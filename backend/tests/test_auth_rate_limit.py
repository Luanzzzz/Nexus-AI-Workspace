"""Rate limit de login/cadastro e proxy confiável."""

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.request_context import client_ip
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

_CLIENT = TestClient(app)
_PASSWORD = "senha-ficticia-ok"


@pytest.fixture
def enable_limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_login_per_ip_limit", 3)
    monkeypatch.setattr(settings, "auth_login_per_email_limit", 2)
    monkeypatch.setattr(settings, "auth_register_per_ip_limit", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 60)
    limiter.reset()
    yield
    limiter.reset()


def _login_payload(email: str) -> dict[str, str]:
    return {"email": email, "password": "senha-errada-ficticia"}


def test_login_rate_limit_per_email_returns_429(enable_limits):
    email = f"limit-{uuid4().hex}@example.com"
    first = _CLIENT.post("/api/v1/auth/login", json=_login_payload(email))
    second = _CLIENT.post("/api/v1/auth/login", json=_login_payload(email))
    blocked = _CLIENT.post("/api/v1/auth/login", json=_login_payload(email))

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert blocked.json() == {
        "detail": "Muitas tentativas. Tente novamente mais tarde."
    }
    assert "Retry-After" in blocked.headers
    int(blocked.headers["Retry-After"])


async def _delete_emails(emails: list[str]) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email.in_(emails)))
        await session.commit()


def test_register_rate_limit_per_ip_returns_429(enable_limits):
    emails = [f"reg-{uuid4().hex}@example.com" for _ in range(3)]

    def payload(email: str) -> dict[str, str]:
        return {"name": "Ana Silva", "email": email, "password": _PASSWORD}

    try:
        first = _CLIENT.post("/api/v1/auth/register", json=payload(emails[0]))
        second = _CLIENT.post("/api/v1/auth/register", json=payload(emails[1]))
        blocked = _CLIENT.post("/api/v1/auth/register", json=payload(emails[2]))

        assert first.status_code == 201
        assert second.status_code == 201
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
    finally:
        asyncio.run(_delete_emails(emails))


def test_forged_xff_from_untrusted_peer_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"6.6.6.6")],
        "client": ("203.0.113.10", 1234),
        "server": ("127.0.0.1", 80),
    }
    request = Request(scope)
    assert client_ip(request) == "203.0.113.10"


def test_xff_used_only_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"198.51.100.20")],
        "client": ("10.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
    }
    request = Request(scope)
    assert client_ip(request) == "198.51.100.20"
