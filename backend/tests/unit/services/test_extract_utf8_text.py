from io import BytesIO

import pytest

from app.services.extraction.exceptions import (
    InvalidDocumentContentError,
    NoExtractableTextError,
)
from app.services.extraction.text import extract_utf8_text


def test_preserves_valid_utf8_text() -> None:
    source = BytesIO(b"Linha um\nLinha dois\n")

    result = extract_utf8_text(source)

    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.text == "Linha um\nLinha dois\n"
    assert segment.page_number is None


def test_preserves_markdown_syntax() -> None:
    markdown = "# Título\n\n- item um\n- item dois\n"
    source = BytesIO(markdown.encode("utf-8"))

    result = extract_utf8_text(source)

    assert result.segments[0].text == markdown


def test_decodes_accented_characters() -> None:
    source = BytesIO("ação, coração".encode("utf-8"))

    result = extract_utf8_text(source)

    assert result.segments[0].text == "ação, coração"


def test_rejects_invalid_utf8_bytes() -> None:
    source = BytesIO(b"ok\xff")

    with pytest.raises(InvalidDocumentContentError):
        extract_utf8_text(source)


def test_rejects_empty_file() -> None:
    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(b""))


def test_rejects_whitespace_only_file() -> None:
    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(b" \n\t"))


def test_rejects_file_with_only_utf8_bom() -> None:
    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(b"\xef\xbb\xbf"))


def test_rejects_file_with_utf8_bom_and_whitespace() -> None:
    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(b"\xef\xbb\xbf \n\t"))


def test_strips_leading_utf8_bom_from_content() -> None:
    source = BytesIO("\ufeffconteúdo útil".encode("utf-8"))

    result = extract_utf8_text(source)

    assert result.segments[0].text == "conteúdo útil"
    assert not result.segments[0].text.startswith("\ufeff")


def test_rejects_invisible_formatting_only_file() -> None:
    payload = "\ufeff\u200b\u200c\u200d\u2060".encode("utf-8")

    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(payload))


def test_rejects_invisible_formatting_mixed_with_whitespace() -> None:
    payload = " \u200b\n\u200c\t\u200d\u2060\ufeff ".encode("utf-8")

    with pytest.raises(NoExtractableTextError):
        extract_utf8_text(BytesIO(payload))


def test_leaves_caller_stream_open() -> None:
    source = BytesIO(b"conteudo")

    extract_utf8_text(source)

    assert source.closed is False
    assert source.read() == b""
