"""POST /api/v1/workspaces/{id}/documents.

Cada teste roda numa transação externa revertida no fim (nexus_ai_test) e com
storage em tmp_path: nada fica no banco nem no diretório real.
"""

import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.api.dependencies.documents import get_document_storage
from app.api.exception_handlers import DOCUMENT_TOO_LARGE_DETAIL
from app.api.v1.documents import _MULTIPART_OVERHEAD
from app.core.tokens import create_access_token
from app.db.session import engine
from app.main import app
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.document import DocumentRepository
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.services.document import DocumentService
from app.services.document_reconciliation import find_orphan_blobs, reconcile_orphans
from app.services.document_validation import MAX_UPLOAD_BYTES
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
_PDF = b"%PDF-1.7\n%conteudo\n"


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


@pytest_asyncio.fixture
async def client(session, storage_root) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: LocalDocumentStorage(
        storage_root
    )
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
        email=f"doc-{uuid4().hex}@example.com",
        password_hash="hash-ficticio",
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _workspace(session, owner, roles=None) -> Workspace:
    workspace = await WorkspaceRepository(session).create(
        name="Workspace", slug=f"ws-{uuid4().hex[:12]}", owner_id=owner.id
    )
    members = WorkspaceMemberRepository(session)
    await members.create(workspace_id=workspace.id, user_id=owner.id, role="owner")
    for user, role in (roles or {}).items():
        await members.create(workspace_id=workspace.id, user_id=user.id, role=role)
    return workspace


def _url(workspace_id: int) -> str:
    return f"/api/v1/workspaces/{workspace_id}/documents"


def _blobs(root) -> list:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def _count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Document))


async def _upload(client, user, workspace_id, name, data, content_type=None):
    file = (name, data) if content_type is None else (name, data, content_type)
    return await client.post(
        _url(workspace_id), files={"file": file}, headers=_auth(user)
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("a.pdf", _PDF, "application/pdf"),
        ("a.txt", "olá ção".encode(), "text/plain"),
        ("a.md", b"# titulo\n", "text/markdown"),
        ("a.markdown", b"# titulo\n", "text/markdown"),
    ],
)
async def test_owner_and_admin_can_upload(
    client, session, storage_root, role, name, data, mime
):
    owner = await _user(session)
    other = await _user(session)
    workspace = await _workspace(session, owner, {other: "admin"})
    user = owner if role == "owner" else other

    response = await _upload(client, user, workspace.id, name, data)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == _PUBLIC_FIELDS
    assert body["status"] == "uploaded"
    assert body["mime_type"] == mime
    assert body["size_bytes"] == len(data)
    assert body["filename"] == name
    assert body["uploaded_by"] == user.id
    assert body["workspace_id"] == workspace.id
    assert body["metadata"] == {}
    text = response.text
    assert str(storage_root) not in text
    document = await session.get(Document, body["id"])
    assert document.storage_key not in text
    assert len(_blobs(storage_root)) == 1
    with LocalDocumentStorage(storage_root).open(document.storage_key) as handle:
        assert handle.read() == data


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_filename_twice_creates_distinct_blobs(
    client, session, storage_root
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    first = await _upload(client, owner, workspace.id, "a.txt", b"um")
    second = await _upload(client, owner, workspace.id, "a.txt", b"dois")

    assert first.status_code == second.status_code == 201
    assert len(_blobs(storage_root)) == 2
    assert await _count(session) == 2


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_member_and_viewer_get_403_and_nothing_is_stored(
    client, session, storage_root, role
):
    owner = await _user(session)
    other = await _user(session)
    workspace = await _workspace(session, owner, {other: role})

    response = await _upload(client, other, workspace.id, "a.txt", b"x")

    assert response.status_code == 403
    assert _blobs(storage_root) == []
    assert not storage_root.exists()
    assert await _count(session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_member_and_missing_workspace_get_404(client, session, storage_root):
    owner = await _user(session)
    stranger = await _user(session)
    workspace = await _workspace(session, owner)

    foreign = await _upload(client, stranger, workspace.id, "a.txt", b"x")
    missing = await _upload(client, stranger, 2147483000, "a.txt", b"x")

    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert not storage_root.exists()
    assert await _count(session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_jwt_gets_401(client, session, storage_root):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await client.post(
        _url(workspace.id),
        files={"file": ("a.txt", b"x")},
        headers={"Authorization": "Bearer invalido"},
    )

    assert response.status_code == 401
    assert not storage_root.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_over_limit_gets_413_without_persisting(client, session, storage_root):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await _upload(
        client, owner, workspace.id, "a.txt", b"a" * (MAX_UPLOAD_BYTES + 1)
    )

    assert response.status_code == 413
    assert _blobs(storage_root) == []
    assert await _count(session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exactly_limit_is_accepted(client, session, storage_root):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await _upload(
        client, owner, workspace.id, "a.txt", b"a" * MAX_UPLOAD_BYTES
    )

    assert response.status_code == 201
    assert response.json()["size_bytes"] == MAX_UPLOAD_BYTES


@pytest.mark.integration
@pytest.mark.asyncio
async def test_declared_content_length_far_over_limit_is_rejected_early(
    client, session, storage_root
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await _upload(
        client, owner, workspace.id, "a.txt", b"a" * (MAX_UPLOAD_BYTES + 200_000)
    )

    assert response.status_code == 413
    assert _blobs(storage_root) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_declared_content_length_over_limit_never_reads_body(
    client, session, storage_root, monkeypatch
):
    """Sem o guarda de Content-Length o corpo seria lido: aqui ele não é tocado."""
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    calls: list[str] = []

    async def spy_upload(self, **kwargs):
        calls.append("upload")
        raise AssertionError("handler não deveria rodar")

    monkeypatch.setattr(DocumentService, "upload_document", spy_upload)
    pulled = 0

    async def body():
        nonlocal pulled
        pulled += 1
        yield b"x"

    headers = {
        **_auth(owner),
        "Content-Type": "multipart/form-data; boundary=b",
        "Content-Length": str(MAX_UPLOAD_BYTES + 10 * 1024 * 1024),
    }
    response = await client.post(_url(workspace.id), content=body(), headers=headers)

    assert response.status_code == 413
    assert pulled == 0
    assert calls == []
    assert _blobs(storage_root) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunked_body_far_over_limit_is_aborted_with_413(client, storage_root):
    """Sem Content-Length e sem autenticação: leitura limitada ao teto + folga."""
    chunk = b"a" * 65536
    yielded = 0
    total = 200 * 1024 * 1024

    preamble = (
        b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
    )

    async def body():
        nonlocal yielded
        yield preamble
        while yielded * len(chunk) < total:
            yielded += 1
            yield chunk

    response = await client.post(
        "/api/v1/workspaces/1/documents",
        content=body(),
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": DOCUMENT_TOO_LARGE_DETAIL}
    assert yielded * len(chunk) <= MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD + len(chunk)
    assert _blobs(storage_root) == []


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data", "ctype", "status"),
    [
        ("a.exe", b"MZ", None, 415),
        ("semextensao", b"x", None, 415),
        ("a.pdf", _PDF, "text/plain", 415),
        ("a.pdf", b"<html>falso</html>", None, 422),
        ("a.txt", b"\xff\xfe\xfa", None, 422),
        ("a.txt", b"ab\x00cd", None, 422),
        ("a.txt", b"", None, 422),
        ("..", b"x", None, 422),
    ],
)
async def test_invalid_uploads_are_rejected_without_persisting(
    client, session, storage_root, name, data, ctype, status
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await _upload(client, owner, workspace.id, name, data, ctype)

    assert response.status_code == status
    assert _blobs(storage_root) == []
    assert await _count(session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_file_field_gets_422(client, session):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    response = await client.post(
        _url(workspace.id), data={"outro": "x"}, headers=_auth(owner)
    )

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_failure_returns_500_and_removes_blob(
    client, session, storage_root, monkeypatch
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    before = await _count(session)

    async def boom(self, **kwargs):
        raise RuntimeError("falha de insert com /caminho/secreto")

    monkeypatch.setattr(DocumentRepository, "create", boom)
    response = await _upload(client, owner, workspace.id, "a.txt", b"conteudo")

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert "secreto" not in response.text
    assert _blobs(storage_root) == []
    assert await _count(session) == before


def _fail_second_commit(session, monkeypatch, *, really_commit: bool):
    """A 1ª chamada (fim da transação de leitura) passa; a 2ª (commit da linha)
    falha, antes ou depois de confirmar de verdade."""
    real_commit = session.commit
    calls = 0

    async def commit():
        nonlocal calls
        calls += 1
        if calls < 2:
            await real_commit()
            return
        if really_commit:
            await real_commit()
        raise OperationalError("COMMIT", None, Exception("conexao caiu"))

    monkeypatch.setattr(session, "commit", commit)
    return real_commit


@pytest.mark.integration
@pytest.mark.asyncio
async def test_commit_succeeded_then_connection_error_keeps_blob_and_row(
    client, session, storage_root, monkeypatch, caplog
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    real_commit = _fail_second_commit(session, monkeypatch, really_commit=True)
    with caplog.at_level("ERROR"):
        response = await _upload(
            client, owner, workspace.id, "segredo.txt", b"conteudo"
        )
    monkeypatch.setattr(session, "commit", real_commit)

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    blobs = _blobs(storage_root)
    assert len(blobs) == 1
    assert blobs[0].read_bytes() == b"conteudo"
    assert await _count(session) == 1
    key = await session.scalar(select(Document.storage_key))
    assert blobs[0].name == key
    assert "stage=commit_uncertain" in caplog.text
    assert "OperationalError" in caplog.text
    assert key not in caplog.text
    assert "segredo" not in caplog.text
    assert str(storage_root) not in caplog.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_commit_failure_without_commit_keeps_blob_for_reconciliation(
    client, session, storage_root, monkeypatch
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)
    real_commit = _fail_second_commit(session, monkeypatch, really_commit=False)
    response = await _upload(client, owner, workspace.id, "a.txt", b"conteudo")
    monkeypatch.setattr(session, "commit", real_commit)

    assert response.status_code == 500
    assert await _count(session) == 0
    blobs = _blobs(storage_root)
    assert len(blobs) == 1  # incerto: o blob não é apagado

    storage = LocalDocumentStorage(storage_root)
    future = time.time() + 7200
    assert await find_orphan_blobs(session, storage, now=future) == [blobs[0].name]
    report = await reconcile_orphans(session, storage, dry_run=False, now=future)
    assert report.removed_blobs == 1
    assert _blobs(storage_root) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failure_before_commit_removes_blob(
    client, session, storage_root, monkeypatch
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    async def failing_create(self, **kwargs):
        raise RuntimeError("flush falhou")

    monkeypatch.setattr(DocumentRepository, "create", failing_create)
    response = await _upload(client, owner, workspace.id, "a.txt", b"conteudo")

    assert response.status_code == 500
    assert _blobs(storage_root) == []
    assert await _count(session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_storage_failure_returns_500_and_no_row(
    client, session, storage_root, monkeypatch
):
    owner = await _user(session)
    workspace = await _workspace(session, owner)

    def boom(fd, data):
        raise OSError("disco cheio em /caminho/secreto")

    monkeypatch.setattr("app.storage.local.os.write", boom)
    response = await _upload(client, owner, workspace.id, "a.txt", b"conteudo")

    assert response.status_code == 500
    assert "secreto" not in response.text
    assert _blobs(storage_root) == []
    assert await _count(session) == 0
