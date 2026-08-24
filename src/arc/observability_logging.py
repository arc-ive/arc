"""Structured application logging setup (TRD 28; approved decision).

stdlib logging only — no telemetry infrastructure dependency. Every line
carries the correlation ID via a filter (never from untrusted input):
request_id is minted by the request-telemetry middleware.

Log content policy: safe metadata only (correlation id, operation,
method, route template, status, duration, coarse error category).
NEVER logged: bodies, prompts, answers, tokens, credentials, secrets,
PII, raw query strings, or arbitrary user payload content.
"""

import logging
import os
from typing import Optional

from arc.api.correlation import request_id_var

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class RequestIdLogFilter(logging.Filter):
    """Inject the current correlation ID into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        value: Optional[str] = request_id_var.get()
        record.request_id = value if value else "-"
        return True


def configure_observability_logging() -> None:
    """Install the Arc root handler exactly once per process."""
    root = logging.getLogger()
    if any(getattr(handler, "_arc_observability", False) for handler in root.handlers):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s request_id=%(request_id)s"
        )
    )
    handler.addFilter(RequestIdLogFilter())
    handler._arc_observability = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel(level if level in _VALID_LEVELS else "INFO")
