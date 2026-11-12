"""Cenário multi-tenant ponta a ponta da Fase 3 (etapa 3.7).

Fluxo HTTP real: workspaces criados pela API, memberships adicionados pelo
repositório, uploads/listagens/leituras/exclusões entre tenants. Verifica que
nenhuma resposta de erro revela metadados do outro tenant e que banco e
storage ficam intactos depois de operações negadas.

Banco: só nexus_ai_test (transação externa revertida). Storage: só tmp_path.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.api.dependencies.documents import get_document_storage
from app.core.config import settings
from app.core.tokens import create_access_token
from app.db.session import engine
from app.main import app
from app.models.document import Document
from app.models.user import User
from app.repositories.user import UserRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.storage.local import LocalDocumentStorage

_PDF = b"%PDF-1.7\n%conteudo\n"
_SECRET_NAME = "plano-secreto-do-tenant-b.txt"
_SECRET_BODY = b"conteudo-ultra-confidencial-do-b"


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
        email=f"p3-{uuid4().hex}@example.com",
        password_hash="hash-ficticio",
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _create_workspace(client, owner: User) -> int:
    response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Tenant", "slug": f"t-{uuid4().hex[:12]}"},
        headers=_auth(owner),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _url(workspace_id: int, document_id: int | None = None) -> str:
    base = f"/api/v1/workspaces/{workspace_id}/documents"
    return base if document_id is None else f"{base}/{document_id}"


async def _upload(client, user, workspace_id, name, data):
    return await client.post(
        _url(workspace_id), files={"file": (name, data)}, headers=_auth(user)
    )


def _blobs(root) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def _rows(session) -> set[tuple[int, str, str]]:
    result = await session.execute(
        select(Document.id, Document.filename, Document.storage_key)
    )
    return {tuple(row) for row in result.all()}


class _World:
    """Dois tenants: A (alice owner, ana admin) e B (bruno owner, bia member,
    vera viewer). Alice não tem vínculo algum com B."""


@pytest_asyncio.fixture
async def world(client, session) -> _World:
    w = _World()
    w.alice, w.ana = await _user(session), await _user(session)
    w.bruno = await _user(session)
    w.bia = await _user(session)
    w.vera = await _user(session)
    w.ws_a = await _create_workspace(client, w.alice)
    w.ws_b = await _create_workspace(client, w.bruno)
    members = WorkspaceMemberRepository(session)
    await members.create(workspace_id=w.ws_a, user_id=w.ana.id, role="admin")
    await members.create(workspace_id=w.ws_b, user_id=w.bia.id, role="member")
    await members.create(workspace_id=w.ws_b, user_id=w.vera.id, role="viewer")
    return w


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_flow_isolates_workspaces(
    client, session, storage_root, world
):
    w = world
    # B (owner) envia PDF, TXT secreto e MD; A (admin) envia seu próprio PDF.
    up_b_pdf = await _upload(client, w.bruno, w.ws_b, "b.pdf", _PDF)
    up_b_secret = await _upload(client, w.bruno, w.ws_b, _SECRET_NAME, _SECRET_BODY)
    up_b_md = await _upload(client, w.bruno, w.ws_b, "b.md", b"# b\n")
    up_a = await _upload(client, w.ana, w.ws_a, "a.pdf", _PDF)
    for response in (up_b_pdf, up_b_secret, up_b_md, up_a):
        assert response.status_code == 201
        assert response.json()["status"] == "uploaded"
    secret = up_b_secret.json()
    doc_a = up_a.json()
    assert (secret["workspace_id"], doc_a["workspace_id"]) == (w.ws_b, w.ws_a)

    # Listagens isoladas por tenant.
    list_a = await client.get(_url(w.ws_a), headers=_auth(w.alice))
    list_b = await client.get(_url(w.ws_b), headers=_auth(w.vera))
    assert [i["id"] for i in list_a.json()["items"]] == [doc_a["id"]]
    assert list_a.json()["total"] == 1
    assert list_b.json()["total"] == 3
    assert {i["workspace_id"] for i in list_b.json()["items"]} == {w.ws_b}
    assert _SECRET_NAME not in list_a.text

    # Estado de referência antes de qualquer tentativa negada.
    rows_before, blobs_before = await _rows(session), _blobs(storage_root)
    assert len(rows_before) == 4
    assert len(blobs_before) == 4

    sensitive = [
        _SECRET_NAME,
        _SECRET_BODY.decode(),
        "text/plain",
        "storage_key",
        str(storage_root),
    ]
    sensitive += [row[2] for row in rows_before]

    # Alice (sem vínculo com B) tenta tudo contra o workspace B e contra o doc
    # de B via o próprio workspace. Todas as respostas são 404 e idênticas
    # ao caso "inexistente".
    missing_ws = 2147483000
    attempts = [
        ("GET", _url(w.ws_b)),
        ("GET", _url(w.ws_b, secret["id"])),
        ("DELETE", _url(w.ws_b, secret["id"])),
        ("GET", _url(w.ws_a, secret["id"])),
        ("DELETE", _url(w.ws_a, secret["id"])),
    ]
    for method, url in attempts:
        response = await client.request(method, url, headers=_auth(w.alice))
        assert response.status_code == 404, (method, url)
        for needle in sensitive:
            assert needle not in response.text, (method, url, needle)
        assert response.json()["detail"] in {
            "Workspace não encontrado.",
            "Documento não encontrado.",
        }
    denied_upload = await _upload(client, w.alice, w.ws_b, "x.txt", b"x")
    assert denied_upload.status_code == 404
    ghost = await client.get(_url(missing_ws), headers=_auth(w.alice))
    foreign = await client.get(_url(w.ws_b), headers=_auth(w.alice))
    assert ghost.status_code == foreign.status_code == 404
    assert ghost.json() == foreign.json()

    # Papéis insuficientes em B: member/viewer leem, mas não enviam nem excluem.
    for user in (w.bia, w.vera):
        read = await client.get(_url(w.ws_b, secret["id"]), headers=_auth(user))
        assert read.status_code == 200
        up = await _upload(client, user, w.ws_b, "n.txt", b"n")
        rm = await client.delete(_url(w.ws_b, secret["id"]), headers=_auth(user))
        for response in (up, rm):
            assert response.status_code == 403
            assert response.json() == {"detail": "Permissão insuficiente."}
            for needle in sensitive:
                assert needle not in response.text

    # JWT inválido/ausente: 401 sem efeito colateral.
    for headers in ({}, {"Authorization": "Bearer lixo.invalido.token"}):
        for method, url in [
            ("GET", _url(w.ws_b, secret["id"])),
            ("DELETE", _url(w.ws_b, secret["id"])),
        ]:
            response = await client.request(method, url, headers=headers)
            assert response.status_code == 401
            assert _SECRET_NAME not in response.text
        response = await client.post(
            _url(w.ws_b), files={"file": ("x.txt", b"x")}, headers=headers
        )
        assert response.status_code == 401

    # Nada mudou no banco nem no storage após todas as negações.
    assert await _rows(session) == rows_before
    assert _blobs(storage_root) == blobs_before

    # O dono de B continua lendo o documento intacto.
    ok = await client.get(_url(w.ws_b, secret["id"]), headers=_auth(w.bruno))
    assert ok.status_code == 200
    assert ok.json()["filename"] == _SECRET_NAME
    assert "storage_key" not in ok.json()

    # Delete autorizado remove só o alvo; o outro tenant e os demais ficam.
    deleted = await client.delete(_url(w.ws_b, secret["id"]), headers=_auth(w.bruno))
    assert deleted.status_code == 204
    assert deleted.content == b""
    after = await _rows(session)
    assert {r[0] for r in rows_before} - {r[0] for r in after} == {secret["id"]}
    assert len(_blobs(storage_root)) == 3
    assert any(r[0] == doc_a["id"] for r in after)
    again = await client.get(_url(w.ws_b, secret["id"]), headers=_auth(w.bruno))
    assert again.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_filename_in_two_workspaces_gets_distinct_blobs(
    client, session, storage_root, world
):
    w = world
    first = await _upload(client, w.alice, w.ws_a, "igual.txt", b"conteudo A")
    second = await _upload(client, w.bruno, w.ws_b, "igual.txt", b"conteudo B")
    assert first.status_code == second.status_code == 201

    keys = [row[2] for row in await _rows(session)]
    assert len(set(keys)) == 2
    assert len(_blobs(storage_root)) == 2
    storage = LocalDocumentStorage(storage_root)
    contents = set()
    for key in keys:
        with storage.open(key) as handle:
            contents.add(handle.read())
    assert contents == {b"conteudo A", b"conteudo B"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rejected_uploads_leave_no_trace_in_any_tenant(
    client, session, storage_root, world
):
    w = world
    bad = [
        ("x.exe", b"MZ\x90\x00"),
        ("x.pdf", b"nao e pdf"),
        ("x.txt", b"\xff\xfe\x00invalido"),
        ("x.md", b""),
    ]
    for name, data in bad:
        response = await _upload(client, w.bruno, w.ws_b, name, data)
        assert response.status_code in {413, 415, 422}, name
    too_big = await _upload(
        client, w.bruno, w.ws_b, "big.txt", b"a" * (10 * 1024 * 1024 + 1)
    )
    assert too_big.status_code == 413
    assert await _rows(session) == set()
    assert _blobs(storage_root) == set()


def test_document_storage_dir_is_isolated_per_test_by_conftest(tmp_path):
    """A fixture autouse do conftest nunca deixa o diretório real em uso."""
    real_default = "backend/var/documents"
    assert not str(settings.document_storage_dir).endswith(real_default)
    assert "default-document-storage" in str(settings.document_storage_dir)
