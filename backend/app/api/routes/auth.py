"""Authentication routes.

POST /api/v1/auth/login   — Authenticate user and return JWT token.
POST /api/v1/auth/register — Create a new user account.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.interfaces.auth_provider import IAuthProvider
from app.core.interfaces.storage_provider import IStorageProvider
from app.core.models.schemas import LoginRequest, LoginResponse, RegisterRequest
from app.dependencies import get_auth_provider, get_storage_provider

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    auth_provider: IAuthProvider = Depends(get_auth_provider),
) -> LoginResponse:
    """Authenticate user with email and password.

    Returns JWT token and company name on success.
    Returns 401 for invalid credentials, 423 for locked accounts.
    """
    result = auth_provider.authenticate(request.email, request.password)

    if not result.success:
        if result.account_locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=result.error,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.error,
        )

    # result.token is guaranteed non-None when success=True
    assert result.token is not None
    return LoginResponse(
        token=result.token.token,
        expires_at=result.token.expires_at,
        company_name=result.token.company_name,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    auth_provider: IAuthProvider = Depends(get_auth_provider),
    storage: IStorageProvider = Depends(get_storage_provider),
) -> dict[str, str]:
    """Register a new user account.

    Returns the created user_id. Returns 409 if email already exists.
    """
    # Check if email is already registered
    existing = storage.get_user_by_email(request.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está registrado",
        )

    # Hash password and create user
    password_hash = auth_provider.hash_password(request.password)
    user_id = storage.create_user(
        email=request.email,
        password_hash=password_hash,
        company_name=request.company_name,
    )

    return {"user_id": user_id, "message": "Usuario registrado exitosamente"}
