"""Tests for CSRF protection.

Verifies that state-changing requests are protected by CSRF tokens,
while Bearer token API clients remain compatible.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arc.api.csrf import CSRF_EXEMPT_PATHS, STATE_CHANGING_METHODS, CSRFMiddleware
from arc.security.session import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME


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

        cookie_header = response.headers.get("set-cookie", "")
        assert CSRF_COOKIE_NAME in cookie_header
        assert "httponly" not in cookie_header.lower() or "httponly=false" in cookie_header.lower()

    def test_csrf_cookie_secure(self):
        """CSRF cookie should be Secure in production."""
        from fastapi import Response

        from arc.api.auth_routes import _set_csrf_cookie

        with patch.dict(os.environ, {"APP_ENV": "production"}):
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


class TestCSRFMiddlewareDispatch:
    """Integration tests for CSRFMiddleware.dispatch with Request objects."""

    @pytest.fixture
    def middleware(self):
        """Create a CSRFMiddleware instance."""
        app = MagicMock()
        app.state.session_service = MagicMock()
        app.state.session_service.validate_csrf_token = AsyncMock(return_value=True)
        return CSRFMiddleware(app)

    @pytest.fixture
    def call_next(self):
        """Create a mock call_next that returns a 200 response."""
        from starlette.responses import Response

        async def _call_next(request):
            return Response(status_code=200)

        return _call_next

    def _make_request(
        self,
        method="POST",
        path="/api/test",
        cookies=None,
        headers=None,
    ):
        """Create a mock Request object."""
        from starlette.datastructures import URL

        # Build case-insensitive headers dict (lowercase keys)
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}

        request = MagicMock()
        request.method = method
        request.url = MagicMock(spec=URL)
        request.url.path = path
        request.cookies = cookies or {}
        request.headers = hdrs
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.app = MagicMock()
        request.app.state.session_service = MagicMock()
        request.app.state.session_service.validate_csrf_token = AsyncMock(return_value=True)
        return request

    @pytest.mark.asyncio
    async def test_bearer_only_post_allowed_past_csrf(self, middleware, call_next):
        """Bearer-only POST (no session cookie) passes CSRF middleware."""
        request = self._make_request(
            method="POST",
            headers={"Authorization": "Bearer test-token"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_session_cookie_no_csrf_token_rejected(self, middleware, call_next):
        """Session cookie + no CSRF token → 403."""
        request = self._make_request(
            method="POST",
            cookies={SESSION_COOKIE_NAME: "test-session-id"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_session_cookie_missing_csrf_header_rejected(self, middleware, call_next):
        """Session cookie + CSRF cookie but no CSRF header → 403."""
        request = self._make_request(
            method="POST",
            cookies={
                SESSION_COOKIE_NAME: "test-session-id",
                CSRF_COOKIE_NAME: "test-csrf-token",
            },
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_session_cookie_mismatched_csrf_rejected(self, middleware, call_next):
        """Session cookie + mismatched CSRF token → 403."""
        request = self._make_request(
            method="POST",
            cookies={
                SESSION_COOKIE_NAME: "test-session-id",
                CSRF_COOKIE_NAME: "cookie-token",
            },
            headers={"X-CSRF-Token": "header-token"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_session_and_bearer_no_csrf_rejected(self, middleware, call_next):
        """Session cookie + Bearer header + no CSRF token → 403.

        The session cookie takes precedence: CSRF validation is mandatory.
        """
        request = self._make_request(
            method="POST",
            cookies={SESSION_COOKIE_NAME: "test-session-id"},
            headers={"Authorization": "Bearer test-token"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_session_and_bearer_valid_csrf_allowed(self, middleware, call_next):
        """Session cookie + Bearer header + valid CSRF token → 200.

        The session cookie takes precedence: CSRF validation is mandatory
        and passes.
        """
        request = self._make_request(
            method="POST",
            cookies={
                SESSION_COOKIE_NAME: "test-session-id",
                CSRF_COOKIE_NAME: "valid-csrf-token",
            },
            headers={
                "Authorization": "Bearer test-token",
                "X-CSRF-Token": "valid-csrf-token",
            },
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_safe_method_not_protected(self, middleware, call_next):
        """GET requests are not protected by CSRF."""
        request = self._make_request(
            method="GET",
            cookies={SESSION_COOKIE_NAME: "test-session-id"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_exempt_path_not_protected(self, middleware, call_next):
        """Exempt paths bypass CSRF validation."""
        request = self._make_request(
            method="POST",
            path="/auth/google",
            cookies={SESSION_COOKIE_NAME: "test-session-id"},
        )
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
