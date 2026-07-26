"""Dependency injection configuration.

Provides FastAPI dependency functions that wire interface ABCs
to their concrete implementations. When use_local_providers is True,
returns local providers (SQLite, bcrypt/PyJWT, spaCy). When False,
returns AWS-based providers (DynamoDB, Cognito, Comprehend).
"""

from functools import lru_cache

from app.config import settings
from app.core.interfaces.auth_provider import IAuthProvider
from app.core.interfaces.nlp_provider import INLPProvider
from app.core.interfaces.storage_provider import IStorageProvider


@lru_cache
def get_storage_provider() -> IStorageProvider:
    """Return the singleton storage provider instance."""
    if settings.use_local_providers:
        from app.infrastructure.storage.database import get_session
        from app.infrastructure.storage.sqlite_storage_provider import (
            SQLiteStorageProvider,
        )

        return SQLiteStorageProvider(session_factory=get_session)
    else:
        from app.infrastructure.storage.dynamodb_storage_provider import (
            DynamoDBStorageProvider,
        )

        return DynamoDBStorageProvider(
            table_name=settings.dynamodb_table_name,
            region=settings.aws_region,
        )


@lru_cache
def get_auth_provider() -> IAuthProvider:
    """Return the singleton auth provider instance."""
    if settings.use_local_providers:
        from app.infrastructure.auth.local_auth_provider import LocalAuthProvider

        storage = get_storage_provider()
        return LocalAuthProvider(storage)
    else:
        from app.infrastructure.auth.cognito_auth_provider import (
            CognitoAuthProvider,
        )

        return CognitoAuthProvider(
            user_pool_id=settings.cognito_user_pool_id,
            client_id=settings.cognito_app_client_id,
            region=settings.aws_region,
        )


@lru_cache
def get_nlp_provider() -> INLPProvider:
    """Return the singleton NLP provider instance."""
    if settings.use_local_providers:
        from app.infrastructure.nlp.spacy_nlp_provider import SpaCyNLPProvider

        return SpaCyNLPProvider()
    else:
        from app.infrastructure.nlp.comprehend_nlp_provider import (
            ComprehendNLPProvider,
        )

        return ComprehendNLPProvider(region=settings.aws_region)
