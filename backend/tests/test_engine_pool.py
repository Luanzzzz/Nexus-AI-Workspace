"""Contrato do engine: pool explícito e parâmetros SQL ocultos."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


def test_engine_uses_explicit_pool_and_hides_parameters():
    sync_engine = engine.sync_engine
    pool = sync_engine.pool

    assert sync_engine.hide_parameters is True
    assert pool._pre_ping is True
    assert pool.size() == settings.db_pool_size
    assert pool._max_overflow == settings.db_max_overflow
    assert pool._timeout == settings.db_pool_timeout


@pytest.mark.integration
@pytest.mark.asyncio
async def test_statement_error_hides_sql_parameters():
    leaked_email = "engine-param-leak@example.com"
    with pytest.raises(Exception) as exc_info:
        async with engine.connect() as connection:
            await connection.execute(
                text("SELECT :email FROM no_such_table_xyz"),
                {"email": leaked_email},
            )

    message = str(exc_info.value)
    assert leaked_email not in message
    assert "parameters hidden" in message.lower() or "parameter" not in message.lower()
