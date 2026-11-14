from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextSegment:
    text: str
    page_number: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or self.text.strip() == "":
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
        if not isinstance(self.segments, tuple):
            raise ValueError("segments must be a tuple")
