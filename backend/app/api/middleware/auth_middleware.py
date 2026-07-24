"""JWT authentication middleware.

Provides a FastAPI dependency that extracts and validates the Bearer token
from the Authorization header, returning the authenticated user's AuthToken.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.interfaces.auth_provider import AuthToken, IAuthProvider
from app.dependencies import get_auth_provider

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    auth_provider: IAuthProvider = Depends(get_auth_provider),
) -> AuthToken:
    """Validate the JWT token and return the current user's AuthToken.

    Raises 401 if the token is missing, invalid, or expired.
    """
    token = credentials.credentials
    auth_token = auth_provider.validate_token(token)

    if auth_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return auth_token
