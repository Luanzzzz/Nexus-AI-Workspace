"""O upload não segura conexão do pool durante o I/O de storage (F03).

Usa um engine dedicado com pool_size=1 e dados realmente confirmados (a sessão
do app precisa de conexão própria), limpos no fim.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies.database import get_db
from app.api.dependencies.documents import get_document_storage
from app.core.security import hash_password
from app.core.tokens import create_access_token
from app.db.session import SessionLocal, database_url
from app.main import app
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.storage.local import LocalDocumentStorage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class Data:
    user_id: int
    workspace_id: int


@pytest_asyncio.fixture
async def data() -> AsyncIterator[Data]:
    async with SessionLocal() as s:
        user = await UserRepository(s).create_user(
            name="Ana Silva",
            email=f"rel-{uuid4().hex}@example.com",
            password_hash=hash_password("senha-ficticia-ok"),
        )
        ws = await WorkspaceRepository(s).create(
            name="WS", slug=f"rel-{uuid4().hex[:12]}", owner_id=user.id
        )
        await WorkspaceMemberRepository(s).create(
            workspace_id=ws.id, user_id=user.id, role="owner"
        )
        await s.commit()
        d = Data(user.id, ws.id)
    try:
        yield d
    finally:
        async with SessionLocal() as s:
            await s.execute(
                delete(Document).where(Document.workspace_id == d.workspace_id)
            )
            await s.execute(
                delete(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == d.workspace_id
                )
            )
            await s.execute(delete(Workspace).where(Workspace.id == d.workspace_id))
            await s.execute(delete(User).where(User.id == d.user_id))
            await s.commit()


class BlockingStorage(LocalDocumentStorage):
    """Para dentro do I/O de storage até o teste liberar."""

    def __init__(self, root, pool) -> None:
        super().__init__(root)
        self.pool = pool
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.checked_out_during_io: int | None = None

    async def save(self, chunks, *, max_bytes):
        self.checked_out_during_io = self.pool.checkedout()
        self.reached.set()
        await self.release.wait()
        return await super().save(chunks, max_bytes=max_bytes)


@pytest_asyncio.fixture
async def harness(tmp_path):
    engine = create_async_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    storage = BlockingStorage(tmp_path / "storage", engine.pool)

    async def tight_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = tight_db
    app.dependency_overrides[get_document_storage] = lambda: storage
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client, storage, engine
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_document_storage, None)
        await engine.dispose()


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _upload(client, data: Data):
    return asyncio.create_task(
        client.post(
            f"/api/v1/workspaces/{data.workspace_id}/documents",
            files={"file": ("a.txt", b"conteudo", "text/plain")},
            headers=_headers(data.user_id),
        )
    )


def _blobs(root):
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def _doc_count(workspace_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.workspace_id == workspace_id)
        )


async def test_connection_released_during_storage_io(harness, data):
    client, storage, engine = harness
    task = _upload(client, data)
    await asyncio.wait_for(storage.reached.wait(), 5)

    assert storage.checked_out_during_io == 0
    assert engine.pool.checkedout() == 0
    # Com pool_size=1, outra requisição que precisa do banco não fica presa.
    me = await asyncio.wait_for(
        client.get("/api/v1/auth/me", headers=_headers(data.user_id)), 3
    )
    assert me.status_code == 200

    storage.release.set()
    response = await asyncio.wait_for(task, 10)
    assert response.status_code == 201
    assert await _doc_count(data.workspace_id) == 1
    assert len(_blobs(storage._root)) == 1


async def test_membership_removed_during_upload_returns_404(harness, data):
    client, storage, _ = harness
    task = _upload(client, data)
    await asyncio.wait_for(storage.reached.wait(), 5)
    async with SessionLocal() as s:
        await s.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == data.workspace_id
            )
        )
        await s.commit()
    storage.release.set()
    response = await asyncio.wait_for(task, 10)

    assert response.status_code == 404
    assert await _doc_count(data.workspace_id) == 0
    assert _blobs(storage._root) == []


async def test_role_downgraded_during_upload_returns_403(harness, data):
    client, storage, _ = harness
    task = _upload(client, data)
    await asyncio.wait_for(storage.reached.wait(), 5)
    async with SessionLocal() as s:
        member = await WorkspaceMemberRepository(s).get_membership(
            data.workspace_id, data.user_id
        )
        member.role = "viewer"
        await s.commit()
    storage.release.set()
    response = await asyncio.wait_for(task, 10)

    assert response.status_code == 403
    assert await _doc_count(data.workspace_id) == 0
    assert _blobs(storage._root) == []
