"""AWS Cognito authentication provider."""

import base64
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import jwt
from botocore.exceptions import ClientError, EndpointConnectionError

from app.core.interfaces.auth_provider import AuthResult, AuthToken, IAuthProvider


class CognitoAuthProvider(IAuthProvider):
    """Concrete auth provider using AWS Cognito for user management and authentication.

    Cognito handles password hashing and verification internally, so
    hash_password and verify_password are no-ops per Requirements 10.1, 10.2.
    """

    GENERIC_ERROR = "Credenciales inválidas"
    SERVICE_UNAVAILABLE_ERROR = "Servicio no disponible temporalmente"
    JWKS_CACHE_TTL = timedelta(hours=24)

    def __init__(
        self,
        user_pool_id: str,
        client_id: str,
        region: str,
    ) -> None:
        self._user_pool_id = user_pool_id
        self._client_id = client_id
        self._region = region
        self._client: Any = boto3.client(
            "cognito-idp", region_name=region
        )
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at: datetime | None = None

    def hash_password(self, password: str) -> str:
        """No-op: Cognito manages password hashing internally.

        Returns an empty string regardless of input (Requirement 10.1).
        """
        return ""

    def verify_password(self, password: str, hashed: str) -> bool:
        """No-op: Cognito manages password verification internally.

        Returns False regardless of input (Requirement 10.2).
        """
        return False

    def authenticate(self, email: str, password: str) -> AuthResult:
        """Authenticate user via Cognito USER_PASSWORD_AUTH flow.

        Delegates password verification entirely to Cognito (Requirement 10.3).
        Returns generic error on invalid credentials (Requirement 4.2).
        """
        try:
            response = self._client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                },
                ClientId=self._client_id,
            )

            auth_result = response["AuthenticationResult"]
            id_token = auth_result["IdToken"]

            # Decode JWT payload (middle segment) to extract claims
            payload_segment = id_token.split(".")[1]
            # Add padding for base64 decoding
            padding = 4 - len(payload_segment) % 4
            if padding != 4:
                payload_segment += "=" * padding
            claims = json.loads(base64.urlsafe_b64decode(payload_segment))

            token = AuthToken(
                token=auth_result["AccessToken"],
                expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
                user_id=claims["sub"],
                company_name=claims.get("custom:company_name", ""),
            )

            return AuthResult(success=True, token=token)

        except self._client.exceptions.NotAuthorizedException:
            return AuthResult(success=False, error=self.GENERIC_ERROR)

        except self._client.exceptions.UserNotFoundException:
            return AuthResult(success=False, error=self.GENERIC_ERROR)

        except self._client.exceptions.UserNotConfirmedException:
            return AuthResult(success=False, error="Cuenta no confirmada")

        except self._client.exceptions.TooManyRequestsException:
            return AuthResult(success=False, account_locked=True)

        except (EndpointConnectionError, ConnectionError):
            return AuthResult(success=False, error=self.SERVICE_UNAVAILABLE_ERROR)

        except ClientError:
            return AuthResult(success=False, error=self.SERVICE_UNAVAILABLE_ERROR)

    def _get_jwks(self) -> dict[str, Any] | None:
        """Fetch and cache JWKS keys from the Cognito well-known endpoint.

        Returns the JWKS JSON dict, or None if the endpoint is unreachable
        and no previously cached keys are available.
        Keys are cached for up to 24 hours (JWKS_CACHE_TTL).
        """
        now = datetime.now(tz=timezone.utc)

        # Return cached keys if still within the TTL window
        if (
            self._jwks_cache is not None
            and self._jwks_fetched_at is not None
            and (now - self._jwks_fetched_at) < self.JWKS_CACHE_TTL
        ):
            return self._jwks_cache

        # Build the Cognito JWKS URL from instance config
        url = (
            "https://cognito-idp."
            + self._region
            + ".amazonaws.com/"
            + self._user_pool_id
            + "/.well-known/jwks.json"
        )
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
            jwks = json.loads(raw)
            self._jwks_cache = jwks
            self._jwks_fetched_at = now
            return jwks
        except Exception:
            # Network failure or parse error — fall back to stale cache if available
            return self._jwks_cache

    def validate_token(self, token: str) -> AuthToken | None:
        """Validate a Cognito-issued JWT against the JWKS endpoint.

        Fetches (or reuses a cached copy of) the Cognito JWKS, locates the
        key whose kid matches the token header, verifies the RS256 signature
        and expiration via PyJWT, then returns an AuthToken populated from
        the verified claims.

        Returns None on expired/malformed token, signature mismatch, or when
        the JWKS endpoint is unreachable with no cached keys available.
        Requirements: 4.4, 4.5, 10.4.
        """
        try:
            jwks = self._get_jwks()
            if jwks is None:
                return None

            # Read the key ID from the unverified token header
            headers = jwt.get_unverified_header(token)
            kid = headers.get("kid")
            if kid is None:
                return None

            # Find the matching public key in the JWKS key set
            matching_key_data: dict[str, Any] | None = None
            for key_data in jwks.get("keys", []):
                if key_data.get("kid") == kid:
                    matching_key_data = key_data
                    break

            if matching_key_data is None:
                return None

            # Build a PyJWT-compatible RSA public key from the JWK entry
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
                json.dumps(matching_key_data)
            )

            # Decode and verify: PyJWT checks the signature AND expiration claim
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
            )

            user_id: str = claims["sub"]
            company_name: str = claims.get("custom:company_name", "")
            expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)

            return AuthToken(
                token=token,
                expires_at=expires_at,
                user_id=user_id,
                company_name=company_name,
            )

        except Exception:
            # Covers ExpiredSignatureError, InvalidTokenError, KeyError, network errors
            return None

    def register(self, email: str, password: str, company_name: str) -> AuthResult:
        """Register a new user in Cognito User Pool.

        Validates inputs locally, then calls Cognito sign_up with email as
        username and company_name as a custom attribute.
        """
        # Input validation
        if not email or len(email) > 128:
            return AuthResult(
                success=False,
                error="El email debe tener entre 1 y 128 caracteres",
            )

        if len(password) < 8 or len(password) > 128:
            return AuthResult(
                success=False,
                error="La contraseña debe tener entre 8 y 128 caracteres",
            )

        if not company_name or len(company_name) > 255:
            return AuthResult(
                success=False,
                error="El nombre de empresa debe tener entre 1 y 255 caracteres",
            )

        try:
            self._client.sign_up(
                ClientId=self._client_id,
                Username=email,
                Password=password,
                UserAttributes=[
                    {"Name": "custom:company_name", "Value": company_name},
                ],
            )
            return AuthResult(success=True)

        except self._client.exceptions.UsernameExistsException:
            return AuthResult(
                success=False,
                error="El email ya está registrado",
            )

        except self._client.exceptions.InvalidPasswordException as exc:
            message = exc.response.get("Error", {}).get(
                "Message", "La contraseña no cumple la política de seguridad"
            )
            return AuthResult(success=False, error=message)

        except (ClientError, Exception):
            return AuthResult(
                success=False,
                error=self.SERVICE_UNAVAILABLE_ERROR,
            )

    def refresh_token(self, refresh_token: str) -> AuthResult:
        """Refresh access token using Cognito REFRESH_TOKEN_AUTH flow.

        Implemented in task 4.5.
        """
        raise NotImplementedError("refresh_token will be implemented in task 4.5")
