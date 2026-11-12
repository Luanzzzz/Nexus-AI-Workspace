"""LocalDocumentStorage: sempre em tmp_path, sem banco."""

import os
import re
import stat

import pytest

from app.core.exceptions import DocumentTooLargeError, StorageError
from app.services.document_validation import MAX_UPLOAD_BYTES
from app.storage import local
from app.storage.local import LocalDocumentStorage

KEY_RE = re.compile(r"[0-9a-f]{32}")


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


async def _sized(total: int, size: int = 64 * 1024):
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        yield b"a" * n
        sent += n


@pytest.fixture
def storage(tmp_path):
    return LocalDocumentStorage(tmp_path / "docs")


def _files(root):
    return [p for p in root.rglob("*") if p.is_file()]


@pytest.mark.asyncio
async def test_save_open_delete_roundtrip(storage, tmp_path):
    stored = await storage.save(_chunks(b"ola ", b"mundo"), max_bytes=100)

    assert KEY_RE.fullmatch(stored.key)
    assert stored.size == 9
    with storage.open(stored.key) as handle:
        assert handle.read() == b"ola mundo"
    path = tmp_path / "docs" / stored.key[:2] / stored.key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "docs").stat().st_mode) == 0o700

    assert storage.delete(stored.key) is True
    assert storage.delete(stored.key) is False
    with pytest.raises(FileNotFoundError):
        storage.open(stored.key)
    assert _files(tmp_path / "docs") == []


@pytest.mark.asyncio
async def test_same_content_gets_distinct_keys_without_overwrite(storage):
    first = await storage.save(_chunks(b"um"), max_bytes=100)
    second = await storage.save(_chunks(b"dois"), max_bytes=100)

    assert first.key != second.key
    with storage.open(first.key) as handle:
        assert handle.read() == b"um"


@pytest.mark.asyncio
async def test_over_limit_aborts_and_leaves_no_files(storage, tmp_path):
    with pytest.raises(DocumentTooLargeError):
        await storage.save(_sized(MAX_UPLOAD_BYTES + 1), max_bytes=MAX_UPLOAD_BYTES)

    assert _files(tmp_path / "docs") == []


@pytest.mark.asyncio
async def test_exactly_limit_is_accepted(storage):
    stored = await storage.save(_sized(MAX_UPLOAD_BYTES), max_bytes=MAX_UPLOAD_BYTES)

    assert stored.size == MAX_UPLOAD_BYTES


@pytest.mark.asyncio
async def test_write_failure_leaves_no_temp(storage, tmp_path, monkeypatch):
    def boom(fd, data):
        raise OSError("disco cheio")

    monkeypatch.setattr(local.os, "write", boom)
    with pytest.raises(OSError):
        await storage.save(_chunks(b"abc"), max_bytes=100)

    assert _files(tmp_path / "docs") == []


@pytest.mark.asyncio
async def test_source_failure_leaves_no_temp(storage, tmp_path):
    async def failing():
        yield b"abc"
        raise ValueError("origem quebrou")

    with pytest.raises(ValueError):
        await storage.save(failing(), max_bytes=100)

    assert _files(tmp_path / "docs") == []


@pytest.mark.parametrize(
    "key",
    [
        "../x",
        "../../etc/passwd",
        "/etc/passwd",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "g" * 32,
        ("a" * 30) + "/x",
        "",
        "a" * 32 + "\n",
    ],
)
def test_malformed_keys_are_refused(storage, key):
    with pytest.raises(StorageError):
        storage.open(key)
    with pytest.raises(StorageError):
        storage.delete(key)


@pytest.mark.asyncio
async def test_symlink_blob_is_refused(storage, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"segredo")
    stored = await storage.save(_chunks(b"x"), max_bytes=10)
    blob = tmp_path / "docs" / stored.key[:2] / stored.key
    blob.unlink()
    blob.symlink_to(outside)

    with pytest.raises(StorageError):
        storage.open(stored.key)
    with pytest.raises(StorageError):
        storage.delete(stored.key)
    assert outside.read_bytes() == b"segredo"


@pytest.mark.asyncio
async def test_symlink_shard_directory_is_refused(storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    key = "ab" + "0" * 30
    (outside / key).write_bytes(b"segredo")
    await storage.save(_chunks(b"x"), max_bytes=10)  # cria o root
    (tmp_path / "docs" / "ab").symlink_to(outside, target_is_directory=True)

    with pytest.raises(StorageError):
        storage.open(key)
    with pytest.raises(StorageError):
        storage.delete(key)
    assert (outside / key).exists()


def test_open_and_delete_on_missing_root(tmp_path):
    storage = LocalDocumentStorage(tmp_path / "nao-existe")
    key = "0" * 32

    assert storage.delete(key) is False
    with pytest.raises(FileNotFoundError):
        storage.open(key)
    assert not os.path.exists(tmp_path / "nao-existe")
