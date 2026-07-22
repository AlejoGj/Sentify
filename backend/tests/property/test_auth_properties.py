"""
Property-based tests for LocalAuthProvider password hashing.

Feature: sentiment-analysis-platform
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

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
        from hypothesis import assume

        assume(password != wrong_password)

        provider = _make_auth_provider()

        hashed = provider.hash_password(password)
        assert provider.verify_password(wrong_password, hashed) is False
