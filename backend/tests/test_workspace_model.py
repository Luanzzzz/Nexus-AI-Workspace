from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace


def _user(name: str) -> User:
    return User(
        email=f"test-{uuid4().hex}@example.com",
        password_hash="fake-password-hash",
        name=name,
    )


def _workspace(owner_id: int) -> Workspace:
    return Workspace(
        name="Test Workspace",
        slug=f"workspace-{uuid4().hex}",
        owner_id=owner_id,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_workspace_assigns_id():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        session.add(owner)
        await session.flush()

        workspace = _workspace(owner.id)
        session.add(workspace)
        await session.flush()

        assert workspace.id is not None
        assert workspace.name == "Test Workspace"
        assert workspace.owner_id == owner.id

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_owner_references_existing_user():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        session.add(owner)
        await session.flush()

        workspace = _workspace(owner.id)
        session.add(workspace)
        await session.flush()
        await session.refresh(workspace, attribute_names=["owner"])

        assert workspace.owner_id == owner.id
        assert workspace.owner.id == owner.id
        assert workspace.owner.email == owner.email

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_workspace_slug_raises_integrity_error():
    async with SessionLocal() as session:
        owner = _user("Workspace Owner")
        session.add(owner)
        await session.flush()

        slug = f"workspace-{uuid4().hex}"
        session.add(Workspace(name="First Workspace", slug=slug, owner_id=owner.id))
        session.add(Workspace(name="Second Workspace", slug=slug, owner_id=owner.id))

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_rejects_missing_owner():
    async with SessionLocal() as session:
        workspace = _workspace(owner_id=999_999_999)
        session.add(workspace)

        with pytest.raises(IntegrityError):
            await session.flush()

        await session.rollback()
