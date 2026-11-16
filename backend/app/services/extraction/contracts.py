from dataclasses import dataclass

_INVISIBLE_FORMATTING_CHARS = "\ufeff\u200b\u200c\u200d\u2060"
_INVISIBLE_FORMATTING_TABLE = str.maketrans("", "", _INVISIBLE_FORMATTING_CHARS)


def has_useful_content(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return value.translate(_INVISIBLE_FORMATTING_TABLE).strip() != ""


@dataclass(frozen=True, slots=True)
class TextSegment:
    text: str
    page_number: int | None

    def __post_init__(self) -> None:
        if not has_useful_content(self.text):
            raise ValueError("text must contain useful content")
        if self.page_number is None:
            return
        if isinstance(self.page_number, bool) or not isinstance(self.page_number, int):
            raise ValueError("page_number must be a positive integer or None")
        if self.page_number <= 0:
            raise ValueError("page_number must be a positive integer or None")


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    segments: tuple[TextSegment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.segments, tuple) or not self.segments:
            raise ValueError("segments must be a non-empty tuple")
        if any(not isinstance(segment, TextSegment) for segment in self.segments):
            raise ValueError("segments must contain only TextSegment items")
