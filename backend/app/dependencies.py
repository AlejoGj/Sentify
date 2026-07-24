"""Dependency injection configuration.

Provides FastAPI dependency functions that wire interface ABCs
to their concrete implementations.
"""

from functools import lru_cache

from app.core.interfaces.auth_provider import IAuthProvider
from app.core.interfaces.nlp_provider import INLPProvider
from app.core.interfaces.storage_provider import IStorageProvider
from app.infrastructure.auth.local_auth_provider import LocalAuthProvider
from app.infrastructure.nlp.spacy_nlp_provider import SpaCyNLPProvider
from app.infrastructure.storage.database import get_session
from app.infrastructure.storage.sqlite_storage_provider import SQLiteStorageProvider


@lru_cache
def get_storage_provider() -> IStorageProvider:
    """Return the singleton storage provider instance."""
    return SQLiteStorageProvider(session_factory=get_session)


@lru_cache
def get_auth_provider() -> IAuthProvider:
    """Return the singleton auth provider instance."""
    storage = get_storage_provider()
    return LocalAuthProvider(storage)


@lru_cache
def get_nlp_provider() -> INLPProvider:
    """Return the singleton NLP provider instance."""
    return SpaCyNLPProvider()
