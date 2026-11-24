from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from app.services.extraction.contracts import ExtractionResult, TextSegment
from app.services.extraction.exceptions import (
    InvalidDocumentContentError,
    NoExtractableTextError,
    PasswordProtectedDocumentError,
)


def extract_pdf_text(source: BinaryIO) -> ExtractionResult:
    try:
        reader = PdfReader(source)
    except PdfReadError as exc:
        raise InvalidDocumentContentError("document is not a valid PDF") from exc
    if reader.is_encrypted:
        raise PasswordProtectedDocumentError("document is password-protected")
    try:
        segments: list[TextSegment] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip() == "":
                continue
            segments.append(TextSegment(text=text, page_number=page_number))
    except FileNotDecryptedError as exc:
        raise PasswordProtectedDocumentError("document is password-protected") from exc
    except PdfReadError as exc:
        raise InvalidDocumentContentError("document is not a valid PDF") from exc
    if not segments:
        raise NoExtractableTextError("document has no extractable text")
    return ExtractionResult(segments=tuple(segments))
