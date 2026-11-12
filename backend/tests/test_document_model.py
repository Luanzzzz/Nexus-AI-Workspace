from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace


async def _workspace(session) -> tuple[User, Workspace]:
    user = User(
        email=f"test-{uuid4().hex}@example.com",
        password_hash="fake-password-hash",
        name="Owner",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(name="WS", slug=f"workspace-{uuid4().hex}", owner_id=user.id)
    session.add(workspace)
    await session.flush()
    return user, workspace


def _doc(user: User, workspace: Workspace, **overrides) -> Document:
    data = {
        "workspace_id": workspace.id,
        "uploaded_by": user.id,
        "filename": "a.pdf",
        "mime_type": "application/pdf",
        "storage_key": f"key-{uuid4().hex}",
        "size_bytes": 10,
    }
    data.update(overrides)
    return Document(**data)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_document_with_defaults():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        doc = _doc(user, workspace)
        session.add(doc)
        await session.flush()
        await session.refresh(doc)

        assert doc.id is not None
        assert doc.status == "uploaded"
        assert doc.metadata_ == {}
        assert doc.created_at is not None
        assert doc.workspace_id == workspace.id
        assert doc.uploaded_by == user.id
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_default_status_applies_at_database_level():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        row = await session.execute(
            text(
                "INSERT INTO documents (workspace_id, uploaded_by, filename, "
                "mime_type, created_at, storage_key, size_bytes) "
                "VALUES (:w, :u, 'a', 'text/plain', now(), :k, 1) "
                "RETURNING status, metadata"
            ),
            {"w": workspace.id, "u": user.id, "k": f"key-{uuid4().hex}"},
        )
        status, metadata = row.one()
        assert status == "uploaded"
        assert metadata == {}
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metadata_column_is_named_metadata_and_roundtrips():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        doc = _doc(user, workspace, metadata_={"pages": 3})
        session.add(doc)
        await session.flush()

        cols = await session.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'documents'"
            )
        )
        types = dict(cols.all())
        assert types["metadata"] == "jsonb"
        assert "metadata_" not in types

        value = await session.execute(
            text("SELECT metadata FROM documents WHERE id = :i"), {"i": doc.id}
        )
        assert value.scalar_one() == {"pages": 3}
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["uploaded", "processing", "ready", "failed"])
async def test_valid_statuses_accepted(status):
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, status=status))
        await session.flush()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_status_rejected():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, status="bogus"))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_negative_size_rejected_and_zero_allowed():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, size_bytes=0))
        await session.flush()
        session.add(_doc(user, workspace, size_bytes=-1))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_storage_key_unique():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, storage_key="same-key"))
        await session.flush()
        session.add(_doc(user, workspace, storage_key="same-key"))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_foreign_keys_enforced():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, workspace_id=2_000_000_000))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace, uploaded_by=2_000_000_000))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_workspace_with_documents_is_restricted():
    async with SessionLocal() as session:
        user, workspace = await _workspace(session)
        session.add(_doc(user, workspace))
        await session.flush()
        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM workspaces WHERE id = :i"), {"i": workspace.id}
            )
        await session.rollback()
