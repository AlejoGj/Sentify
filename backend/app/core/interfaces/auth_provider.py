from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuthToken:
    token: str
    expires_at: datetime
    user_id: str
    company_name: str


@dataclass
class AuthResult:
    success: bool
    token: AuthToken | None = None
    error: str | None = None
    account_locked: bool = False


class IAuthProvider(ABC):
    @abstractmethod
    def authenticate(self, email: str, password: str) -> AuthResult:
        """Autentica usuario con email y contraseña."""
        ...

    @abstractmethod
    def validate_token(self, token: str) -> AuthToken | None:
        """Valida token. Retorna None si inválido o expirado."""
        ...

    @abstractmethod
    def hash_password(self, password: str) -> str:
        """Hashea contraseña con bcrypt."""
        ...

    @abstractmethod
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verifica contraseña contra hash."""
        ...
