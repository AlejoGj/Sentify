"""
Property-based tests for SQLiteStorageProvider.

Feature: sentiment-analysis-platform
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models.base import Base
from app.core.models.user import User  # noqa: F401
from app.core.models.batch import Batch  # noqa: F401
from app.core.models.feedback import Feedback
from app.core.models.keyword import Keyword  # noqa: F401
from app.infrastructure.storage.sqlite_storage_provider import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helper: create a fresh storage provider with in-memory SQLite
# ---------------------------------------------------------------------------

def _make_storage_provider():
    """Create a fresh in-memory SQLite storage provider with user and batch."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    storage = SQLiteStorageProvider(session_factory)

    # Create a user and batch required for storing feedback
    user_id = storage.create_user("prop_test@test.com", "hashed_pw", "Test Corp")
    batch_id = storage.create_batch(user_id, "test.csv")

    return storage, session_factory, batch_id


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_sentiments = st.sampled_from(["positivo", "neutro", "negativo"])
valid_scores = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
feedback_text = st.text(min_size=1, max_size=5000)


# ---------------------------------------------------------------------------
# Property 12: Feedback text persistence round-trip
# ---------------------------------------------------------------------------


class TestFeedbackTextPersistenceRoundTrip:
    """
    Property 12: Feedback text persistence round-trip

    For any text string of at most 5,000 characters, storing it as a feedback
    and then retrieving it SHALL return the exact original text without
    modification, along with its computed sentiment and score.

    **Validates: Requirements 5.1, 5.4**
    """

    @given(
        text=feedback_text,
        sentiment=valid_sentiments,
        score=valid_scores,
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_round_trip_preserves_text_sentiment_and_score(
        self, text: str, sentiment: str, score: float
    ):
        """
        Property 12: Feedback text persistence round-trip

        Storing a feedback and retrieving it preserves the original text,
        sentiment, and score exactly.

        **Validates: Requirements 5.1, 5.4**
        """
        storage, session_factory, batch_id = _make_storage_provider()

        # Store feedback with a known keyword (>2 chars, lowercase)
        feedback_id = storage.store_feedback(
            batch_id=batch_id,
            text=text,
            sentiment=sentiment,
            score=score,
            keywords=["testword"],
            status="success",
        )

        # Retrieve directly from the database to verify round-trip
        session = session_factory()
        try:
            feedback = session.query(Feedback).filter(Feedback.id == feedback_id).first()

            assert feedback is not None, "Feedback should be persisted"
            assert feedback.original_text == text, (
                f"Text round-trip failed: stored {len(text)} chars, "
                f"got back {len(feedback.original_text)} chars"
            )
            assert feedback.sentiment == sentiment, (
                f"Sentiment mismatch: expected {sentiment!r}, got {feedback.sentiment!r}"
            )
            assert feedback.score == score, (
                f"Score mismatch: expected {score}, got {feedback.score}"
            )
        finally:
            session.close()
