"""Storage local de documentos em filesystem.

Layout: <root>/<2 primeiros hex da chave>/<chave> e <root>/.tmp/ para
gravações em andamento (mesmo filesystem, então o link é atômico). A
publicação usa link + unlink do temporário (nunca os.replace): se a chave já
existir, o link falha e uma nova chave é sorteada, sem sobrescrever blob.
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
from collections.abc import AsyncIterable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.exceptions import DocumentTooLargeError, StorageError

_KEY_RE = re.compile(r"[0-9a-f]{32}")
_TMP_DIR = ".tmp"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


# Tentativas de publicar sob uma chave inédita antes de desistir.
_PUBLISH_ATTEMPTS = 3

_TMP_RE = re.compile(r"[0-9a-f]{32}\.part")
_SHARD_RE = re.compile(r"[0-9a-f]{2}")


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


class _Descriptors:
    """Descritores abertos por save(); cada um é fechado no máximo uma vez."""

    def __init__(self) -> None:
        self.root: int | None = None
        self.tmp: int | None = None
        self.fd: int | None = None

    def close(self, name: str) -> None:
        descriptor = getattr(self, name)
        setattr(self, name, None)
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)

    def close_all(self) -> None:
        for name in ("fd", "tmp", "root"):
            self.close(name)


async def _run_to_completion[**P, T](
    func: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """to_thread que só retorna depois que a thread terminou.

    Cancelar a corrotina não interrompe a thread; sem esperar por ela, o
    chamador fecharia descritores (cujo número pode ser reutilizado) enquanto
    a thread ainda escreve neles ou os abre. O cancelamento é repassado ao fim.
    """
    task = asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            # A thread segue rodando; espera por ela e repassa o cancelamento.
            cancelled = True
            if task.done():
                break
    if cancelled:
        raise asyncio.CancelledError
    return result


def _new_key() -> str:
    return secrets.token_hex(16)


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
        falha (inclusive do iterador de origem ou cancelamento) remove o
        temporário e fecha cada descritor exatamente uma vez.
        """
        key = _new_key()
        tmp_name = f"{secrets.token_hex(16)}.part"
        fds = _Descriptors()
        try:
            await _run_to_completion(self._start, tmp_name, fds)
            size = 0
            digest = hashlib.sha256()
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentTooLargeError
                assert fds.fd is not None
                await _run_to_completion(_write_all, fds.fd, chunk)
                digest.update(chunk)
            assert fds.fd is not None
            await _run_to_completion(os.fsync, fds.fd)
            fds.close("fd")
            assert fds.root is not None and fds.tmp is not None
            key = await _run_to_completion(
                self._publish, fds.root, fds.tmp, tmp_name, key
            )
        except BaseException:
            # Toda thread iniciada já terminou (_run_to_completion), então
            # nenhum fd é fechado enquanto ainda está em uso.
            fds.close("fd")
            if fds.tmp is not None:
                with suppress(OSError):
                    os.unlink(tmp_name, dir_fd=fds.tmp)
            raise
        finally:
            fds.close_all()
        return StoredFile(key=key, size=size, sha256=digest.hexdigest())

    def _start(self, tmp_name: str, fds: _Descriptors) -> None:
        # Registra cada fd em `fds` assim que abre; quem chamou fecha tudo,
        # mesmo que a corrotina tenha sido cancelada durante esta thread.
        fds.root = self._open_root(create=True)
        fds.tmp = self._open_subdir(fds.root, _TMP_DIR, create=True)
        fds.fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=fds.tmp,
        )

    def _publish(self, root_fd: int, tmp_fd: int, tmp_name: str, key: str) -> str:
        """Publica o temporário sem sobrescrever; devolve a chave efetiva.

        os.link falha com FileExistsError se o destino existe (colisão de
        chave): sorteia outra e tenta de novo, até _PUBLISH_ATTEMPTS vezes.
        """
        for _ in range(_PUBLISH_ATTEMPTS):
            shard_fd = self._open_subdir(root_fd, key[:2], create=True)
            try:
                try:
                    os.link(
                        tmp_name,
                        key,
                        src_dir_fd=tmp_fd,
                        dst_dir_fd=shard_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    key = _new_key()
                    continue
                try:
                    os.fsync(shard_fd)
                except BaseException:
                    # O link é nosso (não existia antes): desfaz para não
                    # deixar blob publicado numa operação que falhou.
                    with suppress(OSError):
                        os.unlink(key, dir_fd=shard_fd)
                    raise
                with suppress(OSError):
                    # O blob já está publicado; um .part sobrando (mesmo inode)
                    # é removido por save() ou pela reconciliação.
                    os.unlink(tmp_name, dir_fd=tmp_fd)
                return key
            finally:
                os.close(shard_fd)
        raise StorageError("Não foi possível publicar o blob sob uma chave inédita.")

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

    # --- varredura (reconciliação) --------------------------------------

    def list_blobs(self) -> list[tuple[str, float]]:
        """Lista (chave, mtime) dos blobs publicados.

        Só entram arquivos regulares com nome de chave válida dentro do shard
        correto; symlinks, diretórios e nomes fora do formato são ignorados.
        Nunca sai do root (descritores de diretório + O_NOFOLLOW).
        """
        found: list[tuple[str, float]] = []
        try:
            root_fd = self._open_root(create=False)
        except FileNotFoundError:
            return found
        try:
            with os.scandir(root_fd) as shards:
                shard_names = [
                    e.name
                    for e in shards
                    if _SHARD_RE.fullmatch(e.name) and e.is_dir(follow_symlinks=False)
                ]
            for shard in shard_names:
                try:
                    shard_fd = self._open_subdir(root_fd, shard, create=False)
                except (FileNotFoundError, StorageError):
                    continue
                try:
                    with os.scandir(shard_fd) as entries:
                        for entry in entries:
                            if (
                                _KEY_RE.fullmatch(entry.name)
                                and entry.name.startswith(shard)
                                and entry.is_file(follow_symlinks=False)
                            ):
                                mtime = entry.stat(follow_symlinks=False).st_mtime
                                found.append((entry.name, mtime))
                finally:
                    os.close(shard_fd)
        finally:
            os.close(root_fd)
        return found

    def list_tmp(self) -> list[tuple[str, float]]:
        """Lista (nome, mtime) dos temporários `<32 hex>.part` em .tmp/."""
        found: list[tuple[str, float]] = []
        try:
            root_fd = self._open_root(create=False)
        except FileNotFoundError:
            return found
        try:
            try:
                tmp_fd = self._open_subdir(root_fd, _TMP_DIR, create=False)
            except (FileNotFoundError, StorageError):
                return found
            try:
                with os.scandir(tmp_fd) as entries:
                    for entry in entries:
                        if _TMP_RE.fullmatch(entry.name) and entry.is_file(
                            follow_symlinks=False
                        ):
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            found.append((entry.name, mtime))
            finally:
                os.close(tmp_fd)
        finally:
            os.close(root_fd)
        return found

    def delete_tmp(self, name: str) -> bool:
        """Remove um temporário `.part` regular. False se já não existia."""
        if not isinstance(name, str) or _TMP_RE.fullmatch(name) is None:
            raise StorageError("Nome de temporário inválido.")
        try:
            root_fd = self._open_root(create=False)
        except FileNotFoundError:
            return False
        try:
            try:
                tmp_fd = self._open_subdir(root_fd, _TMP_DIR, create=False)
            except FileNotFoundError:
                return False
            try:
                try:
                    mode = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False).st_mode
                except FileNotFoundError:
                    return False
                if not stat.S_ISREG(mode):
                    raise StorageError("Caminho de storage inseguro.")
                try:
                    os.unlink(name, dir_fd=tmp_fd)
                except FileNotFoundError:
                    return False
                return True
            finally:
                os.close(tmp_fd)
        finally:
            os.close(root_fd)
