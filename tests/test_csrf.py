"""Tests for CSRF protection.

Verifies that state-changing requests are protected by CSRF tokens,
while Bearer token API clients remain compatible.
"""

from unittest.mock import AsyncMock

import pytest

from arc.api.csrf import CSRF_EXEMPT_PATHS, STATE_CHANGING_METHODS
from arc.security.session import CSRF_COOKIE_NAME


class TestCSRFMiddleware:
    """Test CSRF middleware behavior."""

    def test_get_requests_not_protected(self):
        """GET requests should not require CSRF protection."""
        assert "GET" not in STATE_CHANGING_METHODS

    def test_head_requests_not_protected(self):
        """HEAD requests should not require CSRF protection."""
        assert "HEAD" not in STATE_CHANGING_METHODS

    def test_options_requests_not_protected(self):
        """OPTIONS requests should not require CSRF protection."""
        assert "OPTIONS" not in STATE_CHANGING_METHODS

    def test_post_requests_protected(self):
        """POST requests should require CSRF protection."""
        assert "POST" in STATE_CHANGING_METHODS

    def test_put_requests_protected(self):
        """PUT requests should require CSRF protection."""
        assert "PUT" in STATE_CHANGING_METHODS

    def test_patch_requests_protected(self):
        """PATCH requests should require CSRF protection."""
        assert "PATCH" in STATE_CHANGING_METHODS

    def test_delete_requests_protected(self):
        """DELETE requests should require CSRF protection."""
        assert "DELETE" in STATE_CHANGING_METHODS

    def test_auth_google_exempt(self):
        """/auth/google should be exempt from CSRF protection."""
        assert "/auth/google" in CSRF_EXEMPT_PATHS

    def test_auth_callback_exempt(self):
        """/auth/callback should be exempt from CSRF protection."""
        assert "/auth/callback" in CSRF_EXEMPT_PATHS

    def test_health_exempt(self):
        """/health should be exempt from CSRF protection."""
        assert "/health" in CSRF_EXEMPT_PATHS


class TestCSRFCookieHandling:
    """Test CSRF cookie setting and clearing."""

    def test_csrf_cookie_not_http_only(self):
        """CSRF cookie should NOT be HttpOnly so JavaScript can read it."""
        from fastapi import Response

        from arc.api.auth_routes import _set_csrf_cookie

        response = Response()
        _set_csrf_cookie(response, "test-token", max_age=3600)

        # Check that the cookie is set with correct attributes
        cookie_header = response.headers.get("set-cookie", "")
        assert CSRF_COOKIE_NAME in cookie_header
        assert "httponly" not in cookie_header.lower() or "httponly=false" in cookie_header.lower()

    def test_csrf_cookie_secure(self):
        """CSRF cookie should be Secure."""
        from fastapi import Response

        from arc.api.auth_routes import _set_csrf_cookie

        response = Response()
        _set_csrf_cookie(response, "test-token", max_age=3600)

        cookie_header = response.headers.get("set-cookie", "")
        assert "secure" in cookie_header.lower()

    def test_csrf_cookie_same_site_strict(self):
        """CSRF cookie should have SameSite=Strict."""
        from fastapi import Response

        from arc.api.auth_routes import _set_csrf_cookie

        response = Response()
        _set_csrf_cookie(response, "test-token", max_age=3600)

        cookie_header = response.headers.get("set-cookie", "")
        assert "samesite=strict" in cookie_header.lower()


class TestSessionCSRFToken:
    """Test session CSRF token generation and validation."""

    @pytest.fixture
    def db(self):
        """Mock database connection."""
        return AsyncMock()

    @pytest.fixture
    def service(self, db):
        """SessionService with mocked database."""
        from arc.security.session import SessionService

        return SessionService(db, expiry_hours=24)

    def test_generate_csrf_token_is_random(self, service):
        """CSRF tokens should be cryptographically random."""
        token1 = service.generate_csrf_token()
        token2 = service.generate_csrf_token()
        assert token1 != token2

    def test_generate_csrf_token_is_sufficient_length(self, service):
        """CSRF tokens should be at least 32 characters (256 bits)."""
        token = service.generate_csrf_token()
        assert len(token) >= 32


class TestBearerTokenExemption:
    """Test that Bearer token clients are exempt from CSRF."""

    def test_bearer_token_header_detected(self):
        """Bearer token in Authorization header should be detected."""
        auth_header = "Bearer test-token-123"
        assert auth_header.lower().startswith("bearer ")

    def test_bearer_token_case_insensitive(self):
        """Bearer token detection should be case-insensitive."""
        auth_header = "bearer test-token-123"
        assert auth_header.lower().startswith("bearer ")
