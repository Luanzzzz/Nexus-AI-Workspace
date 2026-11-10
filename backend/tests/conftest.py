"""Configuração compartilhada do pytest."""

import os
import secrets
from collections.abc import Iterator

import psycopg
import pytest

from app.core.rate_limit import limiter

# Segredo forte e efêmero, definido antes de qualquer import de app.core.config
# (que instancia Settings no import). Variável de ambiente tem prioridade sobre o .env.
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["AUTH_RATE_LIMIT_ENABLED"] = "false"

from app.db.session import database_url, engine  # noqa: E402

TEST_DATABASE_NAME = "nexus_ai_test"
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNMARKED_DB_ACCESS_MESSAGE = (
    "Teste sem @pytest.mark.integration tentou abrir conexão com o banco "
    "antes de qualquer SQL. Marque o teste com @pytest.mark.integration "
    "ou não acesse o PostgreSQL."
)


class UnmarkedDatabaseAccessError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(UNMARKED_DB_ACCESS_MESSAGE)


def is_safe_test_database(database: str | None, host: str | None) -> bool:
    return database == TEST_DATABASE_NAME and host in ALLOWED_TEST_HOSTS


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
    if is_safe_test_database(configured_database, host):
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


@pytest.fixture(autouse=True)
def _block_unmarked_database_access(
    request: pytest.FixtureRequest, monkeypatch
) -> Iterator[None]:
    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    def _blocked_sync(*_args, **_kwargs):
        raise UnmarkedDatabaseAccessError()

    async def _blocked_async(*_args, **_kwargs):
        raise UnmarkedDatabaseAccessError()

    monkeypatch.setattr(engine.sync_engine.dialect, "connect", _blocked_sync)
    monkeypatch.setattr(engine.sync_engine.pool, "connect", _blocked_sync)
    monkeypatch.setattr(psycopg.Connection, "connect", _blocked_sync)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _blocked_async)
    yield
