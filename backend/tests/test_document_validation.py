import pytest

from app.core.exceptions import InvalidDocumentError, UnsupportedDocumentTypeError
from app.services.document_validation import (
    ContentChecker,
    resolve_mime_type,
    sanitize_filename,
    validated_chunks,
)


def _check(mime: str, *chunks: bytes) -> None:
    checker = ContentChecker(mime)
    for chunk in chunks:
        checker.feed(chunk)
    checker.finish()


def test_pdf_header_accepted_even_when_split():
    _check("application/pdf", b"%P", b"DF", b"-1.7 resto")


@pytest.mark.parametrize("data", [b"<html>", b"%PDX-1", b"abc"])
def test_pdf_without_header_rejected(data):
    with pytest.raises(InvalidDocumentError):
        _check("application/pdf", data)


def test_utf8_split_across_chunks_is_accepted():
    encoded = "ação ✓".encode()
    # corta no meio de sequências multibyte
    _check("text/plain", encoded[:2], encoded[2:7], encoded[7:])


@pytest.mark.parametrize("data", [b"\xff\xfe\xfa", b"abc\x80", b"ol\xc3"])
def test_invalid_utf8_rejected(data):
    with pytest.raises(InvalidDocumentError):
        _check("text/markdown", data)


def test_nul_byte_rejected():
    with pytest.raises(InvalidDocumentError):
        _check("text/plain", b"ab\x00cd")


@pytest.mark.parametrize("mime", ["application/pdf", "text/plain"])
def test_empty_rejected(mime):
    with pytest.raises(InvalidDocumentError):
        _check(mime)


@pytest.mark.parametrize(
    ("name", "client", "mime"),
    [
        ("a.pdf", "application/pdf", "application/pdf"),
        ("A.PDF", None, "application/pdf"),
        ("a.txt", "text/plain; charset=utf-8", "text/plain"),
        ("a.md", "text/markdown", "text/markdown"),
        ("a.markdown", "application/octet-stream", "text/markdown"),
        ("a.md", "text/plain", "text/markdown"),
    ],
)
def test_mime_comes_from_extension(name, client, mime):
    assert resolve_mime_type(name, client) == mime


@pytest.mark.parametrize(
    ("name", "client"),
    [
        ("a.exe", "application/pdf"),
        ("semextensao", None),
        ("a.pdf", "text/plain"),
        ("a.txt", "application/pdf"),
    ],
)
def test_unsupported_or_mismatched_type(name, client):
    with pytest.raises(UnsupportedDocumentTypeError):
        resolve_mime_type(name, client)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("relatorio.pdf", "relatorio.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\x\\nota.md", "nota.md"),
        ("a\x00b\x1f.txt", "ab.txt"),
        ("  espaço.txt  ", "espaço.txt"),
        ("cafe\u0301.txt", "caf\u00e9.txt"),
        ("a\u202etxt.pdf", "atxt.pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "..", ".", "dir/", "\x00\x01", "a/.."]
)
def test_sanitize_filename_rejects_empty_result(raw):
    with pytest.raises(InvalidDocumentError):
        sanitize_filename(raw)


def test_sanitize_filename_limits_length_keeping_extension():
    result = sanitize_filename("x" * 400 + ".pdf")

    assert len(result) == 255
    assert result.endswith(".pdf")


@pytest.mark.asyncio
async def test_validated_chunks_raises_on_finish_for_bad_utf8():
    data = [b"abc", b"\xc3", b""]

    async def read(_size):
        return data.pop(0)

    seen = []
    with pytest.raises(InvalidDocumentError):
        async for chunk in validated_chunks(read, "text/plain"):
            seen.append(chunk)
    assert seen == [b"abc", b"\xc3"]
