"""Tests for upload text extraction (issue #299).

Company Brain stores text, so an upload has to become text before the
existing chunking, embedding and citation path can touch it. These cover
what is accepted, what is refused, and -- most importantly -- that
nothing is accepted silently.
"""

import io
import zipfile

import pytest

from arc.services.document_extraction import (
    MAX_UPLOAD_BYTES,
    DocumentFormat,
    EmptyExtractionError,
    ExtractionError,
    FileTooLargeError,
    UnsupportedFormatError,
    detect_format,
    extract,
)

LEAVE_POLICY = (
    "Every permanent employee receives 26 days of paid annual leave "
    "per year, in addition to UK public holidays."
)


def _pdf(text: str) -> bytes:
    """A minimal PDF carrying a real text layer, built without a library.

    Deliberately hand-built rather than pulling in reportlab: a test
    dependency whose only job is to produce a fixture is a dependency the
    deployment then has to justify. pypdf reads this exactly as it reads
    a generated one.
    """
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


def _docx(paragraphs, table_rows=None) -> bytes:
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, value in enumerate(row):
                table.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class TestFormatDetection:
    """Format comes from the bytes, never from the filename.

    A caller-supplied extension deciding which parser runs is how a
    parser gets handed something it was never meant to read.
    """

    def test_pdf_is_detected_by_signature(self):
        assert detect_format(b"%PDF-1.7\nrest") is DocumentFormat.PDF

    def test_a_pdf_named_txt_is_still_a_pdf(self):
        assert detect_format(b"%PDF-1.7\n", "notes.txt") is DocumentFormat.PDF

    def test_text_named_pdf_is_still_text(self):
        assert detect_format(b"just words", "report.pdf") is DocumentFormat.TEXT

    def test_markdown_is_distinguished_only_by_name(self):
        # Safe to trust the name here: both are read as text, so the
        # distinction carries no parsing risk.
        assert detect_format(b"# Title", "policy.md") is DocumentFormat.MARKDOWN
        assert detect_format(b"# Title", "policy.txt") is DocumentFormat.TEXT

    def test_a_plain_zip_is_not_a_word_document(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "hi")
        with pytest.raises(UnsupportedFormatError, match="ZIP archive"):
            detect_format(buffer.getvalue(), "policy.docx")


class TestRefusals:
    """Nothing is accepted silently."""

    def test_images_are_refused_and_say_why(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        with pytest.raises(UnsupportedFormatError) as exc:
            extract(png, "scan.png")
        # The message must name the real reason, not just "unsupported":
        # an operator needs to know OCR is the missing piece.
        assert "optical character recognition" in str(exc.value).lower()

    def test_binary_junk_is_refused(self):
        with pytest.raises(UnsupportedFormatError):
            extract(b"\x00\x01\x02\x03\xfe\xff" * 20, "mystery.bin")

    def test_oversized_files_are_refused_before_parsing(self):
        with pytest.raises(FileTooLargeError):
            extract(b"%PDF-1.7" + b"a" * (MAX_UPLOAD_BYTES + 1), "huge.pdf")

    def test_an_empty_file_is_refused(self):
        with pytest.raises(EmptyExtractionError):
            extract(b"", "empty.txt")

    def test_a_file_yielding_no_text_is_refused(self):
        """A stored document with no content retrieves as an empty
        citation and looks like an answer. Worse than no document."""
        with pytest.raises(EmptyExtractionError):
            extract(b"hi", "tiny.txt")

    def test_a_malformed_pdf_is_a_controlled_failure(self):
        """A parser exception must never escape as a 500."""
        with pytest.raises(ExtractionError):
            extract(b"%PDF-1.7\nnot actually a pdf at all" + b"\x00" * 200, "bad.pdf")


class TestExtraction:
    def test_plain_text_passes_through(self):
        result = extract(LEAVE_POLICY.encode(), "leave.txt")
        assert result.detected_format is DocumentFormat.TEXT
        assert "26 days" in result.text
        assert result.char_count == len(result.text)

    def test_markdown_keeps_its_content(self):
        source = f"# Leave Policy\n\n{LEAVE_POLICY}"
        result = extract(source.encode(), "leave.md")
        assert result.detected_format is DocumentFormat.MARKDOWN
        assert "26 days" in result.text

    def test_word_paragraphs_are_extracted(self):
        result = extract(_docx([LEAVE_POLICY]), "leave.docx")
        assert result.detected_format is DocumentFormat.DOCX
        assert "26 days" in result.text

    def test_word_tables_are_extracted(self):
        """Policy documents put entitlements in tables.

        Paragraph-only extraction silently drops them, so the fact
        someone will actually ask about is the fact that goes missing.
        """
        data = _docx(
            ["Notice required:"],
            table_rows=[["Length", "Notice"], ["3-10 days", "2 weeks"]],
        )
        result = extract(data, "notice.docx")
        assert "3-10 days" in result.text
        assert "2 weeks" in result.text

    def test_pdf_text_is_extracted(self):
        result = extract(_pdf(LEAVE_POLICY), "leave.pdf")
        assert result.detected_format is DocumentFormat.PDF
        assert "26 days" in result.text
