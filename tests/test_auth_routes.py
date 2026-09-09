"""Tests for authentication routes.

Verifies Google OIDC flow, session management, and logout endpoints.
These tests verify the route logic without requiring the full app state.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arc.api.auth_routes import (
    _clear_session_cookie,
    _get_current_user,
    _set_session_cookie,
    auth_router,
)
from arc.security.session import SessionService


class TestSessionCookieHelpers:
    """Test session cookie helper functions."""

    def test_set_session_cookie_sets_correct_attributes(self):
        """Session cookie has correct security attributes."""
        response = MagicMock()
        _set_session_cookie(response, "test-session-id", max_age=86400)

        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["key"] == "arc_session"
        assert call_kwargs["value"] == "test-session-id"
        assert call_kwargs["max_age"] == 86400
        assert call_kwargs["httponly"] is True
        assert call_kwargs["secure"] is True
        assert call_kwargs["samesite"] == "lax"
        assert call_kwargs["path"] == "/"

    def test_clear_session_cookie_deletes_cookie(self):
        """Clearing session cookie deletes it with correct attributes."""
        response = MagicMock()
        _clear_session_cookie(response)

        response.delete_cookie.assert_called_once()
        call_kwargs = response.delete_cookie.call_args[1]
        assert call_kwargs["key"] == "arc_session"
        assert call_kwargs["httponly"] is True
        assert call_kwargs["secure"] is True
        assert call_kwargs["samesite"] == "lax"
        assert call_kwargs["path"] == "/"


class TestGetCurrentUser:
    """Test the _get_current_user helper."""

    async def test_returns_none_without_cookie(self):
        """Returns None when no session cookie is present."""
        request = MagicMock()
        request.cookies = {}

        result = await _get_current_user(request)

        assert result is None

    async def test_returns_none_for_invalid_session(self):
        """Returns None for invalid session ID."""
        request = MagicMock()
        request.cookies = {"arc_session": "invalid-session-id"}

        session_service = MagicMock(spec=SessionService)
        session_service.validate_session = AsyncMock(return_value=None)

        with patch("arc.api.auth_routes._get_session_service", return_value=session_service):
            result = await _get_current_user(request)

        assert result is None

    async def test_returns_user_for_valid_session(self):
        """Returns user for valid session."""
        from arc.domain.models import User

        request = MagicMock()
        request.cookies = {"arc_session": "valid-session-id"}

        mock_user = MagicMock(spec=User)
        mock_user.id = "user-123"

        session_service = MagicMock(spec=SessionService)
        session_service.validate_session = AsyncMock(return_value=mock_user)

        with patch("arc.api.auth_routes._get_session_service", return_value=session_service):
            result = await _get_current_user(request)

        assert result is not None
        assert result.id == "user-123"


class TestRouterSetup:
    """Test router setup and configuration."""

    def test_auth_router_has_correct_prefix(self):
        """Auth router has no prefix (routes are mounted with /auth)."""
        assert auth_router.prefix == "" or auth_router.prefix is None

    def test_auth_router_has_google_login_route(self):
        """Auth router has the Google login route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/google" in routes

    def test_auth_router_has_callback_route(self):
        """Auth router has the callback route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/callback" in routes

    def test_auth_router_has_workspaces_route(self):
        """Auth router has the workspaces route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/workspaces" in routes

    def test_auth_router_has_logout_route(self):
        """Auth router has the logout route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/logout" in routes

    def test_auth_router_has_logout_all_route(self):
        """Auth router has the logout-all route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/logout-all" in routes


class TestGoogleLoginUnconfigured:
    """Test /auth/google returns 503 when Google OIDC is not configured."""

    async def test_returns_503_when_google_service_is_none(self):
        """GET /auth/google returns 503 when Google OIDC service is not initialized."""
        app = FastAPI()
        app.include_router(auth_router)

        # Simulate startup where google_oidc_service is None
        app.state.google_oidc_service = None
        app.state.session_service = MagicMock()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/google")

        assert response.status_code == 503
        assert response.json()["detail"] == "Google authentication is not configured"


class TestCallbackStateValidation:
    """Test callback state parameter validation (F7)."""

    def _make_callback_app(self, google_service=None, session_service=None):
        """Create a test app with mocked services."""
        app = FastAPI()
        app.include_router(auth_router)
        app.state.google_oidc_service = google_service or MagicMock()
        app.state.session_service = session_service or MagicMock()
        return app

    def test_missing_state_cookie_rejected(self):
        """Callback with missing state cookie returns 400."""
        app = self._make_callback_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "state-from-google"},
        )
        assert response.status_code == 400

    def test_mismatched_state_rejected(self):
        """Callback with mismatched state returns 400."""
        app = self._make_callback_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "state-from-google"},
            cookies={"arc_oidc_state": "different-state"},
        )
        assert response.status_code == 400


class TestCallbackNonceValidation:
    """Test callback nonce validation — fail-closed (F6)."""

    def _make_callback_app(self, google_service=None, session_service=None):
        """Create a test app with mocked services."""
        app = FastAPI()
        app.include_router(auth_router)
        app.state.google_oidc_service = google_service or MagicMock()
        app.state.session_service = session_service or MagicMock()
        return app

    def test_missing_nonce_cookie_rejected(self):
        """Callback with matching state but missing nonce → MUST NOT succeed."""
        app = self._make_callback_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/auth/callback",
            params={"code": "auth-code", "state": "state-value"},
            cookies={"arc_oidc_state": "state-value"},
            # No arc_oidc_nonce cookie
        )
        assert response.status_code == 400

    def test_missing_code_rejected(self):
        """Callback with missing code returns 400."""
        app = self._make_callback_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/auth/callback",
            params={"state": "state-value"},
            cookies={"arc_oidc_state": "state-value"},
        )
        assert response.status_code == 400

    def test_error_param_rejected(self):
        """Callback with error param returns 400."""
        app = self._make_callback_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/auth/callback",
            params={"error": "access_denied", "state": "state-value"},
        )
        assert response.status_code == 400
