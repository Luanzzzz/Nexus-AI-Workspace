"""Configuração compartilhada do pytest."""

import os
import secrets
from collections.abc import Iterator

import pytest

from app.core.rate_limit import limiter

# Segredo forte e efêmero, definido antes de qualquer import de app.core.config
# (que instancia Settings no import). Variável de ambiente tem prioridade sobre o .env.
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["AUTH_RATE_LIMIT_ENABLED"] = "false"

from app.db.session import database_url  # noqa: E402

TEST_DATABASE_NAME = "nexus_ai_test"
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _protection_failure_message(
    configured_database: str | None, host: str | None
) -> str:
    return (
        "Proteção do banco de testes: testes de integração só podem acessar "
        f"{TEST_DATABASE_NAME} em {sorted(ALLOWED_TEST_HOSTS)}. "
        f"Banco configurado: {configured_database!r} host={host!r}. "
        "Defina POSTGRES_DB=nexus_ai_test e POSTGRES_HOST local antes do pytest."
    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Interrompe o setup antes das fixtures se o banco não for o de teste."""
    if item.get_closest_marker("integration") is None:
        return

    configured_database = database_url.database
    host = database_url.host
    if configured_database == TEST_DATABASE_NAME and host in ALLOWED_TEST_HOSTS:
        return

    pytest.fail(
        _protection_failure_message(configured_database, host),
        pytrace=False,
    )


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()
