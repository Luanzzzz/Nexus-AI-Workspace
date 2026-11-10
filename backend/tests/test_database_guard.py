"""Guarda do banco de testes exige nome e host locais."""

import psycopg
import pytest
from psycopg import connect as imported_psycopg_connect
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db.session import SessionLocal, database_url
from tests.conftest import (
    UnmarkedDatabaseAccessError,
    UnsafeTestDatabaseError,
    is_safe_test_database,
)

_CONNINFO = "host=127.0.0.1 port=1 dbname=nexus_ai_test user=nobody password=invalid"
_SAFE_URL = "postgresql+psycopg://nobody:invalid@127.0.0.1:1/nexus_ai_test"


@pytest.fixture(scope="module")
def module_scope_guard_blocks_connect() -> bool:
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        psycopg.connect(_CONNINFO)
    return True


@pytest.fixture(scope="session")
def session_scope_guard_blocks_connect() -> bool:
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        psycopg.connect(_CONNINFO)
    return True


def test_guard_allows_only_local_test_database():
    assert is_safe_test_database("nexus_ai_test", "127.0.0.1")
    assert is_safe_test_database("nexus_ai_test", "localhost")
    assert not is_safe_test_database("nexus_ai_test", "db.example.com")
    assert not is_safe_test_database("nexus_ai", "127.0.0.1")
    assert not is_safe_test_database("nexus_ai_test", None)


def test_unmarked_test_cannot_open_database_connection():
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        psycopg.connect(_CONNINFO)


def test_unmarked_psycopg_connect_is_blocked():
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        psycopg.connect(_CONNINFO)


def test_unmarked_imported_psycopg_connect_is_blocked():
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        imported_psycopg_connect(_CONNINFO)


def test_unmarked_sync_create_engine_is_blocked():
    sync_engine = create_engine(_SAFE_URL)
    try:
        with pytest.raises(
            UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
        ):
            sync_engine.connect()
    finally:
        sync_engine.dispose()


def test_unmarked_sync_create_engine_nullpool_is_blocked():
    sync_engine = create_engine(_SAFE_URL, poolclass=NullPool)
    try:
        with pytest.raises(
            UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
        ):
            sync_engine.connect()
    finally:
        sync_engine.dispose()


def test_module_scoped_fixture_cannot_open_database(
    module_scope_guard_blocks_connect: bool,
):
    assert module_scope_guard_blocks_connect


def test_session_scoped_fixture_cannot_open_database(
    session_scope_guard_blocks_connect: bool,
):
    assert session_scope_guard_blocks_connect


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_warms_app_pool():
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))


@pytest.mark.asyncio
async def test_unmarked_cannot_reuse_app_pool_after_integration():
    with pytest.raises(
        UnmarkedDatabaseAccessError, match="sem @pytest.mark.integration"
    ):
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))


@pytest.mark.integration
def test_integration_rejects_wrong_database_name():
    wrong_url = database_url.set(database="nexus_ai", port=1)
    sync_engine = create_engine(wrong_url)
    try:
        with pytest.raises(
            UnsafeTestDatabaseError, match="Proteção do banco de testes"
        ):
            sync_engine.connect()
    finally:
        sync_engine.dispose()
