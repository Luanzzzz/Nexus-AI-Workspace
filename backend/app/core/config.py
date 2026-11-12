from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

JWT_SECRET_MIN_BYTES = 32
JWT_SECRET_MIN_UNIQUE_CHARS = 10
JWT_SECRET_MIN_ENTROPY_BITS = 3.0
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
    environment: development, test ou production (ENVIRONMENT).
    debug: Modo debug (DEBUG). Padrão False; só altera o FastAPI em development.
    postgres_user: The username for the PostgreSQL database.
    postgres_password: The password for the PostgreSQL database.
    postgres_db: The database name for the PostgreSQL database.
    jwt_secret_key: Segredo HMAC dos access tokens (obrigatório, >= 32 bytes).
    jwt_algorithm: Algoritmo de assinatura (fixo em HS256).
    jwt_access_token_expire_minutes: Validade do access token em minutos.
    jwt_issuer: Claim "iss" dos tokens.
    jwt_audience: Claim "aud" dos tokens.
"""


def _shannon_entropy(value: str) -> float:
    length = len(value)
    if length == 0:
        return 0.0
    counts = Counter(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _compact_secret(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


_KEYBOARD_ROWS = (
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "1234567890",
)
_KEYBOARD_CONCAT = "".join(_KEYBOARD_ROWS)


def _is_keyboard_sequence(secret: str) -> bool:
    compact = _compact_secret(secret)
    if len(compact) < JWT_SECRET_MIN_BYTES:
        return False
    if compact in _KEYBOARD_CONCAT or compact[::-1] in _KEYBOARD_CONCAT:
        return True
    window = 10
    haystacks = tuple(row + row[::-1] + row for row in _KEYBOARD_ROWS) + (
        _KEYBOARD_CONCAT,
        _KEYBOARD_CONCAT[::-1],
    )
    for index in range(0, len(compact) - window + 1):
        chunk = compact[index : index + window]
        if any(chunk in haystack for haystack in haystacks):
            return True
    return False


def _is_placeholder_secret(secret: str) -> bool:
    compact = _compact_secret(secret)
    if not compact:
        return True
    for placeholder in JWT_PLACEHOLDER_SECRETS:
        token = _compact_secret(placeholder)
        if not token:
            continue
        if compact == token:
            return True
        if compact.replace(token, "") == "":
            return True
    return False


class Settings(BaseSettings):
    app_name: str = "Nexus AI Workspace API"
    environment: Literal["development", "test", "production"] = "development"
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
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_pre_ping: bool = True
    auth_rate_limit_enabled: bool = True
    auth_login_per_email_limit: int = 5
    auth_login_per_ip_limit: int = 20
    auth_register_per_ip_limit: int = 5
    auth_rate_limit_window_seconds: int = 60
    trusted_proxies: str = ""
    # Diretório do storage de documentos: fora de qualquer pasta pública e do Git.
    document_storage_dir: Path = ROOT_DIR / "backend" / "var" / "documents"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret != secret.strip() or not secret.strip():
            raise ValueError(
                "JWT_SECRET_KEY não pode ser vazio nem conter espaços nas extremidades"
            )
        if len(secret.encode("utf-8")) < JWT_SECRET_MIN_BYTES:
            raise ValueError(
                f"JWT_SECRET_KEY deve ter pelo menos {JWT_SECRET_MIN_BYTES} bytes"
            )
        if _is_placeholder_secret(secret):
            raise ValueError(
                "JWT_SECRET_KEY não pode ser um valor padrão ou placeholder"
            )
        if len(set(secret)) < JWT_SECRET_MIN_UNIQUE_CHARS:
            raise ValueError("JWT_SECRET_KEY tem entropia insuficiente")
        if _shannon_entropy(secret) < JWT_SECRET_MIN_ENTROPY_BITS:
            raise ValueError("JWT_SECRET_KEY tem entropia insuficiente")
        if _is_keyboard_sequence(secret):
            raise ValueError("JWT_SECRET_KEY tem entropia insuficiente")
        return value

    @field_validator("jwt_access_token_expire_minutes")
    @classmethod
    def _validate_expire_minutes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES deve ser positivo")
        return value

    @field_validator(
        "db_pool_size",
        "db_pool_timeout",
        "auth_login_per_email_limit",
        "auth_login_per_ip_limit",
        "auth_register_per_ip_limit",
        "auth_rate_limit_window_seconds",
    )
    @classmethod
    def _validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("valor deve ser positivo")
        return value

    @field_validator("db_max_overflow")
    @classmethod
    def _validate_overflow(cls, value: int) -> int:
        if value < 0:
            raise ValueError("DB_MAX_OVERFLOW não pode ser negativo")
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _validate_trusted_proxies(cls, value: str) -> str:
        tokens = [token.strip() for token in value.split(",")]
        if any(token == "*" for token in tokens):
            raise ValueError("TRUSTED_PROXIES não pode ser *")
        return value

    @model_validator(mode="after")
    def _forbid_debug_in_production(self) -> Settings:
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG deve ser False quando ENVIRONMENT=production")
        return self

    @property
    def fastapi_debug(self) -> bool:
        return self.debug and self.environment == "development"

    @property
    def expose_openapi(self) -> bool:
        return self.environment != "production"


settings = Settings()
