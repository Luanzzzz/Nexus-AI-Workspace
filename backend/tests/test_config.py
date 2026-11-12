import os
import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Nexus AI Workspace API")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")

    test_settings = Settings(_env_file=None)

    assert test_settings.app_name == "Nexus AI Workspace API"
    assert test_settings.environment == "test"
    assert test_settings.debug is True


def _strong_secret() -> str:
    return secrets.token_urlsafe(32)


def test_settings_jwt_defaults(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())

    test_settings = Settings(_env_file=None)

    assert test_settings.jwt_algorithm == "HS256"
    assert test_settings.jwt_access_token_expire_minutes == 30
    assert test_settings.jwt_issuer == "nexus-ai-workspace"
    assert test_settings.jwt_audience == "nexus-api"
    assert "JWT_SECRET" not in repr(test_settings)
    assert test_settings.jwt_secret_key.get_secret_value() not in repr(test_settings)


def test_settings_rejects_missing_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 31)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("placeholder", ["changeme", "CHANGE_ME_LOCAL", "secret", ""])
def test_settings_rejects_placeholder_jwt_secret(monkeypatch, placeholder):
    monkeypatch.setenv("JWT_SECRET_KEY", placeholder)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "weak",
    [
        "a" * 32,
        "changemechangemechangemechangeme",
        "CHANGE_ME_LOCAL_CHANGE_ME_LOCAL_",
        "your-secret-key-your-secret-key!",
        " " * 32,
        "qwertyuiopasdfghjklzxcvbnm123456",
    ],
)
def test_settings_rejects_weak_or_placeholder_jwt_secret(monkeypatch, weak):
    monkeypatch.setenv("JWT_SECRET_KEY", weak)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    stripped = weak.strip()
    if stripped:
        assert stripped not in message
        if len(stripped) >= 8:
            assert stripped[:8] not in message


def test_settings_rejects_other_jwt_algorithm(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("JWT_ALGORITHM", "none")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_non_positive_expiration(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_debug_defaults_to_false(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    test_settings = Settings(_env_file=None)

    assert test_settings.debug is False
    assert test_settings.environment == "development"


def test_settings_rejects_debug_in_production(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "true")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    secret = os.environ["JWT_SECRET_KEY"]
    assert "DEBUG deve ser False" in message
    assert secret not in message
    assert secret[-8:] not in message
    assert secret[:8] not in message


def test_settings_accepts_production_without_debug(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")

    test_settings = Settings(_env_file=None)

    assert test_settings.environment == "production"
    assert test_settings.debug is False


def test_settings_accepts_debug_in_development(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEBUG", "true")

    assert Settings(_env_file=None).debug is True


def test_settings_accepts_zero_pool_overflow(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")

    assert Settings(_env_file=None).db_max_overflow == 0


def test_settings_rejects_skewed_low_entropy_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 40 + "bcdefghij")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_fastapi_debug_only_in_development(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")

    loaded = Settings(_env_file=None)
    assert loaded.debug is True
    assert loaded.fastapi_debug is False


def test_settings_rejects_unknown_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("ENVIRONMENT", "prod")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["*", " * ", "10.0.0.1,*", "*,10.0.0.1"])
def test_settings_rejects_star_trusted_proxies(monkeypatch, value):
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())
    monkeypatch.setenv("TRUSTED_PROXIES", value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "TRUSTED_PROXIES não pode ser *" in str(exc_info.value)


_PHASE3_LIMIT_ENV = (
    "UPLOAD_LIMITS_ENABLED",
    "UPLOAD_RATE_LIMIT_PER_MINUTE",
    "UPLOAD_MAX_CONCURRENT_PER_USER",
    "WORKSPACE_MAX_DOCUMENTS",
    "WORKSPACE_MAX_STORAGE_BYTES",
    "WORKSPACE_MAX_OWNED_PER_USER",
    "WORKSPACE_CREATE_RATE_LIMIT_ENABLED",
    "WORKSPACE_CREATE_RATE_LIMIT_PER_HOUR",
)


def test_phase3_limits_have_secure_defaults(monkeypatch):
    # O conftest desliga os limites por variável de ambiente; aqui elas saem e
    # o .env do desenvolvedor não é lido (_env_file=None): só valem os padrões.
    for name in _PHASE3_LIMIT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", _strong_secret())

    defaults = Settings(_env_file=None)

    assert defaults.upload_limits_enabled is True
    assert defaults.upload_rate_limit_per_minute == 20
    assert defaults.upload_max_concurrent_per_user == 2
    assert defaults.workspace_max_documents == 1000
    assert defaults.workspace_max_storage_bytes == 1_073_741_824
    assert defaults.workspace_max_owned_per_user == 10
    assert defaults.workspace_create_rate_limit_enabled is True
    assert defaults.workspace_create_rate_limit_per_hour == 10


def test_lock_timeout_constants_are_pinned():
    from app.services.document import MEMBERSHIP_LOCK_TIMEOUT_MS
    from app.services.workspace import OWNER_LOCK_TIMEOUT_MS

    assert MEMBERSHIP_LOCK_TIMEOUT_MS == 5000
    assert OWNER_LOCK_TIMEOUT_MS == 5000
