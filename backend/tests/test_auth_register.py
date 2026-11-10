"""HTTP de POST /api/v1/auth/register.

O serviço confirma a transação de verdade. Estes testes apagam o
usuário criado; não há savepoint em volta do get_db de produção.
"""

import asyncio
import logging
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.security import verify_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.repositories.user import UserRepository

_PASSWORD = "senha-ficticia-ok"
_CLIENT = TestClient(app)


def _email() -> str:
    return f"api-{uuid4().hex}@example.com"


async def _delete_user(email: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


async def _load_user(email: str) -> User | None:
    async with SessionLocal() as session:
        return await UserRepository(session).get_by_email(email)


@pytest.mark.integration
def test_register_returns_public_user_and_stores_argon2id_hash():
    email = _email()
    try:
        response = _CLIENT.post(
            "/api/v1/auth/register",
            json={"name": "Ana Silva", "email": email, "password": _PASSWORD},
        )

        assert response.status_code == 201
        body = response.json()
        assert body == {"detail": "Cadastro processado."}
        assert _PASSWORD not in response.text
        assert "password_hash" not in response.text
        assert "$argon2" not in response.text

        user = asyncio.run(_load_user(email))
        assert user is not None
        assert user.is_active is True
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(_PASSWORD, user.password_hash)
    finally:
        asyncio.run(_delete_user(email))


@pytest.mark.integration
def test_register_existing_email_matches_new_email_response():
    email = _email()
    second_password = "outra-senha-ficticia"
    try:
        first = _CLIENT.post(
            "/api/v1/auth/register",
            json={"name": "Ana Silva", "email": email, "password": _PASSWORD},
        )
        assert first.status_code == 201
        assert first.json() == {"detail": "Cadastro processado."}

        response = _CLIENT.post(
            "/api/v1/auth/register",
            json={
                "name": "Outra Pessoa",
                "email": email,
                "password": second_password,
            },
        )

        assert response.status_code == first.status_code
        assert response.json() == first.json()
        assert response.text == first.text
        assert second_password not in response.text
        assert _PASSWORD not in response.text
        assert "$argon2" not in response.text
        assert "password_hash" not in response.text

        user = asyncio.run(_load_user(email))
        assert user is not None
        assert user.name == "Ana Silva"
        assert verify_password(_PASSWORD, user.password_hash)
    finally:
        asyncio.run(_delete_user(email))


@pytest.mark.integration
def test_register_treats_email_case_as_the_same_identity():
    mixed = f"USUARIO-{uuid4().hex}@EXAMPLE.COM"
    canonical = mixed.lower()
    try:
        first = _CLIENT.post(
            "/api/v1/auth/register",
            json={"name": "Ana Silva", "email": mixed, "password": _PASSWORD},
        )
        assert first.status_code == 201
        assert first.json() == {"detail": "Cadastro processado."}
        created = asyncio.run(_load_user(canonical))
        assert created is not None
        assert created.email == canonical

        response = _CLIENT.post(
            "/api/v1/auth/register",
            json={
                "name": "Ana Silva",
                "email": canonical,
                "password": _PASSWORD,
            },
        )
        assert response.status_code == 201
        assert response.json() == first.json()
        assert _PASSWORD not in response.text
    finally:
        asyncio.run(_delete_user(canonical))


@pytest.mark.integration
def test_register_rejects_short_password_without_leaking_it(caplog):
    secret = "senha-curta"
    leaked_hash = "hash-que-nao-pode-sair"
    caplog.set_level(logging.DEBUG)

    response = _CLIENT.post(
        "/api/v1/auth/register",
        json={
            "name": "Ana Silva",
            "email": _email(),
            "password": secret,
        },
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in caplog.text
    error = response.json()["detail"][0]
    assert error["loc"][-1] == "password"
    assert error["type"] == "string_too_short"
    assert error["msg"]
    assert "input" not in error

    extra = _CLIENT.post(
        "/api/v1/auth/register",
        json={
            "name": "Ana Silva",
            "email": _email(),
            "password": secret,
            "password_hash": leaked_hash,
        },
    )
    assert extra.status_code == 422
    assert secret not in extra.text
    assert leaked_hash not in extra.text
    assert secret not in caplog.text
    assert leaked_hash not in caplog.text


@pytest.mark.integration
def test_register_rejects_nul_in_name_with_422():
    email = _email()
    response = _CLIENT.post(
        "/api/v1/auth/register",
        json={"name": "Ana\u0000Silva", "email": email, "password": _PASSWORD},
    )

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"][-1] == "name"
    assert "input" not in error
    assert asyncio.run(_load_user(email)) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_http_registers_same_email_create_one_row():
    email = _email()
    transport = httpx.ASGITransport(app=app)
    payload = {"name": "Ana Silva", "email": email, "password": _PASSWORD}
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            responses = await asyncio.gather(
                *[client.post("/api/v1/auth/register", json=payload) for _ in range(8)]
            )
        assert {item.status_code for item in responses} == {201}
        bodies = {item.text for item in responses}
        assert bodies == {'{"detail":"Cadastro processado."}'}
        user = await _load_user(email)
        assert user is not None
    finally:
        await _delete_user(email)
