"""Application configuration and environment variables."""

import os

from pydantic import model_validator
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

    # Cloud migration - provider switching
    use_local_providers: bool = True

    # AWS configuration (required when use_local_providers is False)
    aws_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    dynamodb_table_name: str = ""

    model_config = {"env_prefix": "SENTIFY_", "env_file": ".env"}

    @model_validator(mode="after")
    def validate_aws_config(self) -> "Settings":
        """Validate that required AWS env vars are set when using cloud providers.

        When use_local_providers is False, all AWS configuration variables must
        be present and non-empty. When True, AWS validation is skipped entirely.
        """
        if self.use_local_providers:
            return self

        required_aws_vars: dict[str, str] = {
            "SENTIFY_AWS_REGION": self.aws_region,
            "SENTIFY_COGNITO_USER_POOL_ID": self.cognito_user_pool_id,
            "SENTIFY_COGNITO_APP_CLIENT_ID": self.cognito_app_client_id,
            "SENTIFY_DYNAMODB_TABLE_NAME": self.dynamodb_table_name,
        }

        missing = [
            name for name, value in required_aws_vars.items() if not value.strip()
        ]

        if missing:
            missing_list = ", ".join(missing)
            raise ValueError(
                f"AWS configuration error: the following required environment "
                f"variable(s) are missing or empty: {missing_list}. "
                f"Set them or switch to local providers with "
                f"SENTIFY_USE_LOCAL_PROVIDERS=true."
            )

        return self


settings = Settings()
