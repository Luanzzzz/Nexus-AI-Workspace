"""Integração de testes para verificar a dependência do banco de dados."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db

app = FastAPI()


@app.get("/_test/db")
async def db_probe(session: Annotated[AsyncSession, Depends(get_db)]):
    result = await session.execute(text("SELECT 1"))
    return {"result": result.scalar_one()}


@pytest.mark.integration
def test_database_dependency():
    with TestClient(app) as client:
        response = client.get("/_test/db")
        assert response.status_code == 200
        assert response.json() == {"result": 1}
