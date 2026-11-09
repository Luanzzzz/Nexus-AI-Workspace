from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

JWT_SECRET_MIN_BYTES = 32
JWT_PLACEHOLDER_SECRETS = frozenset(
    {
        "changeme",
        "change_me",
        "change-me",
        "change_me_local",
        "secret",
        "jwt_secret",
        "jwt-secret",
        "your-secret-key",
        "your_secret_key",
        "default",
        "password",
        "test",
        "none",
    }
)

"""
configuações gerais da aplicação
Attributes:
    app_name: The name of the application.
    environment: The environment of the application.
    debug: Whether the application is in debug mode.
    postgres_user: The username for the PostgreSQL database.
    postgres_password: The password for the PostgreSQL database.
    postgres_db: The database name for the PostgreSQL database.
    jwt_secret_key: Segredo HMAC dos access tokens (obrigatório, >= 32 bytes).
    jwt_algorithm: Algoritmo de assinatura (fixo em HS256).
    jwt_access_token_expire_minutes: Validade do access token em minutos.
    jwt_issuer: Claim "iss" dos tokens.
    jwt_audience: Claim "aud" dos tokens.
"""


class Settings(BaseSettings):
    app_name: str = "Nexus AI Workspace API"
    environment: str = "development"
    debug: bool = False
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_issuer: str = "nexus-ai-workspace"
    jwt_audience: str = "nexus-api"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret.encode("utf-8")) < JWT_SECRET_MIN_BYTES:
            raise ValueError(
                f"JWT_SECRET_KEY deve ter pelo menos {JWT_SECRET_MIN_BYTES} bytes"
            )
        if secret.strip().lower() in JWT_PLACEHOLDER_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY não pode ser um valor padrão ou placeholder"
            )
        return value

    @field_validator("jwt_access_token_expire_minutes")
    @classmethod
    def _validate_expire_minutes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES deve ser positivo")
        return value


settings = Settings()
