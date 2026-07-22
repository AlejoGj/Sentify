"""Application configuration and environment variables."""

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All sensitive values MUST be provided via environment variables
    (prefixed with SENTIFY_) or a .env file.
    """

    # Database
    database_url: str = "sqlite:///./sentify.db"

    # JWT Authentication - MUST be set via SENTIFY_JWT_SECRET_KEY env var
    jwt_secret_key: str = os.getenv("SENTIFY_JWT_SECRET_KEY", "CHANGE_ME")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # Auth
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15

    # NLP
    spacy_model: str = "es_core_news_md"

    # CSV Upload
    max_file_size_mb: int = 10
    max_csv_rows: int = 50000

    model_config = {"env_prefix": "SENTIFY_", "env_file": ".env"}


settings = Settings()
