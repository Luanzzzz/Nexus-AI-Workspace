"""Cota por workspace (F04): pré-checagem barata e checagem autoritativa."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.api.dependencies.documents import get_document_storage
from app.core.config import settings
from app.core.security import hash_password
from app.core.tokens import create_access_token
from app.db.session import SessionLocal
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

_QUOTA = {"detail": "Cota de armazenamento do workspace excedida."}


@dataclass
class Data:
    user_id: int
    workspace_id: int


@pytest_asyncio.fixture
async def data() -> AsyncIterator[Data]:
    async with SessionLocal() as s:
        user = await UserRepository(s).create_user(
            name="Ana Silva",
            email=f"quota-{uuid4().hex}@example.com",
            password_hash=hash_password("senha-ficticia-ok"),
        )
        ws = await WorkspaceRepository(s).create(
            name="WS", slug=f"quota-{uuid4().hex[:12]}", owner_id=user.id
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


class BarrierStorage(LocalDocumentStorage):
    """Conta chamadas a save e, com `expected`, espera todos chegarem."""

    def __init__(self, root, expected: int = 0) -> None:
        super().__init__(root)
        self.saves = 0
        self.expected = expected
        self.all_in = asyncio.Event()

    async def save(self, chunks, *, max_bytes):
        self.saves += 1
        if self.expected:
            if self.saves >= self.expected:
                self.all_in.set()
            await asyncio.wait_for(self.all_in.wait(), 10)
        return await super().save(chunks, max_bytes=max_bytes)


@pytest_asyncio.fixture
async def make_client(tmp_path):
    clients: list[httpx.AsyncClient] = []

    def factory(expected: int = 0):
        storage = BarrierStorage(tmp_path / "storage", expected)
        app.dependency_overrides[get_document_storage] = lambda: storage
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        clients.append(client)
        return client, storage

    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_document_storage, None)
        for client in clients:
            await client.aclose()


def _upload(client, d: Data, name: str, content: bytes):
    return client.post(
        f"/api/v1/workspaces/{d.workspace_id}/documents",
        files={"file": (name, content, "text/plain")},
        headers={"Authorization": f"Bearer {create_access_token(d.user_id)}"},
    )


def _blobs(storage: BarrierStorage):
    root = storage._root
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def _usage(d: Data) -> tuple[int, int]:
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(
                    func.count(), func.coalesce(func.sum(Document.size_bytes), 0)
                ).where(Document.workspace_id == d.workspace_id)
            )
        ).one()
        return int(row[0]), int(row[1])


async def test_document_count_limit_precheck_writes_no_blob(
    make_client, data, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_max_documents", 1)
    client, storage = make_client()

    assert (await _upload(client, data, "a.txt", b"um")).status_code == 201
    saves_before = storage.saves
    response = await _upload(client, data, "b.txt", b"dois")

    assert response.status_code == 413
    assert response.json() == _QUOTA
    assert storage.saves == saves_before  # pré-checagem: nem tentou gravar
    assert await _usage(data) == (1, 2)
    assert len(_blobs(storage)) == 1


async def test_byte_limit_precheck_writes_no_blob(make_client, data, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_storage_bytes", 6)
    client, storage = make_client()

    assert (await _upload(client, data, "a.txt", b"123456")).status_code == 201
    saves_before = storage.saves
    response = await _upload(client, data, "b.txt", b"x")

    assert response.status_code == 413
    assert response.json() == _QUOTA
    assert storage.saves == saves_before
    assert await _usage(data) == (1, 6)
    assert len(_blobs(storage)) == 1


async def test_byte_limit_authoritative_check_removes_blob(
    make_client, data, monkeypatch
):
    """Passa na pré-checagem (0 < 5), mas o arquivo de 6 bytes não cabe."""
    monkeypatch.setattr(settings, "workspace_max_storage_bytes", 5)
    client, storage = make_client()

    response = await _upload(client, data, "a.txt", b"123456")

    assert response.status_code == 413
    assert response.json() == _QUOTA
    assert storage.saves == 1  # chegou a gravar: a decisão foi a autoritativa
    assert await _usage(data) == (0, 0)
    assert _blobs(storage) == []


async def test_exactly_at_limit_is_accepted(make_client, data, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_storage_bytes", 6)
    monkeypatch.setattr(settings, "workspace_max_documents", 1)
    client, _ = make_client()

    assert (await _upload(client, data, "a.txt", b"123456")).status_code == 201


async def test_race_on_document_count_only_one_fits(make_client, data, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_documents", 1)
    client, storage = make_client(expected=2)

    first, second = await asyncio.gather(
        _upload(client, data, "a.txt", b"um"),
        _upload(client, data, "b.txt", b"dois"),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 413]
    assert storage.saves == 2  # ambos passaram na pré-checagem
    count, _ = await _usage(data)
    assert count == 1
    assert len(_blobs(storage)) == 1


async def test_race_on_bytes_only_one_fits(make_client, data, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_storage_bytes", 10)
    client, storage = make_client(expected=2)

    first, second = await asyncio.gather(
        _upload(client, data, "a.txt", b"123456"),
        _upload(client, data, "b.txt", b"abcdef"),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 413]
    assert storage.saves == 2
    count, used = await _usage(data)
    assert (count, used) == (1, 6)
    assert used <= 10
    assert len(_blobs(storage)) == 1


async def test_quota_is_per_workspace(make_client, data, monkeypatch):
    monkeypatch.setattr(settings, "workspace_max_documents", 1)
    client, _ = make_client()
    assert (await _upload(client, data, "a.txt", b"um")).status_code == 201

    async with SessionLocal() as s:
        other = await WorkspaceRepository(s).create(
            name="WS2", slug=f"quota2-{uuid4().hex[:12]}", owner_id=data.user_id
        )
        await WorkspaceMemberRepository(s).create(
            workspace_id=other.id, user_id=data.user_id, role="owner"
        )
        await s.commit()
        other_id = other.id
    try:
        response = await _upload(client, Data(data.user_id, other_id), "c.txt", b"x")
        assert response.status_code == 201
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Document).where(Document.workspace_id == other_id))
            await s.execute(
                delete(WorkspaceMember).where(WorkspaceMember.workspace_id == other_id)
            )
            await s.execute(delete(Workspace).where(Workspace.id == other_id))
            await s.commit()


async def test_deleting_a_document_frees_workspace_quota(
    make_client, data, monkeypatch
):
    monkeypatch.setattr(settings, "workspace_max_documents", 1)
    monkeypatch.setattr(settings, "workspace_max_storage_bytes", 6)
    client, _ = make_client()
    first = await _upload(client, data, "a.txt", b"123456")
    assert first.status_code == 201
    assert (await _upload(client, data, "b.txt", b"1")).status_code == 413

    deleted = await client.delete(
        f"/api/v1/workspaces/{data.workspace_id}/documents/{first.json()['id']}",
        headers={"Authorization": f"Bearer {create_access_token(data.user_id)}"},
    )
    assert deleted.status_code == 204
    assert await _usage(data) == (0, 0)

    assert (await _upload(client, data, "c.txt", b"123456")).status_code == 201


async def test_workspace_lock_timeout_is_logged_with_its_own_stage(
    make_client, data, monkeypatch, caplog
):
    import app.services.document as document_service

    monkeypatch.setattr(document_service, "MEMBERSHIP_LOCK_TIMEOUT_MS", 200)
    client, _ = make_client()
    async with SessionLocal() as other:
        await other.execute(
            select(Workspace.id)
            .where(Workspace.id == data.workspace_id)
            .with_for_update()
        )
        with caplog.at_level("ERROR", logger="app.services.document"):
            response = await asyncio.wait_for(
                _upload(client, data, "a.txt", b"conteudo"), 10
            )
        await other.rollback()

    assert response.status_code == 500
    assert "stage=workspace_lock" in caplog.text
    assert "stage=database" not in caplog.text
    assert await _usage(data) == (0, 0)


async def test_quota_lock_does_not_conflict_with_fk_key_share(data):
    """FOR NO KEY UPDATE convive com o KEY SHARE que os INSERTs de FK tomam."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with SessionLocal() as inserter, SessionLocal() as locker:
        await inserter.execute(
            select(Workspace.id)
            .where(Workspace.id == data.workspace_id)
            .with_for_update(key_share=True, read=True)  # FOR KEY SHARE
        )
        await locker.execute(text("SET LOCAL lock_timeout = '300ms'"))
        assert await WorkspaceRepository(locker).lock_for_update(data.workspace_id)

        # Ainda se serializa consigo mesmo.
        async with SessionLocal() as second:
            await second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(DBAPIError):
                await WorkspaceRepository(second).lock_for_update(data.workspace_id)
            await second.rollback()
        await locker.rollback()
        await inserter.rollback()
