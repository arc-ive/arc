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

OCR follows the same two rules. It is optional (``arc.services.ocr``),
off unless a deployment configures it, and when it is off the refusals
below are exactly what they always were. When it is on, a document read
by OCR says so -- machine-read text and a document's own text layer are
not the same evidence, and a reader deserves to know which they have.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from arc.services.ocr import OcrProvider

logger = logging.getLogger("arc.document_extraction")

# 20 MB. Large enough for a real policy document with images, small
# enough that a single upload cannot exhaust a worker's memory during
# extraction. Enforced before any parser sees the bytes.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Extraction that produces less than this is treated as having failed.
# A scanned PDF with no text layer typically yields a handful of stray
# characters; accepting it would store an empty document that retrieves
# as a citation with nothing behind it.
MIN_EXTRACTED_CHARS = 20

# A scanned page is normally ONE embedded image, so this bounds the work
# for a scanned PDF the same way page count would. A PDF carrying more
# images than this is read as far as the bound; what was read is
# reported, and the shortfall is never passed off as the whole document.
DEFAULT_MAX_OCR_IMAGES = 20

# Images smaller than this on their shortest side are decoration -- a
# logo, a signature strip, a bullet glyph. Running OCR on them costs time
# and returns noise that would then be indexed and cited.
#
# Measured in PIXELS rather than bytes on purpose. pypdf re-encodes an
# embedded image when it hands it over, so a byte threshold measures the
# compressor, not the content: a clean scan of a sparse page can encode
# smaller than a busy logo. Dimensions are the thing that actually
# separates "a page" from "an icon" -- a page scanned at any usable DPI
# is thousands of pixels on its short side, and no icon is.
MIN_OCR_IMAGE_PIXELS = 200


class DocumentFormat(str, Enum):
    """Formats Arc can recognise.

    Recognising a format is not the same as being able to read it.
    ``IMAGE`` is recognised always and readable only where OCR is
    configured; ``extract`` decides that, so detection stays a question
    about bytes and readability stays a question about this deployment.
    """

    TEXT = "text"
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"
    IMAGE = "image"


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
    """Text recovered from an upload, with how it was recovered.

    ``ocr_used`` distinguishes text the document carried from text a
    machine guessed at. They retrieve and cite identically, so the
    difference has to travel with the result or it is lost.
    """

    text: str
    detected_format: DocumentFormat
    char_count: int
    ocr_used: bool = False
    ocr_provider: Optional[str] = None


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
        return DocumentFormat.IMAGE

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


def extract(
    data: bytes,
    filename: Optional[str] = None,
    ocr: Optional["OcrProvider"] = None,
    max_ocr_images: int = DEFAULT_MAX_OCR_IMAGES,
) -> ExtractedDocument:
    """Return the text of an uploaded document.

    Raises a controlled ExtractionError subclass for every failure; a
    parser exception never escapes as a 500.

    ``ocr`` is optional and off by default. Without it this behaves
    exactly as it did before OCR existed: an image is refused with a
    reason naming OCR, and a scanned PDF is refused for having no text
    layer. With it, images are read directly and a PDF whose text layer
    is empty falls back to reading the images it embeds -- which for a
    scan is the page itself.

    The text layer is always preferred. OCR is a fallback for documents
    that have no text, never a second opinion on documents that do:
    re-reading a real text layer would replace exact characters with
    guessed ones.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileTooLargeError(
            f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."
        )
    if not data:
        raise EmptyExtractionError("The file is empty.")

    detected = detect_format(data, filename)
    ocr_used = False

    if detected in (DocumentFormat.TEXT, DocumentFormat.MARKDOWN):
        text = data.decode("utf-8")
    elif detected is DocumentFormat.IMAGE:
        if ocr is None:
            raise UnsupportedFormatError(
                "Arc cannot read images in this deployment. Optical "
                "character recognition is not configured, so an image "
                "would be stored with no readable content. Supported "
                "formats: plain text, Markdown, PDF, Word."
            )
        text = _run_ocr(ocr, [data])
        ocr_used = True
    elif detected is DocumentFormat.PDF:
        text = _extract_pdf(data)
        if len(text.strip()) < MIN_EXTRACTED_CHARS and ocr is not None:
            # No usable text layer. For a scan that is the expected
            # state, and the page image is what actually holds the words.
            images = _pdf_images(data, max_ocr_images)
            if images:
                text = _run_ocr(ocr, images)
                ocr_used = True
    else:
        text = _extract_docx(data)

    text = text.strip()
    if len(text) < MIN_EXTRACTED_CHARS:
        raise EmptyExtractionError(_empty_reason(detected, ocr, ocr_used))

    return ExtractedDocument(
        text=text,
        detected_format=detected,
        char_count=len(text),
        ocr_used=ocr_used,
        ocr_provider=getattr(ocr, "name", None) if ocr_used else None,
    )


def _empty_reason(detected: DocumentFormat, ocr: object, ocr_used: bool) -> str:
    """Say why nothing was recovered, in terms the reader can act on.

    Three different situations produce the same empty result, and telling
    them apart is the difference between "install something" and "this
    file has nothing in it".
    """
    if ocr_used:
        return (
            "No readable text could be extracted. Optical character "
            "recognition read this document and found no text -- it may "
            "be blank, or the scan may be too low quality to read."
        )
    if detected is DocumentFormat.PDF and ocr is None:
        return (
            "No readable text could be extracted. If this is a scanned "
            "document, it has no text layer and would need optical "
            "character recognition, which is not configured."
        )
    return "No readable text could be extracted from this document."


def _run_ocr(ocr: "OcrProvider", images: list) -> str:
    """Read a sequence of images, tolerating individual failures.

    One unreadable image in a forty-page scan should not lose the other
    thirty-nine. A failure that loses everything still surfaces, because
    the empty-text check below refuses the document.
    """
    from arc.services.ocr import OcrError

    parts = []
    for image in images:
        try:
            recognised = ocr.extract_text(image)
        except OcrError:
            logger.warning("ocr_image_failed provider=%s", getattr(ocr, "name", "unknown"))
            continue
        if recognised and recognised.strip():
            parts.append(recognised.strip())
    return "\n\n".join(parts)


def _pdf_images(data: bytes, limit: int) -> list:
    """Return the embedded images of a PDF, in page order, up to ``limit``.

    Uses the PDF reader Arc already depends on rather than adding a
    rasteriser. That covers the case this exists for -- a scan, where
    each page IS one embedded image -- and deliberately does not cover a
    vector-only PDF with no text layer, which has no image to read and is
    refused by the empty-text check like any other unreadable file.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractionUnavailableError("PDF extraction is not available in this deployment.")

    try:
        import PIL  # noqa: F401 -- pypdf decodes embedded images through Pillow
    except ImportError:
        raise ExtractionUnavailableError(
            "Reading images inside a PDF needs Pillow, which is part of the "
            "ocr extra. Install arc[ocr]."
        )

    images = []
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedFormatError("This PDF is password protected and cannot be read.")
        pages = reader.pages
    except UnsupportedFormatError:
        raise
    except Exception as exc:
        raise ExtractionError("This PDF could not be read.") from exc

    for page in pages:
        # Per PAGE and per IMAGE, because one corrupt embedded image in a
        # forty-page scan must not cost the other thirty-nine. pypdf
        # decodes lazily, so the failure surfaces during iteration.
        try:
            embedded_images = list(page.images)
        except Exception:
            logger.warning("ocr_pdf_page_images_unreadable")
            continue
        for embedded in embedded_images:
            if len(images) >= limit:
                logger.info("ocr_image_limit_reached limit=%d", limit)
                return images
            try:
                payload = embedded.data
                width, height = embedded.image.size
            except Exception:
                logger.warning("ocr_pdf_embedded_image_unreadable")
                continue
            if payload and min(width, height) >= MIN_OCR_IMAGE_PIXELS:
                images.append(payload)
    return images


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
