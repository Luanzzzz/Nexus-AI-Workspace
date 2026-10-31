"""1. Importe FastAPI, Depends, Annotated, AsyncSession, text e nossa função get_db.
2. Crie uma aplicação FastAPI() isolada para o teste.
3. Registre um endpoint temporário GET /_test/db.
4. Faça o endpoint receber uma sessão usando Annotated[AsyncSession, Depends(get_db)].
5. Execute SELECT 1 com await session.execute().
6. Retorne o valor obtido em um JSON.
Importante: não utilize SessionLocal() diretamente dentro do endpoint. Queremos que a sessão seja fornecida exclusivamente pelo sistema de dependências do FastAPI."""

from typing import Annotated

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


def test_database_dependency():
    with TestClient(app) as client:
        response = client.get("/_test/db")
        assert response.status_code == 200
        assert response.json() == {"result": 1}
