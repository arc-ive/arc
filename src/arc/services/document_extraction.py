"""Text extraction from uploaded documents (issue #299).

Company Brain stores text. An enterprise knowledge base cannot depend on
someone pasting it, so this turns an uploaded file into the text the
existing ingestion path already knows how to chunk, embed and cite.

Two rules govern everything here:

**Nothing is accepted silently.** An unsupported format is refused with a
reason naming what Arc can actually read. A file that is accepted but
yields nothing is refused too: a knowledge document with no content is
worse than no document, because it retrieves as an empty citation and
looks like an answer.

**Format is decided by content, not by filename.** The declared
extension and content type are caller input. A ``.pdf`` that is really a
ZIP is not a PDF, and dispatching an extractor on a caller-supplied
string is how a parser gets handed something it was never meant to read.
The magic bytes decide; the filename is only used to produce a better
error message.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum
from typing import Optional

# 20 MB. Large enough for a real policy document with images, small
# enough that a single upload cannot exhaust a worker's memory during
# extraction. Enforced before any parser sees the bytes.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Extraction that produces less than this is treated as having failed.
# A scanned PDF with no text layer typically yields a handful of stray
# characters; accepting it would store an empty document that retrieves
# as a citation with nothing behind it.
MIN_EXTRACTED_CHARS = 20


class DocumentFormat(str, Enum):
    """Formats Arc can read."""

    TEXT = "text"
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"


class ExtractionError(Exception):
    """Base class for controlled extraction failures."""


class UnsupportedFormatError(ExtractionError):
    """The file is not a format Arc can read."""


class FileTooLargeError(ExtractionError):
    """The file exceeds MAX_UPLOAD_BYTES."""


class EmptyExtractionError(ExtractionError):
    """The file was read but yielded no usable text."""


class ExtractionUnavailableError(ExtractionError):
    """The extractor for this format is not installed.

    Distinct from UnsupportedFormatError on purpose: one means Arc will
    never read this, the other means this deployment currently cannot.
    Collapsing them would tell an operator to stop trying when the real
    answer is to install a dependency.
    """


@dataclass(frozen=True)
class ExtractedDocument:
    """Text recovered from an upload, with how it was recovered."""

    text: str
    detected_format: DocumentFormat
    char_count: int


def detect_format(data: bytes, filename: Optional[str] = None) -> DocumentFormat:
    """Identify the format from the bytes themselves.

    The filename is deliberately not trusted for dispatch. It is consulted
    only to distinguish markdown from plain text, where the distinction
    carries no parsing risk because both are read as text.
    """
    if data.startswith(b"%PDF-"):
        return DocumentFormat.PDF

    # DOCX is a ZIP container. Checking for the word/ part distinguishes
    # it from any other ZIP, so a renamed archive is refused rather than
    # handed to the DOCX parser.
    if data.startswith(b"PK\x03\x04"):
        if b"word/" in data[:4096] or _zip_contains_word_part(data):
            return DocumentFormat.DOCX
        raise UnsupportedFormatError("This looks like a ZIP archive rather than a Word document.")

    if _looks_like_image(data):
        raise UnsupportedFormatError(
            "Arc cannot read images yet. Optical character recognition is "
            "not configured, so an image would be stored with no readable "
            "content. Supported formats: plain text, Markdown, PDF, Word."
        )

    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise UnsupportedFormatError(
            "This file is not a format Arc can read. Supported formats: "
            "plain text, Markdown, PDF, Word."
        )

    if filename and filename.lower().endswith((".md", ".markdown")):
        return DocumentFormat.MARKDOWN
    return DocumentFormat.TEXT


def _zip_contains_word_part(data: bytes) -> bool:
    """Confirm a ZIP is a Word document by reading its entry names."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return any(name.startswith("word/") for name in archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def _looks_like_image(data: bytes) -> bool:
    """Recognise the common image containers by signature."""
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")  # JPEG
        or data.startswith(b"GIF87a")
        or data.startswith(b"GIF89a")
        or data.startswith(b"BM")  # BMP
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def extract(data: bytes, filename: Optional[str] = None) -> ExtractedDocument:
    """Return the text of an uploaded document.

    Raises a controlled ExtractionError subclass for every failure; a
    parser exception never escapes as a 500.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileTooLargeError(
            f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."
        )
    if not data:
        raise EmptyExtractionError("The file is empty.")

    detected = detect_format(data, filename)

    if detected in (DocumentFormat.TEXT, DocumentFormat.MARKDOWN):
        text = data.decode("utf-8")
    elif detected is DocumentFormat.PDF:
        text = _extract_pdf(data)
    else:
        text = _extract_docx(data)

    text = text.strip()
    if len(text) < MIN_EXTRACTED_CHARS:
        raise EmptyExtractionError(
            "No readable text could be extracted. If this is a scanned "
            "document, it has no text layer and would need optical "
            "character recognition, which is not configured."
        )

    return ExtractedDocument(text=text, detected_format=detected, char_count=len(text))


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractionUnavailableError("PDF extraction is not available in this deployment.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedFormatError("This PDF is password protected and cannot be read.")
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except UnsupportedFormatError:
        raise
    except Exception as exc:
        # A malformed PDF is a controlled failure, not a server error.
        raise ExtractionError("This PDF could not be read.") from exc


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        raise ExtractionUnavailableError("Word extraction is not available in this deployment.")

    try:
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        # Tables carry real content in policy documents -- a leave
        # entitlement table is exactly the fact someone will ask about --
        # and paragraph extraction alone silently drops them.
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception as exc:
        raise ExtractionError("This Word document could not be read.") from exc
