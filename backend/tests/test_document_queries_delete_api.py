"""GET/DELETE de documentos (etapas 3.5 e 3.6).

Cada teste roda numa transação externa revertida (nexus_ai_test) e com
storage em tmp_path. Há sempre dois usuários e dois workspaces.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.api.dependencies.documents import get_document_storage
from app.core.tokens import create_access_token
from app.db.session import engine
from app.main import app
from app.models.document import Document
from app.models.user import User
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.storage.local import LocalDocumentStorage

_PUBLIC_FIELDS = {
    "id",
    "workspace_id",
    "filename",
    "mime_type",
    "size_bytes",
    "status",
    "uploaded_by",
    "created_at",
    "metadata",
}
_SECRET_NAME = "segredo-do-workspace-b.txt"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db_session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield db_session
        finally:
            await db_session.close()
            await transaction.rollback()


@pytest.fixture
def storage_root(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def storage(storage_root):
    return LocalDocumentStorage(storage_root)


@pytest_asyncio.fixture
async def client(session, storage) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: storage
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_document_storage, None)


async def _user(session: AsyncSession) -> User:
    return await UserRepository(session).create_user(
        name="Usuário Teste",
        email=f"q-{uuid4().hex}@example.com",
        password_hash="hash-ficticio",
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _workspace(session, owner, roles=None):
    workspace = await WorkspaceRepository(session).create(
        name="Workspace", slug=f"ws-{uuid4().hex[:12]}", owner_id=owner.id
    )
    members = WorkspaceMemberRepository(session)
    await members.create(workspace_id=workspace.id, user_id=owner.id, role="owner")
    for user, role in (roles or {}).items():
        await members.create(workspace_id=workspace.id, user_id=user.id, role=role)
    return workspace


async def _document(
    session, storage, workspace, user, name="a.txt", created_at=None, data=b"conteudo"
) -> Document:
    """Cria linha + blob real no storage (via API do storage)."""

    async def chunks():
        yield data

    stored = await storage.save(chunks(), max_bytes=1024)
    document = Document(
        workspace_id=workspace.id,
        uploaded_by=user.id,
        filename=name,
        mime_type="text/plain",
        size_bytes=stored.size,
        storage_key=stored.key,
        status="uploaded",
        metadata_={},
    )
    if created_at is not None:
        document.created_at = created_at
    session.add(document)
    await session.flush()
    return document


def _url(workspace_id, document_id=None):
    base = f"/api/v1/workspaces/{workspace_id}/documents"
    return base if document_id is None else f"{base}/{document_id}"


def _blob_exists(storage, document) -> bool:
    try:
        storage.open(document.storage_key).close()
    except FileNotFoundError:
        return False
    return True


async def _row_exists(session, document_id) -> bool:
    return (
        await session.scalar(
            select(func.count()).select_from(Document).where(Document.id == document_id)
        )
    ) == 1


# --- listagem ---------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_empty(client, session):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await client.get(_url(workspace.id), headers=_auth(owner))

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_pagination_is_deterministic_with_id_tiebreak(
    client, session, storage
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    same = datetime(2030, 1, 1, tzinfo=UTC)
    older = same - timedelta(days=1)
    docs = [
        await _document(session, storage, workspace, owner, "old.txt", older),
        await _document(session, storage, workspace, owner, "t1.txt", same),
        await _document(session, storage, workspace, owner, "t2.txt", same),
        await _document(session, storage, workspace, owner, "t3.txt", same),
    ]
    expected = [docs[3].id, docs[2].id, docs[1].id, docs[0].id]

    first = await client.get(
        _url(workspace.id) + "?limit=3&offset=0", headers=_auth(owner)
    )
    second = await client.get(
        _url(workspace.id) + "?limit=3&offset=3", headers=_auth(owner)
    )
    again = await client.get(
        _url(workspace.id) + "?limit=3&offset=0", headers=_auth(owner)
    )

    assert [i["id"] for i in first.json()["items"]] == expected[:3]
    assert [i["id"] for i in second.json()["items"]] == expected[3:]
    assert first.json() == again.json()
    assert first.json()["total"] == second.json()["total"] == 4
    assert first.json()["limit"] == 3
    assert second.json()["offset"] == 3
    for item in first.json()["items"]:
        assert set(item) == _PUBLIC_FIELDS


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["limit=101", "limit=0", "limit=-1", "offset=-1", "offset=99999999999", "limit=x"],
)
async def test_list_invalid_pagination_gets_422(client, session, query):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await client.get(_url(workspace.id) + "?" + query, headers=_auth(owner))

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_total_and_items_ignore_other_workspaces(client, session, storage):
    user_a = await _user(session)
    user_b = await _user(session)
    ws_a = await _workspace(session, user_a)
    ws_b = await _workspace(session, user_b)
    mine = await _document(session, storage, ws_a, user_a, "meu.txt")
    await _document(session, storage, ws_b, user_b, _SECRET_NAME)
    await _document(session, storage, ws_b, user_b, "outro.txt")

    response = await client.get(_url(ws_a.id), headers=_auth(user_a))

    body = response.json()
    assert body["total"] == 1
    assert [i["id"] for i in body["items"]] == [mine.id]
    assert _SECRET_NAME not in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_other_workspace_without_membership_gets_404(
    client, session, storage
):
    user_a = await _user(session)
    user_b = await _user(session)
    await _workspace(session, user_a)
    ws_b = await _workspace(session, user_b)
    await _document(session, storage, ws_b, user_b, _SECRET_NAME)

    response = await client.get(_url(ws_b.id), headers=_auth(user_a))

    assert response.status_code == 404
    assert _SECRET_NAME not in response.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
async def test_every_role_can_list_and_get(client, session, storage, role):
    owner = await _user(session)
    other = await _user(session)
    workspace = await _workspace(session, owner, {other: role})
    document = await _document(session, storage, workspace, owner)
    user = owner if role == "owner" else other

    listing = await client.get(_url(workspace.id), headers=_auth(user))
    detail = await client.get(_url(workspace.id, document.id), headers=_auth(user))

    assert listing.status_code == detail.status_code == 200
    assert listing.json()["total"] == 1
    assert detail.json()["id"] == document.id


# --- detalhe ----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_returns_only_public_fields(client, session, storage, storage_root):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner, "x.txt")

    response = await client.get(_url(workspace.id, document.id), headers=_auth(owner))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == _PUBLIC_FIELDS
    assert body["filename"] == "x.txt"
    assert body["uploaded_by"] == owner.id
    assert document.storage_key not in response.text
    assert str(storage_root) not in response.text
    assert "storage" not in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_workspace_get_is_404_without_leaking_metadata(
    client, session, storage
):
    """O teste mais importante: A não obtém documento exclusivo de B."""
    user_a = await _user(session)
    user_b = await _user(session)
    ws_a = await _workspace(session, user_a)
    ws_b = await _workspace(session, user_b)
    doc_b = await _document(
        session, storage, ws_b, user_b, _SECRET_NAME, data=b"conteudo-confidencial"
    )
    missing = await client.get(_url(ws_a.id, 2147483000), headers=_auth(user_a))

    via_own = await client.get(_url(ws_a.id, doc_b.id), headers=_auth(user_a))
    via_foreign = await client.get(_url(ws_b.id, doc_b.id), headers=_auth(user_a))

    assert via_own.status_code == 404
    assert via_own.json() == missing.json()  # mesmo corpo genérico
    assert via_foreign.status_code == 404
    for response in (via_own, via_foreign):
        text = response.text
        assert _SECRET_NAME not in text
        assert doc_b.storage_key not in text
        assert str(doc_b.size_bytes) not in text.replace(str(doc_b.id), "")
        assert "text/plain" not in text
        assert str(ws_b.id) not in text or str(ws_b.id) == str(ws_a.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_nonexistent_and_invalid_ids(client, session):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    missing = await client.get(_url(workspace.id, 2147483000), headers=_auth(owner))
    zero = await client.get(_url(workspace.id, 0), headers=_auth(owner))
    huge = await client.get(_url(workspace.id, 99999999999), headers=_auth(owner))
    junk = await client.get(_url(workspace.id, "abc"), headers=_auth(owner))

    assert missing.status_code == 404
    assert zero.status_code == huge.status_code == junk.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_and_list_require_authentication(client, session, storage):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner)

    assert (await client.get(_url(workspace.id))).status_code == 401
    assert (await client.get(_url(workspace.id, document.id))).status_code == 401
    assert (await client.delete(_url(workspace.id, document.id))).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_db_failure_returns_controlled_500(
    client, session, storage, monkeypatch
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("falha SQL com /caminho/secreto")

    monkeypatch.setattr(
        "app.repositories.document.DocumentRepository.get_in_workspace", boom
    )
    monkeypatch.setattr(
        "app.repositories.document.DocumentRepository.list_by_workspace", boom
    )
    detail = await client.get(_url(workspace.id, document.id), headers=_auth(owner))
    listing = await client.get(_url(workspace.id), headers=_auth(owner))

    for response in (detail, listing):
        assert response.status_code == 500
        assert response.json() == {"detail": "Erro interno do servidor."}
        assert "secreto" not in response.text


# --- exclusão ---------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_owner_and_admin_delete_row_and_blob(client, session, storage, role):
    owner = await _user(session)
    other = await _user(session)
    workspace = await _workspace(session, owner, {other: "admin"})
    document = await _document(session, storage, workspace, owner)
    user = owner if role == "owner" else other

    response = await client.delete(_url(workspace.id, document.id), headers=_auth(user))

    assert response.status_code == 204
    assert response.content == b""
    assert not await _row_exists(session, document.id)
    assert not _blob_exists(storage, document)
    again = await client.delete(_url(workspace.id, document.id), headers=_auth(user))
    assert again.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_member_and_viewer_cannot_delete(client, session, storage, role):
    owner = await _user(session)
    other = await _user(session)
    workspace = await _workspace(session, owner, {other: role})
    document = await _document(session, storage, workspace, owner)

    response = await client.delete(
        _url(workspace.id, document.id), headers=_auth(other)
    )

    assert response.status_code == 403
    assert await _row_exists(session, document.id)
    assert _blob_exists(storage, document)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_member_delete_is_404_and_intact(client, session, storage):
    user_a = await _user(session)
    user_b = await _user(session)
    ws_b = await _workspace(session, user_b)
    doc_b = await _document(session, storage, ws_b, user_b, _SECRET_NAME)

    response = await client.delete(_url(ws_b.id, doc_b.id), headers=_auth(user_a))

    assert response.status_code == 404
    assert _SECRET_NAME not in response.text
    assert await _row_exists(session, doc_b.id)
    assert _blob_exists(storage, doc_b)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_workspace_delete_via_own_workspace_is_404_and_intact(
    client, session, storage
):
    user_a = await _user(session)
    user_b = await _user(session)
    ws_a = await _workspace(session, user_a)
    ws_b = await _workspace(session, user_b)
    doc_b = await _document(session, storage, ws_b, user_b, _SECRET_NAME)
    missing = await client.delete(_url(ws_a.id, 2147483000), headers=_auth(user_a))

    response = await client.delete(_url(ws_a.id, doc_b.id), headers=_auth(user_a))

    assert response.status_code == 404
    assert response.json() == missing.json()
    assert _SECRET_NAME not in response.text
    assert await _row_exists(session, doc_b.id)
    assert _blob_exists(storage, doc_b)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_with_blob_already_missing_is_204_and_warns(
    client, session, storage, caplog
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner)
    key = document.storage_key
    assert storage.delete(key) is True

    with caplog.at_level(logging.WARNING):
        response = await client.delete(
            _url(workspace.id, document.id), headers=_auth(owner)
        )

    assert response.status_code == 204
    assert not await _row_exists(session, document.id)
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert key not in caplog.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_blob_removal_failure_after_commit_is_204_and_logged_safely(
    client, session, storage, storage_root, monkeypatch, caplog
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner, "sigiloso.txt")
    key = document.storage_key

    def boom(self, key):
        raise PermissionError(f"negado em {storage_root}/{key}")

    monkeypatch.setattr(LocalDocumentStorage, "delete", boom)
    with caplog.at_level(logging.ERROR):
        response = await client.delete(
            _url(workspace.id, document.id), headers=_auth(owner)
        )

    assert response.status_code == 204
    assert not await _row_exists(session, document.id)
    assert _blob_exists(storage, document)  # órfão, para reconciliação
    assert "stage=blob_cleanup" in caplog.text
    assert "PermissionError" in caplog.text
    assert "request_id=" in caplog.text
    assert key not in caplog.text
    assert str(storage_root) not in caplog.text
    assert "sigiloso" not in caplog.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_commit_failure_returns_500_and_keeps_row_and_blob(
    client, session, storage, monkeypatch, caplog
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    document = await _document(session, storage, workspace, owner)
    # Confirma a preparação: o rollback do serviço não pode desfazê-la.
    await session.commit()
    document_id = document.id
    key = document.storage_key
    real_commit = session.commit

    async def failing_commit():
        raise RuntimeError("commit falhou em /caminho/secreto")

    monkeypatch.setattr(session, "commit", failing_commit)
    with caplog.at_level(logging.ERROR):
        response = await client.delete(
            _url(workspace.id, document_id), headers=_auth(owner)
        )
    monkeypatch.setattr(session, "commit", real_commit)

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert "secreto" not in response.text
    assert "stage=database" in caplog.text
    assert await _row_exists(session, document_id)
    assert storage.open(key).close() is None
