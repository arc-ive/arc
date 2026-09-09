"""Tests for authentication routes.

Verifies Google OIDC flow, session management, and logout endpoints.
These tests verify the route logic without requiring the full app state.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arc.api.auth_routes import auth_router, _get_current_user, _set_session_cookie, _clear_session_cookie
from arc.security.google import GoogleOIDCService
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

    def test_auth_router_has_me_route(self):
        """Auth router has the /auth/me route."""
        routes = [route.path for route in auth_router.routes]
        assert "/auth/me" in routes

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
