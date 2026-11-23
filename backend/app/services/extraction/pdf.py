from typing import BinaryIO

from pypdf import PdfReader

from app.services.extraction.contracts import ExtractionResult, TextSegment
from app.services.extraction.exceptions import NoExtractableTextError


def extract_pdf_text(source: BinaryIO) -> ExtractionResult:
    reader = PdfReader(source)
    segments: list[TextSegment] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip() == "":
            continue
        segments.append(TextSegment(text=text, page_number=page_number))
    if not segments:
        raise NoExtractableTextError("document has no extractable text")
    return ExtractionResult(segments=tuple(segments))
