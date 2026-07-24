"""
Property-based tests for LocalAuthProvider.

Feature: sentiment-analysis-platform
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.config import settings as app_settings
from app.core.interfaces.storage_provider import IStorageProvider
from app.infrastructure.auth.local_auth_provider import LocalAuthProvider


# ---------------------------------------------------------------------------
# Helper: create a LocalAuthProvider without storage (only hashing needed)
# ---------------------------------------------------------------------------

def _make_auth_provider() -> LocalAuthProvider:
    """Create a LocalAuthProvider with a dummy storage (not used for hashing)."""
    return LocalAuthProvider(storage=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid passwords: 8-128 printable characters (no null bytes for bcrypt compat)
valid_passwords = st.text(
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=8,
    max_size=128,
)


# ---------------------------------------------------------------------------
# Property 1: Password hashing round-trip
# ---------------------------------------------------------------------------


class TestPasswordHashingRoundTrip:
    """
    Property 1: Password hashing round-trip

    For any valid password string (8–128 characters), hashing it with
    `hash_password` and then verifying the original against the hash with
    `verify_password` SHALL return True.

    **Validates: Requirements 1.4**
    """

    @given(password=valid_passwords)
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_hash_then_verify_returns_true(self, password: str):
        """
        Property 1: Password hashing round-trip

        Hashing a password and verifying the original against the hash
        always returns True.

        **Validates: Requirements 1.4**
        """
        provider = _make_auth_provider()

        hashed = provider.hash_password(password)
        assert provider.verify_password(password, hashed) is True

    @given(
        password=valid_passwords,
        wrong_password=valid_passwords,
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_verify_with_wrong_password_returns_false(
        self, password: str, wrong_password: str
    ):
        """
        Property 1: Password hashing round-trip (negative case)

        Verifying a different password against a hash returns False,
        ensuring the hash is specific to the original password.

        **Validates: Requirements 1.4**
        """
        assume(password != wrong_password)

        provider = _make_auth_provider()

        hashed = provider.hash_password(password)
        assert provider.verify_password(wrong_password, hashed) is False


# ---------------------------------------------------------------------------
# Strategies for Property 2
# ---------------------------------------------------------------------------

# Non-empty user IDs (alphanumeric characters)
valid_user_ids = st.text(
    alphabet=st.characters(
        min_codepoint=48, max_codepoint=122,
        whitelist_categories=("Ll", "Lu", "Nd"),
    ),
    min_size=1,
    max_size=64,
)

# Non-empty company names (printable ASCII)
valid_company_names = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=1,
    max_size=128,
)

# Time offset within 30-minute validity window (0 to 29 min 59 sec)
valid_time_offsets = st.integers(min_value=0, max_value=29 * 60 + 59)

# Time offset after the 30-minute window (30 min + 1 sec to 120 min)
expired_time_offsets = st.integers(min_value=30 * 60 + 1, max_value=120 * 60)


# ---------------------------------------------------------------------------
# Property 2: Token validity window
# ---------------------------------------------------------------------------


class TestTokenValidityWindow:
    """
    Property 2: Token validity window

    For any valid user credentials, authenticating SHALL produce a token
    that is accepted by validate_token when checked within 30 minutes
    of issuance, and rejected when checked after 30 minutes.

    **Validates: Requirements 1.1, 1.3**
    """

    @given(
        user_id=valid_user_ids,
        company_name=valid_company_names,
        seconds_offset=valid_time_offsets,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_token_accepted_within_30_minutes(
        self, user_id: str, company_name: str, seconds_offset: int
    ):
        """
        A token checked within 30 minutes of issuance SHALL be accepted.

        **Validates: Requirements 1.1, 1.3**
        """
        provider = _make_auth_provider()

        # Create a token with issuance time = now, expiry = now + 30 min
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(
            minutes=app_settings.jwt_access_token_expire_minutes
        )

        payload = {
            "user_id": user_id,
            "company_name": company_name,
            "iat": now,
            "exp": expires_at,
        }

        token_str = pyjwt.encode(
            payload,
            app_settings.jwt_secret_key,
            algorithm=app_settings.jwt_algorithm,
        )

        # Validate the token - since exp is 30 min in the future, it is valid
        result = provider.validate_token(token_str)

        assert result is not None
        assert result.user_id == user_id
        assert result.company_name == company_name
        assert result.token == token_str

    @given(
        user_id=valid_user_ids,
        company_name=valid_company_names,
        seconds_past_expiry=expired_time_offsets,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_token_rejected_after_30_minutes(
        self, user_id: str, company_name: str, seconds_past_expiry: int
    ):
        """
        A token checked after 30 minutes of issuance SHALL be rejected.

        **Validates: Requirements 1.1, 1.3**
        """
        provider = _make_auth_provider()

        # Create a token that was issued in the past and has already expired
        now = datetime.now(timezone.utc)
        issued_at = now - timedelta(
            minutes=app_settings.jwt_access_token_expire_minutes
        ) - timedelta(seconds=seconds_past_expiry)
        expires_at = issued_at + timedelta(
            minutes=app_settings.jwt_access_token_expire_minutes
        )

        payload = {
            "user_id": user_id,
            "company_name": company_name,
            "iat": issued_at,
            "exp": expires_at,
        }

        token_str = pyjwt.encode(
            payload,
            app_settings.jwt_secret_key,
            algorithm=app_settings.jwt_algorithm,
        )

        # Validate the token - it should be rejected (expired)
        result = provider.validate_token(token_str)

        assert result is None


# ---------------------------------------------------------------------------
# Helper: In-memory storage provider for authentication property tests
# ---------------------------------------------------------------------------


class _InMemoryStorageProvider(IStorageProvider):
    """Minimal in-memory storage for auth property tests."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"test-user-{self._counter:04d}"

    def create_user(self, email: str, password_hash: str, company_name: str) -> str:
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

    # --- Unused methods (satisfy interface) ---

    def create_batch(self, user_id: str, filename: str) -> str:
        return ""

    def update_batch_status(self, batch_id: str, status: str) -> None:
        pass

    def store_feedback(
        self,
        batch_id: str,
        text: str,
        sentiment: str,
        score: float,
        keywords: list[str],
        status: str,
    ) -> str:
        return ""

    def get_batch_summary(self, batch_id: str) -> dict:
        return {}

    def get_feedbacks_by_keyword(
        self, batch_id: str, keyword: str, page: int, page_size: int = 20
    ) -> dict:
        return {}

    def get_top_keywords(self, batch_id: str, limit: int = 20) -> list[dict]:
        return []

    def get_urgent_feedbacks(
        self, batch_id: str, threshold: float, page: int, page_size: int = 10
    ) -> dict:
        return {}

    def get_user_batches(
        self, user_id: str, page: int, page_size: int = 10
    ) -> dict:
        return {}

    def update_batch_counts(
        self, batch_id: str, total_rows: int, processed_rows: int, error_rows: int
    ) -> None:
        pass

    def store_feedback_error(
        self, batch_id: str, text: str, error_reason: str
    ) -> str:
        return ""


# ---------------------------------------------------------------------------
# Strategies for Property 3
# ---------------------------------------------------------------------------

# Email-like strings for "wrong email" (guaranteed not to match the registered one)
wrong_emails = st.from_regex(
    r"[a-z]{3,12}@[a-z]{3,8}\.(com|org|net)",
    fullmatch=True,
)

# Passwords that differ from the registered one (printable ASCII, 8-64 chars)
wrong_passwords = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=64,
)


# ---------------------------------------------------------------------------
# Property 3: Generic error message on invalid credentials
# ---------------------------------------------------------------------------


class TestGenericErrorMessage:
    """
    Property 3: Generic error message on invalid credentials

    For any combination of invalid credentials (wrong email, wrong password,
    or both), the authentication error message SHALL be identical regardless
    of which field is incorrect.

    **Validates: Requirements 1.2**
    """

    # Fixed known credentials for registration
    KNOWN_EMAIL = "registered-user-property3@empresa.com"
    KNOWN_PASSWORD = "Correct-Password-42!"
    KNOWN_COMPANY = "Empresa Test"

    # Pre-computed bcrypt hash to avoid rehashing on each iteration
    _cached_hash: str | None = None
    _hash_provider: LocalAuthProvider | None = None

    @classmethod
    def _get_password_hash(cls) -> str:
        """Cache the bcrypt hash to avoid slow rehashing on every example."""
        if cls._cached_hash is None:
            provider = LocalAuthProvider(storage=None)  # type: ignore[arg-type]
            cls._cached_hash = provider.hash_password(cls.KNOWN_PASSWORD)
        return cls._cached_hash

    def _setup_provider(self) -> LocalAuthProvider:
        """Create a fresh provider with a registered user (reuses cached hash)."""
        storage = _InMemoryStorageProvider()
        provider = LocalAuthProvider(storage)
        password_hash = self._get_password_hash()
        storage.create_user(self.KNOWN_EMAIL, password_hash, self.KNOWN_COMPANY)
        return provider

    @given(wrong_email=wrong_emails, wrong_password=wrong_passwords)
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_error_message_identical_for_all_invalid_cases(
        self, wrong_email: str, wrong_password: str
    ):
        """
        Property 3: Generic error message on invalid credentials

        The error message returned for wrong email, wrong password, or both
        wrong must be identical — preventing user enumeration attacks.

        **Validates: Requirements 1.2**
        """
        # Ensure generated values actually differ from the known credentials
        assume(wrong_email != self.KNOWN_EMAIL)
        assume(wrong_password != self.KNOWN_PASSWORD)

        provider = self._setup_provider()

        # Case 1: wrong email + correct password
        result_wrong_email = provider.authenticate(wrong_email, self.KNOWN_PASSWORD)

        # Case 2: correct email + wrong password
        result_wrong_password = provider.authenticate(self.KNOWN_EMAIL, wrong_password)

        # Case 3: wrong email + wrong password
        result_both_wrong = provider.authenticate(wrong_email, wrong_password)

        # All three must fail
        assert result_wrong_email.success is False
        assert result_wrong_password.success is False
        assert result_both_wrong.success is False

        # All three must return the exact same error message
        assert result_wrong_email.error == result_wrong_password.error
        assert result_wrong_password.error == result_both_wrong.error

        # Additionally verify it's the expected generic message
        assert result_wrong_email.error == "Credenciales inválidas"


# ---------------------------------------------------------------------------
# Property 4: Account lockout at threshold
# ---------------------------------------------------------------------------


class TestAccountLockoutAtThreshold:
    """
    Property 4: Account lockout at threshold

    For any user account, after exactly 5 consecutive failed authentication
    attempts, the account SHALL be locked, and any further authentication
    attempt (even with correct credentials) within 15 minutes SHALL be
    rejected with a lockout message.

    Feature: sentiment-analysis-platform, Property 4: Account lockout at threshold

    **Validates: Requirements 1.6**
    """

    KNOWN_EMAIL = "lockout-property4@empresa.com"
    KNOWN_PASSWORD = "Secure-Password-99!"
    KNOWN_COMPANY = "Empresa Lockout"

    _cached_hash: str | None = None

    @classmethod
    def _get_password_hash(cls) -> str:
        """Cache the bcrypt hash to avoid slow rehashing on every example."""
        if cls._cached_hash is None:
            provider = LocalAuthProvider(storage=None)  # type: ignore[arg-type]
            cls._cached_hash = provider.hash_password(cls.KNOWN_PASSWORD)
        return cls._cached_hash

    def _setup_provider(self) -> tuple[LocalAuthProvider, _InMemoryStorageProvider]:
        """Create a fresh provider with a registered user."""
        storage = _InMemoryStorageProvider()
        provider = LocalAuthProvider(storage)
        password_hash = self._get_password_hash()
        storage.create_user(self.KNOWN_EMAIL, password_hash, self.KNOWN_COMPANY)
        return provider, storage

    @given(wrong_password=wrong_passwords)
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_account_locks_after_5_failed_attempts(self, wrong_password: str):
        """
        After exactly 5 consecutive failed attempts, the account becomes locked
        and returns account_locked=True with the lockout error message.

        **Validates: Requirements 1.6**
        """
        assume(wrong_password != self.KNOWN_PASSWORD)

        provider, _ = self._setup_provider()

        # Perform 5 consecutive failed attempts
        for i in range(5):
            result = provider.authenticate(self.KNOWN_EMAIL, wrong_password)
            if i < 4:
                # First 4 attempts: account NOT locked yet
                assert result.success is False
                assert result.account_locked is False
                assert result.error == LocalAuthProvider.GENERIC_ERROR
            else:
                # 5th attempt: account IS locked
                assert result.success is False
                assert result.account_locked is True
                assert result.error == LocalAuthProvider.LOCKED_ERROR

    @given(wrong_password=wrong_passwords, correct_after=st.booleans())
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_locked_account_rejects_correct_credentials(
        self, wrong_password: str, correct_after: bool
    ):
        """
        Once locked, even correct credentials are rejected with account_locked=True
        and the lockout error message within the 15-minute window.

        **Validates: Requirements 1.6**
        """
        assume(wrong_password != self.KNOWN_PASSWORD)

        provider, _ = self._setup_provider()

        # Lock the account with 5 failed attempts
        for _ in range(5):
            provider.authenticate(self.KNOWN_EMAIL, wrong_password)

        # Now try with correct credentials — should still be rejected
        result = provider.authenticate(self.KNOWN_EMAIL, self.KNOWN_PASSWORD)
        assert result.success is False
        assert result.account_locked is True
        assert result.error == LocalAuthProvider.LOCKED_ERROR

        # Also try with wrong credentials — should still be rejected
        result_wrong = provider.authenticate(self.KNOWN_EMAIL, wrong_password)
        assert result_wrong.success is False
        assert result_wrong.account_locked is True
        assert result_wrong.error == LocalAuthProvider.LOCKED_ERROR

    @given(
        wrong_password=wrong_passwords,
        num_attempts=st.integers(min_value=1, max_value=4),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_account_not_locked_before_threshold(
        self, wrong_password: str, num_attempts: int
    ):
        """
        Before reaching 5 failed attempts (1-4 failures), the account is NOT locked.

        **Validates: Requirements 1.6**
        """
        assume(wrong_password != self.KNOWN_PASSWORD)

        provider, _ = self._setup_provider()

        # Perform fewer than 5 failed attempts
        for _ in range(num_attempts):
            result = provider.authenticate(self.KNOWN_EMAIL, wrong_password)
            assert result.success is False
            assert result.account_locked is False
            assert result.error == LocalAuthProvider.GENERIC_ERROR

        # After fewer than 5 failures, correct credentials should still work
        result_correct = provider.authenticate(self.KNOWN_EMAIL, self.KNOWN_PASSWORD)
        assert result_correct.success is True
        assert result_correct.account_locked is False
