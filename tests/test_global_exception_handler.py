"""Tests for the global exception handler (Issue #113).

Verifies that unhandled exceptions return a generic 500 response without
leaking internal details, while preserving intentional HTTPException and
DuplicateKeyError behavior.
"""

import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from arc.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _register_test_routes():
    """Register temporary test routes, removed after each test."""

    @app.get("/test-unhandled-exception")
    async def _unhandled():
        raise RuntimeError("secret-db-password-123 file:///var/data/credentials")

    @app.get("/test-value-error")
    async def _value_error():
        raise ValueError("internal-sql-constraint-details")

    @app.get("/test-http-exception")
    async def _http_exception():
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/test-http-exception-403")
    async def _http_exception_403():
        raise HTTPException(status_code=403, detail="Forbidden")

    yield

    # Remove test routes
    app.router.routes[:] = [
        r for r in app.router.routes if not getattr(r, "path", "").startswith("/test-")
    ]


def test_unhandled_exception_returns_500():
    """Unexpected exceptions return generic 500 to the client."""
    response = client.get("/test-unhandled-exception")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_unhandled_exception_hides_internal_details():
    """No internal details (class names, messages, paths) appear in response."""
    response = client.get("/test-unhandled-exception")
    body = response.text
    assert "RuntimeError" not in body
    assert "secret-db-password-123" not in body
    assert "file:///" not in body
    assert "credentials" not in body


def test_value_error_returns_500():
    """ValueError (non-HTTP) returns generic 500."""
    response = client.get("/test-value-error")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "sql-constraint" not in response.text


def test_http_exception_preserved():
    """Intentional HTTPException is not caught by the global handler."""
    response = client.get("/test-http-exception")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_http_exception_403_preserved():
    """Intentional 403 HTTPException is not caught by the global handler."""
    response = client.get("/test-http-exception-403")
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_unhandled_exception_logged_at_error(caplog):
    """Full traceback is logged at ERROR level for unhandled exceptions."""
    with caplog.at_level(logging.ERROR, logger="arc.main"):
        client.get("/test-unhandled-exception")

    assert "Unhandled exception on GET /test-unhandled-exception" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "secret-db-password-123" in caplog.text


def test_health_endpoint_unaffected():
    """Existing health endpoint continues to work."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
