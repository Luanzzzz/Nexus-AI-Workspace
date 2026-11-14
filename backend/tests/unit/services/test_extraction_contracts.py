from dataclasses import FrozenInstanceError

import pytest

from app.services.extraction.contracts import ExtractionResult, TextSegment


def test_accepts_pdf_segment_with_page_one() -> None:
    segment = TextSegment(text="Conteúdo da página", page_number=1)

    assert segment.text == "Conteúdo da página"
    assert segment.page_number == 1


def test_accepts_txt_segment_without_page_number() -> None:
    segment = TextSegment(text="Conteúdo de texto", page_number=None)

    assert segment.page_number is None


def test_rejects_boolean_page_number() -> None:
    with pytest.raises(ValueError):
        TextSegment(text="Conteúdo válido", page_number=True)


def test_rejects_non_string_text() -> None:
    with pytest.raises(ValueError):
        TextSegment(text=None, page_number=1)  # type: ignore[arg-type]


def test_rejects_zero_page_number() -> None:
    with pytest.raises(ValueError):
        TextSegment(text="Conteúdo válido", page_number=0)


def test_rejects_negative_page_number() -> None:
    with pytest.raises(ValueError):
        TextSegment(
            text="Conteúdo válido",
            page_number=-1,
        )


def test_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        TextSegment(text="", page_number=1)


def test_rejects_whitespace_only_text() -> None:
    with pytest.raises(ValueError):
        TextSegment(text="   \n\t", page_number=None)


def test_text_segment_is_immutable() -> None:
    segment = TextSegment(text="Conteúdo válido", page_number=1)

    with pytest.raises(FrozenInstanceError):
        segment.text = "outro texto"  # type: ignore[misc]


def test_extraction_result_preserves_segment_order() -> None:
    first = TextSegment(text="Primeiro", page_number=1)
    second = TextSegment(text="Segundo", page_number=2)
    third = TextSegment(text="Terceiro", page_number=None)

    result = ExtractionResult(segments=(first, second, third))

    assert result.segments == (first, second, third)


def test_extraction_result_rejects_list_and_is_immutable() -> None:
    segment = TextSegment(text="Conteúdo válido", page_number=1)

    with pytest.raises(ValueError):
        ExtractionResult(segments=[segment])  # type: ignore[arg-type]

    result = ExtractionResult(segments=(segment,))

    with pytest.raises(FrozenInstanceError):
        result.segments = ()  # type: ignore[misc]
