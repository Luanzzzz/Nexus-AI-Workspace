"""HTTP de POST /api/v1/auth/login.

Os usuários são gravados com commit (o get_db de produção não usa
savepoint) e apagados no fim de cada teste.
"""

import asyncio
import logging
from collections.abc import Iterator
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.exceptions import CredentialVerificationError
from app.core.security import hash_password
from app.core.tokens import decode_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import LoginRequest
from app.services.auth import AuthService

_URL = "/api/v1/auth/login"
_PASSWORD = "senha-ficticia-ok"
_WRONG_PASSWORD = "senha-errada-ficticia"
_CLIENT = TestClient(app)
# Erros inesperados viram 500 pelo handler; o cliente não deve relançá-los.
_SAFE_CLIENT = TestClient(app, raise_server_exceptions=False)


def _email() -> str:
    return f"login-api-{uuid4().hex}@example.com"


async def _create_user(email: str, *, is_active: bool = True) -> tuple[int, str]:
    password_hash = hash_password(_PASSWORD)
    async with SessionLocal() as session:
        user = await UserRepository(session).create_user(
            name="Ana Silva", email=email, password_hash=password_hash
        )
        user.is_active = is_active
        await session.commit()
        return user.id, password_hash


async def _delete_user(email: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


@pytest.fixture
def active_user() -> Iterator[tuple[int, str, str]]:
    email = _email()
    user_id, password_hash = asyncio.run(_create_user(email))
    try:
        yield user_id, email, password_hash
    finally:
        asyncio.run(_delete_user(email))


def _assert_no_leaks(text: str, *extra: str) -> None:
    for forbidden in (
        _PASSWORD,
        _WRONG_PASSWORD,
        "password_hash",
        "$argon2",
        settings.jwt_secret_key.get_secret_value(),
        *extra,
    ):
        assert forbidden not in text


@pytest.mark.integration
def test_login_returns_decodable_bearer_token(active_user, caplog):
    user_id, email, password_hash = active_user
    caplog.set_level(logging.DEBUG)

    response = _CLIENT.post(_URL, json={"email": email, "password": _PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"
    assert response.headers.get("cache-control") == "no-store"
    token = body["access_token"]
    assert decode_access_token(token).user_id == user_id

    payload = jwt.decode(token, options={"verify_signature": False})
    assert email not in str(payload)
    assert "email" not in payload
    assert "password" not in str(payload)

    _assert_no_leaks(response.text.replace(token, ""), password_hash)
    _assert_no_leaks(caplog.text, password_hash, token)


@pytest.mark.integration
def test_login_accepts_email_with_different_case(active_user):
    user_id, email, _ = active_user

    response = _CLIENT.post(_URL, json={"email": email.upper(), "password": _PASSWORD})

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"]).user_id == user_id


@pytest.mark.integration
def test_login_failures_share_identical_401(active_user, caplog):
    _, email, _ = active_user
    inactive_email = _email()
    asyncio.run(_create_user(inactive_email, is_active=False))
    caplog.set_level(logging.DEBUG)
    try:
        responses = [
            _CLIENT.post(_URL, json={"email": email, "password": _WRONG_PASSWORD}),
            _CLIENT.post(_URL, json={"email": _email(), "password": _WRONG_PASSWORD}),
            _CLIENT.post(_URL, json={"email": inactive_email, "password": _PASSWORD}),
        ]
    finally:
        asyncio.run(_delete_user(inactive_email))

    for response in responses:
        assert response.status_code == 401
        assert response.json() == {"detail": "Credenciais inválidas."}
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers.get("cache-control") == "no-store"
        assert response.text == responses[0].text
        assert "access_token" not in response.text
        _assert_no_leaks(response.text)
    _assert_no_leaks(caplog.text)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "a@example.com"},
        {"password": _WRONG_PASSWORD},
        {"email": "nao-e-email", "password": _WRONG_PASSWORD},
        {"email": "a@example.com", "password": _WRONG_PASSWORD, "is_active": True},
        {"email": "a@example.com", "password": ""},
        {"email": "a@example.com", "password": _WRONG_PASSWORD * 20},
    ],
)
def test_login_invalid_body_returns_422_without_password(body, caplog):
    caplog.set_level(logging.DEBUG)

    response = _CLIENT.post(_URL, json=body)

    assert response.status_code == 422
    assert _WRONG_PASSWORD not in response.text
    assert _WRONG_PASSWORD not in caplog.text
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "type", "msg"}


def test_login_malformed_json_returns_422_without_password(caplog):
    caplog.set_level(logging.DEBUG)

    response = _CLIENT.post(
        _URL,
        content=f'{{"password": "{_WRONG_PASSWORD}", ',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert _WRONG_PASSWORD not in response.text
    assert _WRONG_PASSWORD not in caplog.text


def test_login_verification_failure_returns_controlled_500(monkeypatch, caplog):
    async def fail(self: AuthService, credentials: LoginRequest):
        raise CredentialVerificationError

    monkeypatch.setattr(AuthService, "authenticate", fail)
    caplog.set_level(logging.DEBUG)
    email = _email()

    response = _SAFE_CLIENT.post(_URL, json={"email": email, "password": _PASSWORD})

    assert response.status_code == 500
    assert response.status_code != 401
    assert "WWW-Authenticate" not in response.headers
    assert response.json() == {"detail": "Erro interno do servidor."}
    _assert_no_leaks(response.text, email)
    _assert_no_leaks(caplog.text, email)


def test_login_database_error_returns_controlled_500(monkeypatch, caplog):
    leaked = "postgresql://usuario:segredo-do-banco@127.0.0.1:5433/db"

    async def fail(self: AuthService, credentials: LoginRequest):
        raise OperationalError("SELECT secreto", {"p": leaked}, Exception(leaked))

    monkeypatch.setattr(AuthService, "authenticate", fail)
    caplog.set_level(logging.DEBUG)
    email = _email()

    response = _SAFE_CLIENT.post(_URL, json={"email": email, "password": _PASSWORD})

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    for forbidden in (leaked, "segredo-do-banco", "SELECT", "OperationalError"):
        assert forbidden not in response.text
    _assert_no_leaks(response.text, email)
    _assert_no_leaks(caplog.text, email, leaked)
