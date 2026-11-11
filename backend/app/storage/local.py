"""Storage local de documentos em filesystem.

Layout: <root>/<2 primeiros hex da chave>/<chave> e <root>/.tmp/ para
gravações em andamento (mesmo filesystem, então os.replace é atômico).
A chave tem 32 hex minúsculos gerados no servidor; nunca deriva do filename.

I/O: o filesystem é síncrono; cada bloco de 64 KiB e cada passo de
finalização rodam em asyncio.to_thread para não travar o event loop.
open() e delete() são síncronos e rápidos (uma syscall cada); o serviço
chama delete() via to_thread.

Segurança: a chave é validada por regex ANTES de qualquer caminho existir, e
os acessos usam descritores de diretório com O_NOFOLLOW, então symlinks
(no diretório do shard ou no arquivo) são recusados sem corrida TOCTOU.
Mensagens de erro nunca incluem caminhos.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import stat
from collections.abc import AsyncIterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.exceptions import DocumentTooLargeError, StorageError

_KEY_RE = re.compile(r"[0-9a-f]{32}")
_TMP_DIR = ".tmp"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    sha256: str


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _check_key(key: str) -> str:
    if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
        raise StorageError("Chave de storage inválida.")
    return key


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    # --- diretórios -----------------------------------------------------

    def _open_root(self, *, create: bool) -> int:
        if create:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # O root é configurado pelo operador (pode ser symlink); só os filhos
        # são abertos com O_NOFOLLOW.
        return os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    def _open_subdir(self, root_fd: int, name: str, *, create: bool) -> int:
        if create:
            with suppress(FileExistsError):
                os.mkdir(name, 0o700, dir_fd=root_fd)
        try:
            return os.open(name, _DIR_FLAGS, dir_fd=root_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            # ELOOP/ENOTDIR: symlink ou arquivo no lugar do diretório.
            raise StorageError("Caminho de storage inseguro.") from exc

    # --- save -----------------------------------------------------------

    async def save(self, chunks: AsyncIterable[bytes], *, max_bytes: int) -> StoredFile:
        """Grava os blocos em temporário e publica sob uma chave nova.

        Interrompe com DocumentTooLargeError ao passar de max_bytes. Qualquer
        falha (inclusive do iterador de origem) remove o temporário.
        """
        key = secrets.token_hex(16)
        tmp_name = f"{secrets.token_hex(16)}.part"
        root_fd = tmp_fd = fd = None
        try:
            root_fd, tmp_fd, fd = await asyncio.to_thread(self._start, tmp_name)
            size = 0
            digest = hashlib.sha256()
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentTooLargeError
                await asyncio.to_thread(_write_all, fd, chunk)
                digest.update(chunk)
            await asyncio.to_thread(os.fsync, fd)
            os.close(fd)
            fd = None
            await asyncio.to_thread(self._publish, root_fd, tmp_fd, tmp_name, key)
        except BaseException:
            if fd is not None:
                with suppress(OSError):
                    os.close(fd)
                fd = None
            if tmp_fd is not None:
                with suppress(OSError):
                    os.unlink(tmp_name, dir_fd=tmp_fd)
            raise
        finally:
            for descriptor in (fd, tmp_fd, root_fd):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
        return StoredFile(key=key, size=size, sha256=digest.hexdigest())

    def _start(self, tmp_name: str) -> tuple[int, int, int]:
        root_fd = self._open_root(create=True)
        tmp_fd = fd = None
        try:
            tmp_fd = self._open_subdir(root_fd, _TMP_DIR, create=True)
            fd = os.open(
                tmp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=tmp_fd,
            )
        except BaseException:
            for descriptor in (fd, tmp_fd, root_fd):
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
            raise
        return root_fd, tmp_fd, fd

    def _publish(self, root_fd: int, tmp_fd: int, tmp_name: str, key: str) -> None:
        shard_fd = self._open_subdir(root_fd, key[:2], create=True)
        try:
            os.replace(tmp_name, key, src_dir_fd=tmp_fd, dst_dir_fd=shard_fd)
            os.fsync(shard_fd)
        finally:
            os.close(shard_fd)

    # --- open / delete --------------------------------------------------

    def open(self, key: str) -> BinaryIO:
        """Abre o blob para leitura. FileNotFoundError se não existir."""
        _check_key(key)
        root_fd = self._open_root(create=False)
        try:
            shard_fd = self._open_subdir(root_fd, key[:2], create=False)
            try:
                try:
                    fd = os.open(
                        key, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=shard_fd
                    )
                except FileNotFoundError:
                    raise
                except OSError as exc:
                    raise StorageError("Caminho de storage inseguro.") from exc
            finally:
                os.close(shard_fd)
        finally:
            os.close(root_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StorageError("Caminho de storage inseguro.")
            return os.fdopen(fd, "rb")
        except BaseException:
            with suppress(OSError):
                os.close(fd)
            raise

    def delete(self, key: str) -> bool:
        """Remove o blob. False se ele (ou o diretório) já não existia."""
        _check_key(key)
        try:
            root_fd = self._open_root(create=False)
        except FileNotFoundError:
            return False
        try:
            try:
                shard_fd = self._open_subdir(root_fd, key[:2], create=False)
            except FileNotFoundError:
                return False
            try:
                try:
                    mode = os.stat(key, dir_fd=shard_fd, follow_symlinks=False).st_mode
                except FileNotFoundError:
                    return False
                if not stat.S_ISREG(mode):
                    raise StorageError("Caminho de storage inseguro.")
                try:
                    os.unlink(key, dir_fd=shard_fd)
                except FileNotFoundError:
                    return False
                return True
            finally:
                os.close(shard_fd)
        finally:
            os.close(root_fd)
