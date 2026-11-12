"""Limites de criação de workspace (F04): teto por dono e rate limit."""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.security import hash_password
from app.core.tokens import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_URL = "/api/v1/workspaces"
_LIMIT = {"detail": "Limite de workspaces atingido."}
_RATE = {"detail": "Muitas tentativas. Tente novamente mais tarde."}


@pytest_asyncio.fixture
async def users() -> AsyncIterator[list[int]]:
    ids: list[int] = []
    async with SessionLocal() as s:
        for _ in range(2):
            user = await UserRepository(s).create_user(
                name="Ana Silva",
                email=f"wslimit-{uuid4().hex}@example.com",
                password_hash=hash_password("senha-ficticia-ok"),
            )
            ids.append(user.id)
        await s.commit()
    try:
        yield ids
    finally:
        async with SessionLocal() as s:
            owned = select(Workspace.id).where(Workspace.owner_id.in_(ids))
            await s.execute(
                delete(WorkspaceMember).where(WorkspaceMember.workspace_id.in_(owned))
            )
            await s.execute(delete(Workspace).where(Workspace.owner_id.in_(ids)))
            await s.execute(delete(User).where(User.id.in_(ids)))
            await s.commit()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


def _create(client, user_id: int):
    return client.post(
        _URL,
        json={"name": "WS", "slug": f"lim-{uuid4().hex[:16]}"},
        headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
    )


async def _owned(user_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.owner_id == user_id)
        )


async def test_owned_workspace_limit_returns_403_generic(client, users, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_owned_per_user", 2)
    a, b = users

    assert (await _create(client, a)).status_code == 201
    assert (await _create(client, a)).status_code == 201
    blocked = await _create(client, a)

    assert blocked.status_code == 403
    assert blocked.json() == _LIMIT
    assert await _owned(a) == 2
    # O teto é por usuário.
    assert (await _create(client, b)).status_code == 201


async def test_concurrent_creations_cannot_exceed_owned_limit(
    client, users, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_max_owned_per_user", 1)
    original = WorkspaceRepository.count_owned_by

    async def slow_count(self, user_id):
        total = await original(self, user_id)
        # Janela de corrida: sem o lock da linha do usuário as duas leriam 0.
        await asyncio.sleep(0.3)
        return total

    monkeypatch.setattr(WorkspaceRepository, "count_owned_by", slow_count)
    a, _ = users

    first, second = await asyncio.gather(_create(client, a), _create(client, a))

    assert sorted([first.status_code, second.status_code]) == [201, 403]
    assert await _owned(a) == 1


async def test_workspace_create_rate_limit_returns_429(client, users, monkeypatch):
    monkeypatch.setattr(settings, "workspace_create_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "workspace_create_rate_limit_per_hour", 2)
    a, b = users

    assert (await _create(client, a)).status_code == 201
    assert (await _create(client, a)).status_code == 201
    blocked = await _create(client, a)

    assert blocked.status_code == 429
    assert blocked.json() == _RATE
    assert int(blocked.headers["Retry-After"]) >= 1
    assert await _owned(a) == 2  # nenhum workspace extra foi criado
    assert (await _create(client, b)).status_code == 201


async def test_rate_limit_runs_after_authentication(client, monkeypatch):
    monkeypatch.setattr(settings, "workspace_create_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "workspace_create_rate_limit_per_hour", 1)
    for _ in range(3):
        response = await client.post(_URL, json={"name": "WS", "slug": "abc"})
        assert response.status_code == 401


async def test_rate_limit_respects_disable_switch(client, users, monkeypatch):
    monkeypatch.setattr(settings, "workspace_create_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "workspace_create_rate_limit_per_hour", 1)
    a, _ = users
    for _ in range(3):
        assert (await _create(client, a)).status_code == 201
