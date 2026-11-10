"""Logs internos não repetem PII, hash nem JWT."""

import logging

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.logging import redact_text
from app.main import app
from app.schemas.user import LoginRequest
from app.services.auth import AuthService

_CLIENT = TestClient(app, raise_server_exceptions=True)


def test_redact_text_strips_hash_email_jwt_and_sql_parameters():
    token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxIn0.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    raw = (
        "Erro [parameters: {'email': 'ana@example.com', "
        "'password_hash': '$argon2id$v=19$m=65536,t=3,p=4$abc'}] "
        f"Bearer {token} postgres://user:segredo@127.0.0.1/db"
    )
    redacted = redact_text(raw)
    assert "ana@example.com" not in redacted
    assert "$argon2" not in redacted
    assert "eyJ" not in redacted
    assert "segredo" not in redacted
    assert "[redacted]" in redacted


def test_unhandled_error_does_not_escape_and_does_not_leak(monkeypatch, caplog):
    leaked = "postgresql://usuario:segredo-do-banco@127.0.0.1:5433/db"
    email = "leak-case@example.com"

    async def fail(self: AuthService, credentials: LoginRequest):
        raise OperationalError("SELECT secreto", {"email": email}, Exception(leaked))

    monkeypatch.setattr(AuthService, "authenticate", fail)
    caplog.set_level(logging.ERROR)

    response = _CLIENT.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "senha-ficticia-ok"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert "X-Request-ID" in response.headers
    assert email not in response.text
    assert "$argon2" not in caplog.text
    assert email not in caplog.text
    assert leaked not in caplog.text
    assert "segredo-do-banco" not in caplog.text
    assert "OperationalError" in caplog.text
    assert response.headers["X-Request-ID"] in caplog.text
