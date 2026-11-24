from app.services.extraction.contracts import ExtractionResult, TextSegment
from app.services.extraction.exceptions import (
    ExtractionError,
    InvalidDocumentContentError,
    NoExtractableTextError,
    PasswordProtectedDocumentError,
)
from app.services.extraction.pdf import extract_pdf_text
from app.services.extraction.text import extract_utf8_text

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "InvalidDocumentContentError",
    "NoExtractableTextError",
    "PasswordProtectedDocumentError",
    "TextSegment",
    "extract_pdf_text",
    "extract_utf8_text",
]
