class ExtractionError(Exception):
    """Base error for document text extraction."""


class InvalidDocumentContentError(ExtractionError):
    """The document bytes are not valid for the requested extraction."""


class NoExtractableTextError(ExtractionError):
    """The document decoded successfully but contains no useful text."""
