"""Caso de uso de criação de workspace, sem passar pelo endpoint.

O serviço chama commit(). Os testes de uma sessão usam SAVEPOINT na transação
externa. A corrida de slug usa SessionLocal de verdade (cada tarefa com a
própria sessão) e apaga o que criou no final.
"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateSlugError
from app.db.session import SessionLocal, engine
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.repositories.user import UserRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace import WorkspaceService


def _slug() -> str:
    return f"svc-{uuid4().hex[:12]}"


async def _new_user(session: AsyncSession) -> User:
    return await UserRepository(session).create_user(
        name="Usuário Teste",
        email=f"svc-{uuid4().hex}@example.com",
        password_hash="hash-ficticio",
    )


async def _count(session: AsyncSession, slug: str) -> int:
    return await session.scalar(
        select(func.count()).select_from(Workspace).where(Workspace.slug == slug)
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_workspace_is_atomic_with_owner_membership():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            user = await _new_user(session)
            slug = _slug()
            workspace = await WorkspaceService(session).create_workspace(
                WorkspaceCreate(name="Time", slug=slug), user
            )
            member = await WorkspaceMemberRepository(session).get_membership(
                workspace.id, user.id
            )
            assert workspace.owner_id == user.id
            assert member is not None and member.role == "owner"
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_membership_failure_rolls_back_workspace(monkeypatch):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            user = await _new_user(session)
            slug = _slug()
            service = WorkspaceService(session)

            async def failing_create(**kwargs: object) -> None:
                raise RuntimeError("falha simulada na membership")

            monkeypatch.setattr(service.members, "create", failing_create)

            with pytest.raises(RuntimeError):
                await service.create_workspace(
                    WorkspaceCreate(name="Time", slug=slug), user
                )

            # Sem workspace órfão: o rollback desfez o INSERT já com flush.
            assert await _count(session, slug) == 0
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_membership_integrity_error_rolls_back_workspace():
    # Falha real do banco (role fora do CHECK) depois do flush do workspace.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            user = await _new_user(session)
            slug = _slug()
            service = WorkspaceService(session)
            original = service.members.create

            async def bad_role(**kwargs: object) -> WorkspaceMember:
                return await original(**{**kwargs, "role": "inexistente"})

            service.members.create = bad_role  # type: ignore[method-assign]

            with pytest.raises(IntegrityError):
                await service.create_workspace(
                    WorkspaceCreate(name="Time", slug=slug), user
                )
            assert await _count(session, slug) == 0
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_slug_raises_domain_error():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            user = await _new_user(session)
            slug = _slug()
            service = WorkspaceService(session)
            await service.create_workspace(WorkspaceCreate(name="A", slug=slug), user)
            with pytest.raises(DuplicateSlugError):
                await service.create_workspace(
                    WorkspaceCreate(name="B", slug=slug), user
                )
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_same_slug_creates_exactly_one_workspace():
    slug = _slug()
    user_ids: list[int] = []
    try:
        async with SessionLocal() as setup:
            users = [await _new_user(setup) for _ in range(2)]
            user_ids = [user.id for user in users]
            await setup.commit()

        # Duas sessões reais passam juntas pela consulta prévia (barreira);
        # só a UNIQUE do banco decide quem fica.
        barrier = asyncio.Barrier(2)

        async def attempt(user_id: int) -> str:
            async with SessionLocal() as session:
                user = await session.get(User, user_id)
                service = WorkspaceService(session)
                original = service.workspaces.get_by_slug

                async def synced_get_by_slug(value: str) -> Workspace | None:
                    found = await original(value)
                    await barrier.wait()
                    return found

                service.workspaces.get_by_slug = synced_get_by_slug  # type: ignore[method-assign]
                try:
                    await service.create_workspace(
                        WorkspaceCreate(name="Corrida", slug=slug), user
                    )
                except DuplicateSlugError:
                    return "duplicate"
                return "created"

        results = await asyncio.gather(*(attempt(uid) for uid in user_ids))

        assert sorted(results) == ["created", "duplicate"]
        async with SessionLocal() as check:
            assert await _count(check, slug) == 1
            members = await check.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                .where(Workspace.slug == slug)
            )
            assert members == 1
    finally:
        async with SessionLocal() as cleanup:
            ids = select(Workspace.id).where(Workspace.slug == slug)
            await cleanup.execute(
                delete(WorkspaceMember).where(WorkspaceMember.workspace_id.in_(ids))
            )
            await cleanup.execute(delete(Workspace).where(Workspace.slug == slug))
            if user_ids:
                await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
            await cleanup.commit()
