"""Main FastAPI application setup for Arc."""

import os

from fastapi import FastAPI

from arc.api.controllers import api_router
from arc.api.dev_controllers import dev_router
from arc.api.middleware import RequestTelemetryMiddleware

# Import app instance to register services
from arc.app import app as arc_app
from arc.observability_logging import configure_observability_logging

# Structured application logging (TRD 28): stdlib only, correlation-ID
# filter, safe metadata content policy. Installed once at import time.
configure_observability_logging()

# Create FastAPI application
app = FastAPI(
    title="Arc",
    description="Enterprise multi-tenant AI platform for IT Services organizations.",
    version="0.1.0",
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


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown application."""
    await arc_app.shutdown()
