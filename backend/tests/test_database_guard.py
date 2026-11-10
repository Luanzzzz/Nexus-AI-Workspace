"""Guarda do banco de testes exige nome e host locais."""

import pytest

from app.db.session import engine
from tests.conftest import UnmarkedDatabaseAccessError, is_safe_test_database


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
        engine.sync_engine.connect()
