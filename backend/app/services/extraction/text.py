from typing import BinaryIO

from app.services.extraction.contracts import (
    ExtractionResult,
    TextSegment,
    has_useful_content,
)
from app.services.extraction.exceptions import (
    InvalidDocumentContentError,
    NoExtractableTextError,
)


def extract_utf8_text(source: BinaryIO) -> ExtractionResult:
    raw = source.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidDocumentContentError("document is not valid UTF-8") from exc
    if not has_useful_content(text):
        raise NoExtractableTextError("document has no extractable text")
    return ExtractionResult(segments=(TextSegment(text=text, page_number=None),))
