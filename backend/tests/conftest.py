"""Configuração compartilhada do pytest."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from contextvars import ContextVar

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.pool.base import Pool

from app.core.rate_limit import (
    limiter,
    upload_concurrency,
    upload_limiter,
    workspace_create_limiter,
)

# Segredo forte e efêmero, definido antes de qualquer import de app.core.config
# (que instancia Settings no import). Variável de ambiente tem prioridade sobre o .env.
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["AUTH_RATE_LIMIT_ENABLED"] = "false"
os.environ["UPLOAD_LIMITS_ENABLED"] = "false"
os.environ["WORKSPACE_CREATE_RATE_LIMIT_ENABLED"] = "false"

from app.db.session import database_url  # noqa: E402

TEST_DATABASE_NAME = "nexus_ai_test"
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNMARKED_DB_ACCESS_MESSAGE = (
    "Teste sem @pytest.mark.integration tentou abrir conexão com o banco "
    "antes de qualquer SQL. Marque o teste com @pytest.mark.integration "
    "ou não acesse o PostgreSQL."
)

_allow_marked_connect: ContextVar[bool] = ContextVar(
    "allow_marked_connect", default=False
)
_guards_installed = False
_original_dialect_connect = DefaultDialect.connect
_original_pool_connect = Pool.connect
_original_psycopg_connect = psycopg.connect
_original_connection_connect = psycopg.Connection.connect
_original_async_connection_connect = psycopg.AsyncConnection.connect


class UnmarkedDatabaseAccessError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(UNMARKED_DB_ACCESS_MESSAGE)


class UnsafeTestDatabaseError(RuntimeError):
    def __init__(self, database: str | None, host: str | None) -> None:
        super().__init__(_protection_failure_message(database, host))


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


def _effective_dbname_and_host(
    *cargs: object, **cparams: object
) -> tuple[str | None, str | None]:
    merged: dict[str, object] = {}
    if cargs and isinstance(cargs[0], str) and cargs[0]:
        try:
            merged.update(conninfo_to_dict(cargs[0]))
        except Exception:
            pass
    merged.update(cparams)
    dbname = merged.get("dbname", merged.get("database"))
    host = merged.get("host")
    return (
        str(dbname) if dbname is not None else None,
        str(host) if host is not None else None,
    )


def _assert_connection_allowed(*cargs: object, **cparams: object) -> None:
    dbname, host = _effective_dbname_and_host(*cargs, **cparams)
    if not is_safe_test_database(dbname, host):
        raise UnsafeTestDatabaseError(dbname, host)
    if not _allow_marked_connect.get():
        raise UnmarkedDatabaseAccessError()


def _guarded_dialect_connect(self: object, *cargs: object, **cparams: object):
    _assert_connection_allowed(*cargs, **cparams)
    return _original_dialect_connect(self, *cargs, **cparams)


def _guarded_psycopg_connect(*cargs: object, **cparams: object):
    _assert_connection_allowed(*cargs, **cparams)
    return _original_psycopg_connect(*cargs, **cparams)


def _guarded_connection_connect(*cargs: object, **cparams: object):
    _assert_connection_allowed(*cargs, **cparams)
    return _original_connection_connect(*cargs, **cparams)


async def _guarded_async_connection_connect(*cargs: object, **cparams: object):
    _assert_connection_allowed(*cargs, **cparams)
    return await _original_async_connection_connect(*cargs, **cparams)


def _guarded_pool_connect(self: Pool):
    if not _allow_marked_connect.get():
        raise UnmarkedDatabaseAccessError()
    return _original_pool_connect(self)


def _install_connection_guards() -> None:
    global _guards_installed
    if _guards_installed:
        return
    DefaultDialect.connect = _guarded_dialect_connect  # type: ignore[method-assign]
    Pool.connect = _guarded_pool_connect  # type: ignore[method-assign]
    psycopg.connect = _guarded_psycopg_connect  # type: ignore[assignment]
    psycopg.Connection.connect = _guarded_connection_connect  # type: ignore[method-assign]
    psycopg.AsyncConnection.connect = _guarded_async_connection_connect  # type: ignore[method-assign]
    _guards_installed = True


def pytest_configure(config: pytest.Config) -> None:
    _install_connection_guards()


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


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    if item.get_closest_marker("integration") is None:
        yield
        return
    token = _allow_marked_connect.set(True)
    try:
        yield
    finally:
        _allow_marked_connect.reset(token)


def _reset_all_limiters() -> None:
    limiter.reset()
    upload_limiter.reset()
    workspace_create_limiter.reset()
    upload_concurrency.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    _reset_all_limiters()
    yield
    _reset_all_limiters()


@pytest.fixture(autouse=True)
def _isolated_document_storage(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Nenhum teste escreve no diretório real de documentos."""
    from app.core.config import settings

    isolated = tmp_path_factory.mktemp("default-document-storage")
    monkeypatch.setattr(settings, "document_storage_dir", isolated)
    yield
