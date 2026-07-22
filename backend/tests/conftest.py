"""
Shared test fixtures for Sentify backend tests.

Provides:
- In-memory SQLite database session (db_session)
- FastAPI test client (client)
- Mock providers (INLPProvider, IAuthProvider, IStorageProvider)
- Hypothesis profile configuration (min 100 examples)
"""

from datetime import datetime, timedelta
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from hypothesis import settings, HealthCheck
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.main import app

# ---------------------------------------------------------------------------
# Hypothesis profiles: default enforces min 100 examples per property
# ---------------------------------------------------------------------------
settings.register_profile(
    "default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("default")


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Database fixture (in-memory SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    """Create an in-memory SQLite engine for testing."""
    from app.infrastructure.storage.database import Base

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session bound to an in-memory SQLite database.

    Rolls back after each test for isolation.
    """
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Mock NLP Provider
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_nlp_provider():
    """Mock INLPProvider that returns predictable sentiment results."""
    from app.core.interfaces.nlp_provider import INLPProvider, SentimentResult, NLPError

    class MockNLPProvider(INLPProvider):
        """Deterministic NLP provider for testing."""

        def analyze_sentiment(self, text: str) -> SentimentResult:
            text_lower = text.lower()
            if "malo" in text_lower or "terrible" in text_lower:
                return SentimentResult(
                    sentiment="negativo",
                    score=-0.75,
                    keywords=["malo"],
                )
            elif "bueno" in text_lower or "excelente" in text_lower:
                return SentimentResult(
                    sentiment="positivo",
                    score=0.75,
                    keywords=["bueno"],
                )
            else:
                return SentimentResult(
                    sentiment="neutro",
                    score=0.0,
                    keywords=["producto"],
                )

        def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
            words = [w.lower() for w in text.split() if len(w) > 2]
            return words[:max_keywords]

        def validate_text(self, text: str) -> NLPError | None:
            stripped = text.strip()
            if not stripped:
                return NLPError(feedback_id="", reason="texto_vacio")
            significant_words = [w for w in stripped.split() if len(w) > 2]
            if len(significant_words) < 2:
                return NLPError(feedback_id="", reason="pocas_palabras")
            return None

    return MockNLPProvider()


# ---------------------------------------------------------------------------
# Mock Auth Provider
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth_provider():
    """Mock IAuthProvider with predictable authentication behavior."""
    from app.core.interfaces.auth_provider import IAuthProvider, AuthToken, AuthResult

    class MockAuthProvider(IAuthProvider):
        """Deterministic auth provider for testing."""

        def __init__(self):
            self._valid_email = "test@empresa.com"
            self._valid_password = "test-fixture-pass"
            self._failed_attempts: dict[str, int] = {}
            self._locked_until: dict[str, datetime] = {}

        def authenticate(self, email: str, password: str) -> AuthResult:
            user_id = "user-001"

            # Check lockout
            if user_id in self._locked_until:
                if datetime.utcnow() < self._locked_until[user_id]:
                    return AuthResult(
                        success=False,
                        error="Cuenta bloqueada temporalmente",
                        account_locked=True,
                    )
                else:
                    del self._locked_until[user_id]
                    self._failed_attempts[user_id] = 0

            if email == self._valid_email and password == self._valid_password:
                self._failed_attempts[user_id] = 0
                return AuthResult(
                    success=True,
                    token=AuthToken(
                        token="mock-jwt-token-for-tests",
                        expires_at=datetime.utcnow() + timedelta(minutes=30),
                        user_id=user_id,
                        company_name="Empresa Test",
                    ),
                )
            else:
                attempts = self._failed_attempts.get(user_id, 0) + 1
                self._failed_attempts[user_id] = attempts
                if attempts >= 5:
                    self._locked_until[user_id] = datetime.utcnow() + timedelta(
                        minutes=15
                    )
                    return AuthResult(
                        success=False,
                        error="Cuenta bloqueada temporalmente",
                        account_locked=True,
                    )
                return AuthResult(
                    success=False,
                    error="Credenciales inválidas",
                )

        def validate_token(self, token: str) -> AuthToken | None:
            if token == "mock-jwt-token-for-tests":
                return AuthToken(
                    token=token,
                    expires_at=datetime.utcnow() + timedelta(minutes=30),
                    user_id="user-001",
                    company_name="Empresa Test",
                )
            return None

        def hash_password(self, password: str) -> str:
            return f"hashed_{password}"

        def verify_password(self, password: str, hashed: str) -> bool:
            return hashed == f"hashed_{password}"

    return MockAuthProvider()


# ---------------------------------------------------------------------------
# Mock Storage Provider
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_storage_provider():
    """Mock IStorageProvider using in-memory dictionaries."""
    from app.core.interfaces.storage_provider import IStorageProvider

    class MockStorageProvider(IStorageProvider):
        """In-memory storage provider for testing."""

        def __init__(self):
            self._batches: dict[str, dict] = {}
            self._feedbacks: dict[str, dict] = {}
            self._users: dict[str, dict] = {}
            self._counter = 0

        def _next_id(self) -> str:
            self._counter += 1
            return f"id-{self._counter:04d}"

        def create_batch(self, user_id: str, filename: str) -> str:
            batch_id = self._next_id()
            self._batches[batch_id] = {
                "id": batch_id,
                "user_id": user_id,
                "filename": filename,
                "status": "pendiente",
                "created_at": datetime.utcnow(),
                "total_rows": 0,
                "processed_count": 0,
                "error_count": 0,
            }
            return batch_id

        def update_batch_status(self, batch_id: str, status: str) -> None:
            if batch_id in self._batches:
                self._batches[batch_id]["status"] = status

        def store_feedback(
            self,
            batch_id: str,
            text: str,
            sentiment: str,
            score: float,
            keywords: list[str],
            status: str,
        ) -> str:
            feedback_id = self._next_id()
            self._feedbacks[feedback_id] = {
                "id": feedback_id,
                "batch_id": batch_id,
                "text": text,
                "sentiment": sentiment,
                "score": score,
                "keywords": keywords,
                "status": status,
            }
            return feedback_id

        def get_batch_summary(self, batch_id: str) -> dict:
            feedbacks = [
                f for f in self._feedbacks.values() if f["batch_id"] == batch_id
            ]
            return {
                "total": len(feedbacks),
                "positivo": sum(
                    1 for f in feedbacks if f["sentiment"] == "positivo"
                ),
                "neutro": sum(
                    1 for f in feedbacks if f["sentiment"] == "neutro"
                ),
                "negativo": sum(
                    1 for f in feedbacks if f["sentiment"] == "negativo"
                ),
            }

        def get_feedbacks_by_keyword(
            self, batch_id: str, keyword: str, page: int, page_size: int = 20
        ) -> dict:
            matching = [
                f
                for f in self._feedbacks.values()
                if f["batch_id"] == batch_id and keyword in f["keywords"]
            ]
            start = (page - 1) * page_size
            end = start + page_size
            return {
                "items": matching[start:end],
                "total": len(matching),
                "page": page,
                "page_size": page_size,
            }

        def get_top_keywords(self, batch_id: str, limit: int = 20) -> list[dict]:
            keyword_count: dict[str, int] = {}
            for f in self._feedbacks.values():
                if f["batch_id"] == batch_id:
                    for kw in f["keywords"]:
                        keyword_count[kw] = keyword_count.get(kw, 0) + 1
            sorted_kw = sorted(
                keyword_count.items(), key=lambda x: x[1], reverse=True
            )
            return [{"word": w, "count": c} for w, c in sorted_kw[:limit]]

        def get_urgent_feedbacks(
            self, batch_id: str, threshold: float, page: int, page_size: int = 10
        ) -> dict:
            urgent = [
                f
                for f in self._feedbacks.values()
                if f["batch_id"] == batch_id and f["score"] < threshold
            ]
            urgent.sort(key=lambda x: x["score"])
            start = (page - 1) * page_size
            end = start + page_size
            return {
                "items": urgent[start:end],
                "total": len(urgent),
                "page": page,
                "page_size": page_size,
            }

        def get_user_batches(
            self, user_id: str, page: int, page_size: int = 10
        ) -> dict:
            user_batches = [
                b
                for b in self._batches.values()
                if b["user_id"] == user_id
            ]
            user_batches.sort(key=lambda x: x["created_at"], reverse=True)
            start = (page - 1) * page_size
            end = start + page_size
            return {
                "items": user_batches[start:end],
                "total": len(user_batches),
                "page": page,
                "page_size": page_size,
            }

        def create_user(
            self, email: str, password_hash: str, company_name: str
        ) -> str:
            user_id = self._next_id()
            self._users[user_id] = {
                "id": user_id,
                "email": email,
                "password_hash": password_hash,
                "company_name": company_name,
                "failed_attempts": 0,
                "locked_until": None,
            }
            return user_id

        def get_user_by_email(self, email: str) -> dict | None:
            for user in self._users.values():
                if user["email"] == email:
                    return user
            return None

        def increment_failed_attempts(self, user_id: str) -> int:
            if user_id in self._users:
                self._users[user_id]["failed_attempts"] += 1
                return self._users[user_id]["failed_attempts"]
            return 0

        def reset_failed_attempts(self, user_id: str) -> None:
            if user_id in self._users:
                self._users[user_id]["failed_attempts"] = 0

        def lock_account(self, user_id: str, until: datetime) -> None:
            if user_id in self._users:
                self._users[user_id]["locked_until"] = until

    return MockStorageProvider()
