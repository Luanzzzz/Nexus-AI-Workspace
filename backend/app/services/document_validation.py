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


# Variation selectors (Mn, não Cf) mudam só a apresentação e servem para
# disfarçar nomes; zero-width e bidi já caem em Cf.
_VARIATION_SELECTORS = frozenset(
    [*range(0xFE00, 0xFE10), *range(0x180B, 0x180E), *range(0xE0100, 0xE01F0)]
)
_DROP = frozenset({"Cc", "Cf", "Cs", "Co"})
_MAX_EXTENSION_BYTES = 16


def _truncate_utf8(text: str, max_bytes: int) -> str:
    # Corta em fronteira de caractere: o decode descarta o byte parcial final.
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def sanitize_filename(raw: str | None) -> str:
    """Nome seguro para exibição/metadados (nunca usado como caminho).

    Usa NFC e não NFKC de propósito: NFKC reescreveria o nome do usuário
    (ligaduras, largura total, ordinais) e não resolve confusáveis entre
    scripts; como o nome nunca vira caminho, preserva-se o que o usuário enviou.
    """
    if not raw:
        raise InvalidDocumentError
    name = unicodedata.normalize("NFC", raw)
    # Cc controle, Cf formatação (bidi/zero-width), Cs surrogate, Co uso privado
    # e variation selectors são removidos.
    name = "".join(
        ch
        for ch in name
        if unicodedata.category(ch) not in _DROP and ord(ch) not in _VARIATION_SELECTORS
    )
    # Todo espaço Unicode (Zs, Zl, Zp, NBSP...) vira espaço simples, sem repetição.
    name = " ".join(name.split())
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name.strip(". "):
        raise InvalidDocumentError
    if len(name.encode("utf-8")) > MAX_FILENAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext.encode("utf-8")) <= _MAX_EXTENSION_BYTES:
            budget = MAX_FILENAME_LENGTH - len(ext.encode("utf-8")) - 1
            name = _truncate_utf8(stem, budget).rstrip(" .") + "." + ext
        else:
            name = _truncate_utf8(name, MAX_FILENAME_LENGTH).rstrip(" .")
        if not name.strip(". "):
            raise InvalidDocumentError
    return name


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
