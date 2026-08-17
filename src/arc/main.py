"""Main FastAPI application setup for Arc."""

from fastapi import FastAPI

from arc.api.controllers import api_router


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


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    await arc_app.initialize()


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown application."""
    await arc_app.shutdown()