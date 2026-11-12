"""Rotas de workspace e autorização por membership.

Cada teste roda numa transação externa com SAVEPOINT, revertida no fim, em
nexus_ai_test: nenhuma linha fica no banco. get_db é trocado por essa sessão.
Todos os cenários usam dois usuários e dois workspaces.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.api.dependencies.workspace import (
    DELETE_DOCUMENT,
    UPLOAD_DOCUMENT,
    require_permission,
)
from app.core.tokens import create_access_token
from app.db.session import engine
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository

_URL = "/api/v1/workspaces"
_PUBLIC_FIELDS = {"id", "name", "slug", "owner_id", "created_at", "updated_at"}


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


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _user(session: AsyncSession) -> User:
    return await UserRepository(session).create_user(
        name="Usuário Teste",
        email=f"ws-{uuid4().hex}@example.com",
        password_hash="hash-ficticio",
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _slug() -> str:
    return f"ws-{uuid4().hex[:12]}"


async def _make_workspace(
    session: AsyncSession, owner: User, roles: dict[User, str] | None = None
) -> Workspace:
    workspace = await WorkspaceRepository(session).create(
        name="Workspace", slug=_slug(), owner_id=owner.id
    )
    members = WorkspaceMemberRepository(session)
    await members.create(workspace_id=workspace.id, user_id=owner.id, role="owner")
    for user, role in (roles or {}).items():
        await members.create(workspace_id=workspace.id, user_id=user.id, role=role)
    return workspace


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_workspace_creates_membership_with_owner_role(client, session):
    user = await _user(session)
    slug = _slug()

    response = await client.post(
        _URL, json={"name": "Meu Time", "slug": slug}, headers=_auth(user)
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == _PUBLIC_FIELDS
    assert body["slug"] == slug
    assert body["owner_id"] == user.id
    member = await WorkspaceMemberRepository(session).get_membership(
        body["id"], user.id
    )
    assert member is not None
    assert member.role == "owner"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"owner_id": 999999}, {"role": "viewer"}])
async def test_payload_cannot_set_owner_or_role(client, session, extra):
    user = await _user(session)
    slug = _slug()

    response = await client.post(
        _URL, json={"name": "Time", "slug": slug, **extra}, headers=_auth(user)
    )

    # Campos extras são rejeitados (422), não ignorados; nada é gravado.
    assert response.status_code == 422
    assert await WorkspaceRepository(session).get_by_slug(slug) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_slug_returns_generic_409(client, session):
    owner_a = await _user(session)
    owner_b = await _user(session)
    existing = await _make_workspace(session, owner_a)
    slug = existing.slug
    # O serviço faz rollback na duplicidade; o commit fixa o setup no SAVEPOINT.
    await session.commit()

    response = await client.post(
        _URL, json={"name": "Outro", "slug": slug}, headers=_auth(owner_b)
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Slug indisponível."}
    assert slug not in response.text
    total = await session.scalar(
        select(func.count()).select_from(Workspace).where(Workspace.slug == slug)
    )
    assert total == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["AB", "Maiusculo", "-x-", "a--b", "a_b"])
async def test_invalid_slug_returns_422(client, session, slug):
    user = await _user(session)
    response = await client.post(
        _URL, json={"name": "Time", "slug": slug}, headers=_auth(user)
    )
    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_returns_only_workspaces_with_membership(client, session):
    user_a = await _user(session)
    user_b = await _user(session)
    ws_a = await _make_workspace(session, user_a)
    ws_b = await _make_workspace(session, user_b, {user_a: "viewer"})
    ws_c = await _make_workspace(session, user_b)

    response_a = await client.get(_URL, headers=_auth(user_a))
    response_b = await client.get(_URL, headers=_auth(user_b))

    ids_a = {item["id"] for item in response_a.json()}
    ids_b = {item["id"] for item in response_b.json()}
    assert response_a.status_code == response_b.status_code == 200
    assert ids_a == {ws_a.id, ws_b.id}
    assert ids_b == {ws_b.id, ws_c.id}
    assert all(set(item) == _PUBLIC_FIELDS for item in response_a.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_is_empty_without_memberships(client, session):
    user = await _user(session)
    other = await _user(session)
    await _make_workspace(session, other)

    response = await client.get(_URL, headers=_auth(user))

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_detail_returns_workspace_for_member_of_any_role(client, session):
    owner = await _user(session)
    viewer = await _user(session)
    workspace = await _make_workspace(session, owner, {viewer: "viewer"})

    for user in (owner, viewer):
        response = await client.get(f"{_URL}/{workspace.id}", headers=_auth(user))
        assert response.status_code == 200
        assert response.json()["id"] == workspace.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_detail_is_404_for_non_member_and_nonexistent_alike(client, session):
    owner_a = await _user(session)
    owner_b = await _user(session)
    ws_b = await _make_workspace(session, owner_b)
    await _make_workspace(session, owner_a)

    foreign = await client.get(f"{_URL}/{ws_b.id}", headers=_auth(owner_a))
    missing = await client.get(f"{_URL}/2147483647", headers=_auth(owner_a))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert ws_b.slug not in foreign.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id", ["0", "-1", "abc", "2147483648"])
async def test_detail_rejects_out_of_range_id_with_422(client, session, workspace_id):
    user = await _user(session)
    response = await client.get(f"{_URL}/{workspace_id}", headers=_auth(user))
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [("get", _URL), ("get", f"{_URL}/1"), ("post", _URL)],
)
@pytest.mark.parametrize("authorization", [None, "Bearer token-invalido", "Basic x"])
async def test_invalid_or_missing_jwt_returns_401(client, method, path, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    kwargs = {"json": {"name": "Time", "slug": "time"}} if method == "post" else {}

    response = await client.request(method, path, headers=headers, **kwargs)

    assert response.status_code == 401
    assert response.json() == {"detail": "Não autenticado."}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthenticated_create_does_not_persist(client, session):
    slug = _slug()
    await client.post(_URL, json={"name": "Time", "slug": slug})
    assert await WorkspaceRepository(session).get_by_slug(slug) is None


@pytest_asyncio.fixture
async def permission_client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    # App mínimo só para exercitar a dependency reutilizável (PR C/D vão usá-la).
    mini = FastAPI()

    @mini.post("/ws/{workspace_id}/upload")
    async def upload(
        membership: WorkspaceMember = Depends(require_permission(UPLOAD_DOCUMENT)),
    ) -> dict[str, str]:
        return {"role": membership.role}

    @mini.delete("/ws/{workspace_id}/doc")
    async def delete(
        membership: WorkspaceMember = Depends(require_permission(DELETE_DOCUMENT)),
    ) -> dict[str, str]:
        return {"role": membership.role}

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    mini.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=mini, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_permission_dependency_matrix(permission_client, session):
    owner = await _user(session)
    admin = await _user(session)
    member = await _user(session)
    viewer = await _user(session)
    outsider = await _user(session)
    workspace = await _make_workspace(
        session, owner, {admin: "admin", member: "member", viewer: "viewer"}
    )
    other = await _make_workspace(session, outsider)
    upload = f"/ws/{workspace.id}/upload"
    delete = f"/ws/{workspace.id}/doc"

    for allowed in (owner, admin):
        assert (
            await permission_client.post(upload, headers=_auth(allowed))
        ).status_code == 200
        assert (
            await permission_client.delete(delete, headers=_auth(allowed))
        ).status_code == 200

    for denied in (member, viewer):
        up = await permission_client.post(upload, headers=_auth(denied))
        de = await permission_client.delete(delete, headers=_auth(denied))
        assert up.status_code == de.status_code == 403
        assert up.json() == {"detail": "Permissão insuficiente."}

    # Quem não é membro recebe 404 (não 403), inclusive no workspace alheio.
    assert (
        await permission_client.post(upload, headers=_auth(outsider))
    ).status_code == 404
    assert (
        await permission_client.post(f"/ws/{other.id}/upload", headers=_auth(owner))
    ).status_code == 404
    assert (await permission_client.post(upload, headers={})).status_code == 401
