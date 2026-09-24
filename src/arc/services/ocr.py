"""Optical character recognition for Company Brain ingestion (issue #299).

This is the piece `document_extraction` refused to guess at. PDF, DOCX
and plain text shipped first; images and scanned PDFs were refused with a
message naming OCR as the missing capability, because the blocker was
never a missing library. It was this question:

    **Where does a customer's document go to be read?**

A hosted OCR API answers it by sending the document out of the
deployment, which is a compliance posture Arc would be choosing on the
customer's behalf. That is the decision this module declines to make for
them.

So the provider that ships is **local**. Tesseract runs inside the
deployment; a scanned contract is read on the same machine that stored
it, and nothing crosses a network boundary that did not already exist.
Accuracy on hard inputs -- a photographed invoice at an angle,
handwriting -- is worse than a cloud engine's, and that is the honest
trade: worse text, no new place for tenant documents to be.

Three properties keep the choice reversible and quiet:

- **Off by default.** ``OCR_PROVIDER`` defaults to ``none``. A deployment
  that does not opt in behaves exactly as it did before, refusal message
  and all. Nobody silently gains OCR on upgrade.
- **Optional dependency.** Tesseract is a system binary, so it lives in
  the ``ocr`` extra rather than the base install. A deployment without it
  cannot half-enable this: the provider refuses to build and says why.
- **A protocol, not a library.** ``OcrProvider`` is the seam. A hosted or
  regional provider can be added here later as a deliberate, documented
  residency decision, without touching extraction.

Nothing here is a security boundary. OCR output is text from an
untrusted file, exactly like the text layer of an uploaded PDF, and it
goes through the same PII sanitization and the same ingestion path.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Protocol

logger = logging.getLogger("arc.ocr")

#: Recognition is CPU-bound and roughly linear in pages. Bounding it
#: keeps one upload from occupying a worker for minutes; a scan longer
#: than this is read as far as the bound and reported honestly rather
#: than truncated in silence.
DEFAULT_MAX_PAGES = 20

#: A hung child process is the failure mode a subprocess-backed engine
#: actually has. Without this the request thread waits forever.
DEFAULT_TIMEOUT_SECONDS = 30

#: Tesseract language packs to use. Each must be installed alongside the
#: binary; naming one that is not produces a controlled failure at build
#: time rather than empty text at upload time.
DEFAULT_LANGUAGES = "eng"


class OcrError(Exception):
    """Base class for controlled OCR failures."""


class OcrUnavailableError(OcrError):
    """OCR is configured but this deployment cannot run it.

    Distinct from "not configured": one means an operator asked for OCR
    and the deployment cannot deliver it, which is a misconfiguration
    worth reporting. The other is the default and is not an error.
    """


class OcrProvider(Protocol):
    """Turn image bytes into text.

    Implementations must be side-effect free and must not raise for
    ordinary "there was no text" -- an image of a blank page is an empty
    string, not a failure. Reserve exceptions for the engine being unable
    to run at all.
    """

    #: Identifies the engine in logs and in the upload response, so a
    #: reader can tell machine-read text from a document's own text layer.
    name: str

    def extract_text(self, image: bytes) -> str:
        """Return the text recognised in one image."""
        ...


class TesseractOcrProvider:
    """Local OCR through the Tesseract engine.

    Chosen because it runs where Arc runs. The document is read by the
    same deployment that stores it, so enabling OCR adds no destination
    for tenant content and needs no per-tenant residency configuration.
    """

    name = "tesseract"

    def __init__(
        self,
        languages: str = DEFAULT_LANGUAGES,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._languages = languages
        self._timeout = timeout_seconds
        # Imported at construction, not at call time: a deployment that
        # asked for OCR and cannot run it should fail at startup with a
        # clear reason, not on a user's upload an hour later.
        try:
            import pytesseract
            from PIL import Image  # noqa: F401 -- presence check
        except ImportError as exc:
            raise OcrUnavailableError(
                "OCR is configured as 'tesseract' but the ocr extra is not "
                "installed. Install arc[ocr] (pytesseract and Pillow)."
            ) from exc

        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise OcrUnavailableError(
                "OCR is configured as 'tesseract' but the tesseract binary "
                "is not on PATH. Install it (for example 'apt-get install "
                "tesseract-ocr') or set OCR_PROVIDER=none."
            ) from exc

    def extract_text(self, image: bytes) -> str:
        import io

        import pytesseract
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(image)) as handle:
                # Tesseract wants a decoded raster; converting here also
                # normalises the exotic modes (palette, CMYK) that make it
                # return nothing at all.
                return pytesseract.image_to_string(
                    handle.convert("L"),
                    lang=self._languages,
                    timeout=self._timeout,
                )
        except UnidentifiedImageError:
            # Not a readable image. Empty text, not an error: the caller
            # decides what "nothing came back" means for the document.
            logger.debug("ocr_skipped_unreadable_image")
            return ""
        except RuntimeError as exc:
            # pytesseract raises RuntimeError on its own timeout.
            raise OcrError("OCR timed out reading an image") from exc
        except Exception as exc:
            raise OcrError("OCR failed to read an image") from exc


def get_ocr_settings() -> dict:
    """Read OCR configuration from the environment."""
    return {
        "provider": (os.getenv("OCR_PROVIDER") or "none").strip().lower(),
        "languages": (os.getenv("OCR_LANGUAGES") or DEFAULT_LANGUAGES).strip(),
        "max_pages": _positive_int(os.getenv("OCR_MAX_PAGES"), DEFAULT_MAX_PAGES),
        "timeout_seconds": _positive_int(os.getenv("OCR_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT_SECONDS),
    }


def _positive_int(raw: Optional[str], default: int) -> int:
    """Parse a positive integer setting, falling back to the default."""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("ocr_setting_not_an_integer value=%r; using %d", raw, default)
        return default
    if value < 1:
        logger.warning("ocr_setting_not_positive value=%d; using %d", value, default)
        return default
    return value


def build_ocr_provider() -> Optional[OcrProvider]:
    """Build the configured OCR provider, or None when OCR is off.

    Returning None is the default and is not a failure: extraction then
    behaves exactly as it did before OCR existed, refusing images with a
    message that names OCR as the missing capability.

    A provider that is configured but cannot run raises
    :class:`OcrUnavailableError`, because that is an operator mistake and
    silently falling back to "no OCR" would hide it.
    """
    settings = get_ocr_settings()
    provider = settings["provider"]

    if provider in ("", "none", "off", "disabled"):
        return None

    if provider == "tesseract":
        built = TesseractOcrProvider(
            languages=settings["languages"],
            timeout_seconds=settings["timeout_seconds"],
        )
        logger.info(
            "ocr_enabled provider=tesseract languages=%s max_pages=%d",
            settings["languages"],
            settings["max_pages"],
        )
        return built

    raise OcrUnavailableError(
        f"OCR_PROVIDER={provider!r} is not a supported provider. "
        "Supported: 'none' (default), 'tesseract'."
    )
