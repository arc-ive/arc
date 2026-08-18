"""Main FastAPI application setup for Arc."""

import os

from fastapi import FastAPI

from arc.api.controllers import api_router
from arc.api.dev_controllers import dev_router

# Import app instance to register services
from arc.app import app as arc_app

# Create FastAPI application
app = FastAPI(
    title="Arc",
    description="Enterprise multi-tenant AI platform for IT Services organizations.",
    version="0.1.0",
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
