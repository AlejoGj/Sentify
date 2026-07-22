"""Local authentication provider (bcrypt + JWT)."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings
from app.core.interfaces.auth_provider import AuthResult, AuthToken, IAuthProvider
from app.core.interfaces.storage_provider import IStorageProvider


class LocalAuthProvider(IAuthProvider):
    """Concrete auth provider using bcrypt for passwords and PyJWT for tokens."""

    GENERIC_ERROR = "Credenciales inválidas"
    LOCKED_ERROR = "Cuenta bloqueada temporalmente"

    def __init__(self, storage: IStorageProvider) -> None:
        self._storage = storage

    def hash_password(self, password: str) -> str:
        """Hash a plaintext password with bcrypt."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify a plaintext password against a bcrypt hash."""
        return bcrypt.checkpw(
            password.encode("utf-8"), hashed.encode("utf-8")
        )

    def authenticate(self, email: str, password: str) -> AuthResult:
        """Authenticate user with email and password.

        - Generic error messages that don't reveal which field is wrong.
        - Account lockout after 5 consecutive failed attempts (15 min).
        """
        user = self._storage.get_user_by_email(email)

        if user is None:
            # Don't reveal that the user doesn't exist
            return AuthResult(success=False, error=self.GENERIC_ERROR)

        # Check if account is locked
        locked_until = user.get("locked_until")
        if locked_until is not None:
            if isinstance(locked_until, str):
                locked_until = datetime.fromisoformat(locked_until)
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < locked_until:
                return AuthResult(
                    success=False,
                    error=self.LOCKED_ERROR,
                    account_locked=True,
                )

        # Verify password
        if not self.verify_password(password, user["password_hash"]):
            failed = self._storage.increment_failed_attempts(user["id"])
            if failed >= settings.max_login_attempts:
                lock_until = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.lockout_duration_minutes
                )
                self._storage.lock_account(user["id"], lock_until)
                return AuthResult(
                    success=False,
                    error=self.LOCKED_ERROR,
                    account_locked=True,
                )
            return AuthResult(success=False, error=self.GENERIC_ERROR)

        # Successful authentication — reset failed attempts
        self._storage.reset_failed_attempts(user["id"])

        # Generate JWT token
        token = self._generate_token(user["id"], user["company_name"])
        return AuthResult(success=True, token=token)

    def validate_token(self, token: str) -> AuthToken | None:
        """Validate a JWT token. Returns None if invalid or expired."""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            return AuthToken(
                token=token,
                expires_at=datetime.fromtimestamp(
                    payload["exp"], tz=timezone.utc
                ),
                user_id=payload["user_id"],
                company_name=payload["company_name"],
            )
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    def _generate_token(self, user_id: str, company_name: str) -> AuthToken:
        """Generate a JWT access token with 30-minute expiry."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

        payload = {
            "user_id": user_id,
            "company_name": company_name,
            "iat": now,
            "exp": expires_at,
        }

        token_str = jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )

        return AuthToken(
            token=token_str,
            expires_at=expires_at,
            user_id=user_id,
            company_name=company_name,
        )
