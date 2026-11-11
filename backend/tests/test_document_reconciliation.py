"""Reconciliação de blobs órfãos e temporários antigos (storage em tmp_path)."""

import os
import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.models.document import Document
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.services.document_reconciliation import (
    find_orphan_blobs,
    reconcile_orphans,
)
from app.storage.local import LocalDocumentStorage

_NOW = 1_000_000.0
_OLD = _NOW - 7200  # mais antigo que a janela de 1 h
_FRESH = _NOW - 10


@pytest_asyncio.fixture
async def session():
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
def root(tmp_path):
    path = tmp_path / "storage"
    path.mkdir()
    return path


@pytest.fixture
def storage(root):
    return LocalDocumentStorage(root)


def _blob(root, mtime=_OLD, key=None):
    key = key or secrets.token_hex(16)
    shard = root / key[:2]
    shard.mkdir(exist_ok=True)
    path = shard / key
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))
    return key


def _tmp(root, mtime):
    tmp_dir = root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    path = tmp_dir / f"{secrets.token_hex(16)}.part"
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))
    return path


async def _row(session, key):
    user = await UserRepository(session).create_user(
        name="U", email=f"r-{uuid4().hex}@example.com", password_hash="h"
    )
    workspace = await WorkspaceRepository(session).create(
        name="W", slug=f"ws-{uuid4().hex[:12]}", owner_id=user.id
    )
    session.add(
        Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="a.txt",
            mime_type="text/plain",
            size_bytes=1,
            storage_key=key,
            status="uploaded",
            metadata_={},
        )
    )
    await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orphan_is_detected_and_removed_referenced_is_kept(
    session, storage, root
):
    orphan = _blob(root)
    referenced = _blob(root)
    await _row(session, referenced)

    report = await reconcile_orphans(session, storage, dry_run=False, now=_NOW)

    assert report.orphan_blobs == (orphan,)
    assert report.removed_blobs == 1
    assert not (root / orphan[:2] / orphan).exists()
    assert (root / referenced[:2] / referenced).exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dry_run_is_default_and_removes_nothing(session, storage, root):
    orphan = _blob(root)
    stale = _tmp(root, _OLD)

    report = await reconcile_orphans(session, storage, now=_NOW)

    assert report.dry_run is True
    assert report.orphan_blobs == (orphan,)
    assert len(report.stale_tmp) == 1
    assert report.removed_blobs == report.removed_tmp == 0
    assert (root / orphan[:2] / orphan).exists()
    assert stale.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fresh_blob_is_not_an_orphan_candidate(session, storage, root):
    # Upload em andamento: blob publicado, linha ainda não confirmada.
    fresh = _blob(root, mtime=_FRESH)

    assert await find_orphan_blobs(session, storage, now=_NOW) == []
    report = await reconcile_orphans(session, storage, dry_run=False, now=_NOW)

    assert report.removed_blobs == 0
    assert (root / fresh[:2] / fresh).exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_tmp_removed_fresh_tmp_kept(session, storage, root):
    stale = _tmp(root, _OLD)
    fresh = _tmp(root, _FRESH)

    report = await reconcile_orphans(session, storage, dry_run=False, now=_NOW)

    assert report.removed_tmp == 1
    assert not stale.exists()
    assert fresh.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_symlinks_and_invalid_names_are_ignored(session, storage, root, tmp_path):
    outside = tmp_path / "fora"
    outside.mkdir()
    victim = outside / "vitima"
    victim.write_bytes(b"nao apagar")
    os.utime(victim, (_OLD, _OLD))

    # symlink de arquivo com nome de chave válida
    key = secrets.token_hex(16)
    shard = root / key[:2]
    shard.mkdir()
    os.symlink(victim, shard / key)
    # shard que é symlink para diretório externo com um "blob" válido dentro
    ext_key = "ab" + secrets.token_hex(15)
    (outside / ext_key).write_bytes(b"externo")
    os.utime(outside / ext_key, (_OLD, _OLD))
    os.symlink(outside, root / "ab")
    # nomes inválidos
    (shard / "nao-e-chave").write_bytes(b"x")
    (shard / key.upper().replace("0", "G")).write_bytes(b"x")
    (root / "zz").mkdir()
    (root / "zz" / secrets.token_hex(16)).write_bytes(b"x")
    # .tmp com symlink e nome inválido
    tmp_dir = root / ".tmp"
    tmp_dir.mkdir()
    os.symlink(victim, tmp_dir / f"{secrets.token_hex(16)}.part")
    (tmp_dir / "lixo.part").write_bytes(b"x")
    os.utime(tmp_dir / "lixo.part", (_OLD, _OLD))

    report = await reconcile_orphans(session, storage, dry_run=False, now=_NOW)

    assert report.orphan_blobs == ()
    assert report.stale_tmp == ()
    assert victim.read_bytes() == b"nao apagar"
    assert (outside / ext_key).exists()
    assert (shard / "nao-e-chave").exists()
    assert (tmp_dir / "lixo.part").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_storage_root_is_empty(session, tmp_path):
    storage = LocalDocumentStorage(tmp_path / "nao-existe")

    report = await reconcile_orphans(session, storage, dry_run=False, now=_NOW)

    assert report.orphan_blobs == () and report.stale_tmp == ()
    assert not (tmp_path / "nao-existe").exists()


def test_delete_tmp_rejects_invalid_names(storage):
    from app.core.exceptions import StorageError

    for name in ("../x.part", "x.part", "a" * 32, ""):
        with pytest.raises(StorageError):
            storage.delete_tmp(name)
