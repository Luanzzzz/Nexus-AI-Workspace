"""Rate limit com uvicorn real: XFF forjado no loopback não burla o IP."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User

_PASSWORD = "senha-ficticia-ok"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(base: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base}/api/v1/health", timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise AssertionError("uvicorn não ficou saudável")


async def _delete_emails(emails: list[str]) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email.in_(emails)))
        await session.commit()


@pytest.mark.integration
def test_uvicorn_empty_trusted_proxies_ignores_forged_xff():
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "AUTH_RATE_LIMIT_ENABLED": "true",
            "AUTH_REGISTER_PER_IP_LIMIT": "2",
            "TRUSTED_PROXIES": "",
            "FORWARDED_ALLOW_IPS": "",
            "JWT_SECRET_KEY": settings.jwt_secret_key.get_secret_value(),
            "POSTGRES_USER": settings.postgres_user or "",
            "POSTGRES_PASSWORD": settings.postgres_password or "",
            "POSTGRES_DB": settings.postgres_db or "",
            "POSTGRES_HOST": settings.postgres_host,
            "POSTGRES_PORT": str(settings.postgres_port),
            "ENVIRONMENT": "test",
            "DEBUG": "false",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=_BACKEND_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    emails = [f"uvx-{uuid4().hex}@example.com" for _ in range(4)]
    try:
        _wait_healthy(base)
        statuses: list[int] = []
        blocked: httpx.Response | None = None
        for index, email in enumerate(emails):
            response = httpx.post(
                f"{base}/api/v1/auth/register",
                json={"name": "Ana Silva", "email": email, "password": _PASSWORD},
                headers={"X-Forwarded-For": f"6.6.6.{index + 1}"},
                timeout=10,
            )
            statuses.append(response.status_code)
            if response.status_code == 429:
                blocked = response
        assert statuses[:2] == [201, 201]
        assert 429 in statuses
        assert blocked is not None
        assert "Retry-After" in blocked.headers
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        asyncio.run(_delete_emails(emails))
