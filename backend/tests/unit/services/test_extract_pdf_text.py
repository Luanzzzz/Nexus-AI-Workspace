from io import BytesIO

import pytest

from app.services.extraction.contracts import ExtractionResult
from app.services.extraction.exceptions import NoExtractableTextError
from app.services.extraction.pdf import extract_pdf_text


def _assemble_pdf(object_bodies: list[bytes]) -> bytes:
    parts = [b"%PDF-1.4\n"]
    offsets: list[int] = []
    for index, body in enumerate(object_bodies, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_position = sum(len(part) for part in parts)
    xref = [
        b"xref\n",
        f"0 {len(object_bodies) + 1}\n".encode("ascii"),
        b"0000000000 65535 f \n",
    ]
    for offset in offsets:
        xref.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(object_bodies) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode("ascii")
    return b"".join(parts + xref + [trailer])


def _digital_pdf_with_page_text(text: str) -> BytesIO:
    escaped = (
        text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    )
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("ascii")
    pdf = _assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        ]
    )
    return BytesIO(pdf)


def test_extracts_text_from_single_page_digital_pdf() -> None:
    source = _digital_pdf_with_page_text("Nexus extraction sample")

    result = extract_pdf_text(source)

    assert isinstance(result, ExtractionResult)
    assert len(result.segments) == 1
    assert result.segments[0].page_number == 1
    assert "Nexus extraction sample" in result.segments[0].text


def _blank_page_pdf() -> BytesIO:
    pdf = _assemble_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << >> >>"
            ),
        ]
    )
    return BytesIO(pdf)


def test_rejects_pdf_with_no_extractable_text() -> None:
    with pytest.raises(NoExtractableTextError):
        extract_pdf_text(_blank_page_pdf())
