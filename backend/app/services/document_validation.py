"""Validação de uploads: nome, tipo e conteúdo (durante o streaming).

Tipos aceitos: .pdf, .txt, .md/.markdown. A extensão (do nome sanitizado)
define o mime_type gravado; o Content-Type do cliente nunca é gravado, só
rejeitado quando contradiz a extensão.
Arquivo vazio é rejeitado (InvalidDocumentError -> 422).
"""

from __future__ import annotations

import codecs
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.exceptions import InvalidDocumentError, UnsupportedDocumentTypeError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10_485_760
CHUNK_SIZE = 64 * 1024
MAX_FILENAME_LENGTH = 255

_EXTENSION_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}
# Content-Types do cliente compatíveis com cada mime canônico.
_COMPATIBLE_CLIENT_TYPES = {
    "application/pdf": {"application/pdf"},
    "text/plain": {"text/plain"},
    "text/markdown": {"text/markdown", "text/x-markdown", "text/plain"},
}
_NEUTRAL_CLIENT_TYPES = {"", "application/octet-stream"}
_PDF_MAGIC = b"%PDF-"


def sanitize_filename(raw: str | None) -> str:
    """Nome seguro para exibição/metadados (nunca usado como caminho)."""
    if not raw:
        raise InvalidDocumentError
    name = unicodedata.normalize("NFC", raw)
    # Cc controle, Cf formatação (bidi/zero-width), Cs surrogate, Co uso privado.
    name = "".join(ch for ch in name if unicodedata.category(ch) not in _DROP)
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name.strip(". "):
        raise InvalidDocumentError
    if len(name) > MAX_FILENAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: MAX_FILENAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_FILENAME_LENGTH]
    return name


_DROP = frozenset({"Cc", "Cf", "Cs", "Co"})


def resolve_mime_type(filename: str, client_content_type: str | None) -> str:
    """Mime canônico pela extensão; 415 se a extensão ou o tipo do cliente não servem."""
    dot = filename.rfind(".")
    extension = filename[dot:].lower() if dot >= 0 else ""
    mime = _EXTENSION_MIME.get(extension)
    if mime is None:
        raise UnsupportedDocumentTypeError
    declared = (client_content_type or "").split(";", 1)[0].strip().lower()
    if declared not in _NEUTRAL_CLIENT_TYPES and (
        declared not in _COMPATIBLE_CLIENT_TYPES[mime]
    ):
        raise UnsupportedDocumentTypeError
    return mime


class ContentChecker:
    """Verifica o conteúdo bloco a bloco, sem acumular o arquivo em memória."""

    def __init__(self, mime_type: str) -> None:
        self._is_pdf = mime_type == "application/pdf"
        self._head = bytearray()
        self._total = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def feed(self, chunk: bytes) -> None:
        self._total += len(chunk)
        if self._is_pdf:
            if len(self._head) < len(_PDF_MAGIC):
                self._head += chunk[: len(_PDF_MAGIC) - len(self._head)]
                if len(self._head) >= len(_PDF_MAGIC) and (
                    bytes(self._head) != _PDF_MAGIC
                ):
                    raise InvalidDocumentError
            return
        if b"\x00" in chunk:
            raise InvalidDocumentError
        try:
            # Incremental: sequências multibyte cortadas entre blocos são ok.
            self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError from exc

    def finish(self) -> None:
        if self._total == 0:
            raise InvalidDocumentError
        if self._is_pdf:
            if bytes(self._head) != _PDF_MAGIC:
                raise InvalidDocumentError
            return
        try:
            self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise InvalidDocumentError from exc


async def validated_chunks(
    read: Callable[[int], Awaitable[bytes]], mime_type: str
) -> AsyncIterator[bytes]:
    """Lê em blocos, valida e repassa; levanta InvalidDocumentError ao final se falhar."""
    checker = ContentChecker(mime_type)
    while chunk := await read(CHUNK_SIZE):
        checker.feed(chunk)
        yield chunk
    checker.finish()
