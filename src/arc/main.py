"""Main FastAPI application setup for Arc."""

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from arc.api.controllers import api_router
from arc.api.dev_controllers import dev_router
from arc.api.middleware import RequestTelemetryMiddleware

# Import app instance to register services
from arc.app import app as arc_app
from arc.db.connection import DuplicateKeyError
from arc.observability_logging import configure_observability_logging
from arc.services.approval_sweep import ApprovalSweepRunner

logger = logging.getLogger(__name__)

# Structured application logging (TRD 28): stdlib only, correlation-ID
# filter, safe metadata content policy. Installed once at import time.
configure_observability_logging()

# Create FastAPI application
app = FastAPI(
    title="Arc",
    description="Enterprise multi-tenant AI platform for IT Services organizations.",
    version="0.1.0",
)


@app.exception_handler(DuplicateKeyError)
async def duplicate_key_error_handler(request: Request, exc: DuplicateKeyError):
    """Handle duplicate key errors as 409 Conflict responses."""
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unhandled exceptions.

    Preserves intentional HTTPException responses (4xx/5xx) by re-raising
    them for FastAPI's built-in handler. For all other exceptions, logs the
    full traceback server-side and returns a generic 500 to the client.
    Never exposes class names, messages, traceback, SQL details, filesystem
    paths, credentials, or other internal details.
    """
    if isinstance(exc, HTTPException):
        raise exc

    logger.error(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Observability-owned request correlation + best-effort HTTP telemetry.
# The service is resolved lazily per request so telemetry remains
# optional: until application startup completes, requests are still
# correlated via X-Request-ID but not persisted.
app.add_middleware(
    RequestTelemetryMiddleware,
    service_provider=lambda: arc_app.services.get("observability_service"),
)

# Include API router
app.include_router(api_router)

# Development-only endpoints (membership provisioning and tenant-context
# scaffolding) are mounted ONLY when APP_ENV is explicitly set to
# "development". Fail closed: an unset APP_ENV must never expose them.
# They are NOT protected application endpoints; X-11 will replace them
# with endpoints backed by an authenticated principal.
if os.getenv("APP_ENV") == "development":
    app.include_router(dev_router)


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    await arc_app.initialize()
    # Start the background approval expiry sweep (PRD §15)
    approval_service = arc_app.services.get("human_approval_service")
    if approval_service is not None:
        sweep_runner = ApprovalSweepRunner(approval_service)
        await sweep_runner.start()
        arc_app._sweep_runner = sweep_runner


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown application."""
    # Stop the approval sweep before closing the database
    sweep_runner = getattr(arc_app, "_sweep_runner", None)
    if sweep_runner is not None:
        await sweep_runner.stop()
    await arc_app.shutdown()
