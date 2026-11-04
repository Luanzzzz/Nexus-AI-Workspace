from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember


def _user(name: str) -> User:
    return User(
        email=f"test-{uuid4().hex}@example.com",
        password_hash="fake-password-hash",
        name=name,
    )


async def _persist_workspace(session, owner: User) -> Workspace:
    session.add(owner)
    await session.flush()
    workspace = Workspace(
        name="Test Workspace",
        slug=f"workspace-{uuid4().hex}",
        owner_id=owner.id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_workspace_member():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        workspace = await _persist_workspace(session, owner)
        member_user = _user("Workspace Member")
        session.add(member_user)
        await session.flush()

        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=member_user.id,
            role="member",
        )
        session.add(membership)
        await session.flush()

        assert membership.id is not None
        assert membership.workspace_id == workspace.id
        assert membership.user_id == member_user.id
        assert membership.role == "member"

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_workspace_member_raises_integrity_error():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        workspace = await _persist_workspace(session, owner)
        member_user = _user("Workspace Member")
        session.add(member_user)
        await session.flush()

        session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=member_user.id,
                role="member",
            )
        )
        session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=member_user.id,
                role="admin",
            )
        )

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_member_rejects_missing_user():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        workspace = await _persist_workspace(session, owner)
        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=999_999_999,
            role="viewer",
        )
        session.add(membership)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_member_rejects_invalid_role():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        workspace = await _persist_workspace(session, owner)
        member_user = _user("Workspace Member")
        session.add(member_user)
        await session.flush()

        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=member_user.id,
            role="superadmin",
        )
        session.add(membership)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_member_loads_related_user_and_workspace():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        workspace = await _persist_workspace(session, owner)
        member_user = _user("Workspace Member")
        session.add(member_user)
        await session.flush()

        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=member_user.id,
            role="admin",
        )
        session.add(membership)
        await session.flush()

        loaded = await session.scalar(
            select(WorkspaceMember)
            .where(WorkspaceMember.id == membership.id)
            .options(
                selectinload(WorkspaceMember.user),
                selectinload(WorkspaceMember.workspace),
            )
        )

        assert loaded is not None
        assert loaded.user.id == member_user.id
        assert loaded.user.email == member_user.email
        assert loaded.workspace.id == workspace.id
        assert loaded.workspace.slug == workspace.slug

        await session.rollback()
