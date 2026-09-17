"""Tests for post-authentication browser redirects using FRONTEND_URL.

After OIDC callback processing, the backend redirects the browser to the
frontend (which runs on a different origin in development). The redirect
URL must be built from the FRONTEND_URL environment variable.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arc.api.auth_routes import (
    _FRONTEND_URL_DEFAULT,
    _frontend_url,
    auth_router,
)


class TestFrontendUrlHelper:
    """Test the _frontend_url() helper."""

    def test_default_value(self):
        """Returns default when FRONTEND_URL is unset."""
        with patch.dict(os.environ, {}, clear=True):
            assert _frontend_url() == "http://localhost:5173"

    def test_default_constant_matches(self):
        """Default constant equals the expected development URL."""
        assert _FRONTEND_URL_DEFAULT == "http://localhost:5173"

    def test_returns_env_var_when_set(self):
        """Returns FRONTEND_URL from environment when set."""
        with patch.dict(os.environ, {"FRONTEND_URL": "https://app.example.com"}):
            assert _frontend_url() == "https://app.example.com"

    def test_returns_custom_dev_url(self):
        """Returns custom development URL when set."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:3000"}):
            assert _frontend_url() == "http://localhost:3000"

    def test_empty_string_returns_empty(self):
        """Empty FRONTEND_URL returns empty string (caller responsibility)."""
        with patch.dict(os.environ, {"FRONTEND_URL": ""}):
            assert _frontend_url() == ""


def _make_callback_app(google_service=None, session_service=None):
    """Create a test app with mocked services."""
    app = FastAPI()
    app.include_router(auth_router)
    app.state.google_oidc_service = google_service or MagicMock()
    app.state.session_service = session_service or MagicMock()
    return app


def _make_client(app):
    """Create a TestClient that does not follow redirects to external origins."""
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _make_success_session():
    """Create a mock session for successful authentication."""
    session = MagicMock()
    session.id = "test-session-id"
    session.csrf_token = "test-csrf-token"
    session.created_at = datetime.now(timezone.utc)
    session.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    return session


def _setup_google_service_for_success():
    """Set up a Google service mock that succeeds through the full flow."""
    google_service = MagicMock()
    google_service.exchange_code = AsyncMock(return_value={"id_token": "mock-id-token"})
    google_service.verify_id_token = AsyncMock(
        return_value=MagicMock(sub="google-sub", email="user@example.com")
    )
    google_service.find_or_link_user = AsyncMock(return_value=MagicMock(id="user-123"))
    return google_service


def _setup_session_service_for_success():
    """Set up a session service mock that creates a session."""
    session_service = MagicMock()
    session_service.create_session = AsyncMock(return_value=_make_success_session())
    return session_service


class TestSuccessRedirect:
    """Test the redirect URL after successful authentication."""

    def test_success_redirects_to_frontend_app(self):
        """Successful callback redirects to {FRONTEND_URL}/app."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            app = _make_callback_app(
                _setup_google_service_for_success(),
                _setup_session_service_for_success(),
            )
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert response.headers["location"] == "http://localhost:5173/app"

    def test_success_redirects_to_custom_frontend(self):
        """Successful callback uses custom FRONTEND_URL."""
        with patch.dict(os.environ, {"FRONTEND_URL": "https://app.example.com"}):
            app = _make_callback_app(
                _setup_google_service_for_success(),
                _setup_session_service_for_success(),
            )
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert response.headers["location"] == "https://app.example.com/app"


class TestAccessDeniedRedirect:
    """Test the redirect URL when Google identity is not linked."""

    def test_access_denied_redirects_to_frontend_login(self):
        """Unlinked identity redirects to {FRONTEND_URL}/login?error=access_denied."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(return_value={"id_token": "mock-id-token"})
            google_service.verify_id_token = AsyncMock(
                return_value=MagicMock(sub="unknown-sub", email="unknown@example.com")
            )
            google_service.find_or_link_user = AsyncMock(return_value=None)

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert response.headers["location"] == "http://localhost:5173/login?error=access_denied"

    def test_access_denied_uses_custom_frontend(self):
        """Unlinked identity uses custom FRONTEND_URL."""
        with patch.dict(os.environ, {"FRONTEND_URL": "https://app.example.com"}):
            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(return_value={"id_token": "mock-id-token"})
            google_service.verify_id_token = AsyncMock(
                return_value=MagicMock(sub="unknown-sub", email="unknown@example.com")
            )
            google_service.find_or_link_user = AsyncMock(return_value=None)

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert (
                response.headers["location"] == "https://app.example.com/login?error=access_denied"
            )


class TestAuthFailedRedirect:
    """Test the redirect URL when Google token exchange/verification fails."""

    def test_auth_failed_redirects_to_frontend_login(self):
        """GoogleAuthError redirects to {FRONTEND_URL}/login?error=auth_failed."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            from arc.security.google import GoogleAuthError

            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(
                side_effect=GoogleAuthError("Token exchange failed")
            )

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert response.headers["location"] == "http://localhost:5173/login?error=auth_failed"

    def test_auth_failed_uses_custom_frontend(self):
        """GoogleAuthError uses custom FRONTEND_URL."""
        with patch.dict(os.environ, {"FRONTEND_URL": "https://app.example.com"}):
            from arc.security.google import GoogleAuthError

            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(
                side_effect=GoogleAuthError("Token exchange failed")
            )

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            assert response.status_code == 302
            assert response.headers["location"] == "https://app.example.com/login?error=auth_failed"


class TestErrorQueryParamEncoding:
    """Test that error query parameters are preserved correctly."""

    def test_access_denied_error_value_preserved(self):
        """The access_denied error value is not mangled by URL encoding."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(return_value={"id_token": "mock-id-token"})
            google_service.verify_id_token = AsyncMock(
                return_value=MagicMock(sub="sub", email="e@e.com")
            )
            google_service.find_or_link_user = AsyncMock(return_value=None)

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            location = response.headers["location"]
            assert "error=access_denied" in location
            assert "%3D" not in location.split("error=")[1].split("&")[0]

    def test_auth_failed_error_value_preserved(self):
        """The auth_failed error value is not mangled by URL encoding."""
        with patch.dict(os.environ, {"FRONTEND_URL": "http://localhost:5173"}):
            from arc.security.google import GoogleAuthError

            google_service = MagicMock()
            google_service.exchange_code = AsyncMock(side_effect=GoogleAuthError("fail"))

            app = _make_callback_app(google_service)
            client = _make_client(app)

            response = client.get(
                "/auth/callback",
                params={"code": "auth-code", "state": "state-value"},
                cookies={
                    "arc_oidc_state": "state-value",
                    "arc_oidc_nonce": "nonce-value",
                },
            )

            location = response.headers["location"]
            assert "error=auth_failed" in location
            assert "%3D" not in location.split("error=")[1].split("&")[0]
