"""Tests for environment-aware cookie Secure attribute.

The Secure cookie attribute must be:
- False when APP_ENV=development (local HTTP cannot set Secure cookies)
- True otherwise (production, staging, or unset APP_ENV)

This applies to all cookies: session, CSRF, and OIDC state/nonce.
"""

import os
from unittest.mock import MagicMock, patch

from arc.api.auth_routes import (
    _clear_csrf_cookie,
    _clear_session_cookie,
    _cookie_secure,
    _set_csrf_cookie,
    _set_session_cookie,
)


class TestCookieSecureDerivation:
    """Test the _cookie_secure() helper."""

    def test_development_returns_false(self):
        """APP_ENV=development means Secure=False for local HTTP."""
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            assert _cookie_secure() is False

    def test_production_returns_true(self):
        """APP_ENV=production means Secure=True."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            assert _cookie_secure() is True

    def test_staging_returns_true(self):
        """APP_ENV=staging means Secure=True."""
        with patch.dict(os.environ, {"APP_ENV": "staging"}):
            assert _cookie_secure() is True

    def test_unset_returns_true(self):
        """Unset APP_ENV defaults to Secure=True (production-safe)."""
        with patch.dict(os.environ, {}, clear=True):
            assert _cookie_secure() is True

    def test_empty_string_returns_true(self):
        """Empty APP_ENV defaults to Secure=True (production-safe)."""
        with patch.dict(os.environ, {"APP_ENV": ""}):
            assert _cookie_secure() is True


class TestSessionCookieSecureAttribute:
    """Session cookie uses _cookie_secure() for the Secure attribute."""

    def test_development_cookie_not_secure(self):
        """Session cookie is not Secure in development."""
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            response = MagicMock()
            _set_session_cookie(response, "sid", max_age=3600)
            call_kwargs = response.set_cookie.call_args[1]
            assert call_kwargs["secure"] is False

    def test_production_cookie_secure(self):
        """Session cookie is Secure in production."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = MagicMock()
            _set_session_cookie(response, "sid", max_age=3600)
            call_kwargs = response.set_cookie.call_args[1]
            assert call_kwargs["secure"] is True

    def test_unset_cookie_secure(self):
        """Session cookie is Secure when APP_ENV is unset."""
        with patch.dict(os.environ, {}, clear=True):
            response = MagicMock()
            _set_session_cookie(response, "sid", max_age=3600)
            call_kwargs = response.set_cookie.call_args[1]
            assert call_kwargs["secure"] is True


class TestCsrfCookieSecureAttribute:
    """CSRF cookie uses _cookie_secure() for the Secure attribute."""

    def test_development_cookie_not_secure(self):
        """CSRF cookie is not Secure in development."""
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            response = MagicMock()
            _set_csrf_cookie(response, "csrf-token", max_age=3600)
            call_kwargs = response.set_cookie.call_args[1]
            assert call_kwargs["secure"] is False

    def test_production_cookie_secure(self):
        """CSRF cookie is Secure in production."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = MagicMock()
            _set_csrf_cookie(response, "csrf-token", max_age=3600)
            call_kwargs = response.set_cookie.call_args[1]
            assert call_kwargs["secure"] is True


class TestClearCookieSecureAttribute:
    """Cookie deletion also uses _cookie_secure() for consistency."""

    def test_clear_session_development(self):
        """Clearing session cookie uses Secure=False in development."""
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            response = MagicMock()
            _clear_session_cookie(response)
            call_kwargs = response.delete_cookie.call_args[1]
            assert call_kwargs["secure"] is False

    def test_clear_session_production(self):
        """Clearing session cookie uses Secure=True in production."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = MagicMock()
            _clear_session_cookie(response)
            call_kwargs = response.delete_cookie.call_args[1]
            assert call_kwargs["secure"] is True

    def test_clear_csrf_development(self):
        """Clearing CSRF cookie uses Secure=False in development."""
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            response = MagicMock()
            _clear_csrf_cookie(response)
            call_kwargs = response.delete_cookie.call_args[1]
            assert call_kwargs["secure"] is False

    def test_clear_csrf_production(self):
        """Clearing CSRF cookie uses Secure=True in production."""
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            response = MagicMock()
            _clear_csrf_cookie(response)
            call_kwargs = response.delete_cookie.call_args[1]
            assert call_kwargs["secure"] is True


class TestOidcCookieAttributes:
    """OIDC state/nonce cookies in google_login respect _cookie_secure().

    These tests mock RedirectResponse to capture set_cookie calls
    made by the google_login handler.
    """

    def test_oidc_cookies_not_secure_in_development(self):
        """OIDC state and nonce cookies have Secure=False in development."""
        from arc.api.auth_routes import google_login

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            request = MagicMock()
            request.app.state.google_oidc_service = MagicMock()
            request.app.state.google_oidc_service.generate_state.return_value = "test-state"
            request.app.state.google_oidc_service.generate_nonce.return_value = "test-nonce"
            request.app.state.google_oidc_service.build_authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth"
            )

            mock_response = MagicMock()
            with patch("arc.api.auth_routes.RedirectResponse", return_value=mock_response):
                import asyncio

                asyncio.get_event_loop().run_until_complete(google_login(request))

            # Check state cookie
            state_call = mock_response.set_cookie.call_args_list[0]
            assert state_call[1]["key"] == "arc_oidc_state"
            assert state_call[1]["secure"] is False

            # Check nonce cookie
            nonce_call = mock_response.set_cookie.call_args_list[1]
            assert nonce_call[1]["key"] == "arc_oidc_nonce"
            assert nonce_call[1]["secure"] is False

    def test_oidc_cookies_secure_in_production(self):
        """OIDC state and nonce cookies have Secure=True in production."""
        from arc.api.auth_routes import google_login

        with patch.dict(os.environ, {"APP_ENV": "production"}):
            request = MagicMock()
            request.app.state.google_oidc_service = MagicMock()
            request.app.state.google_oidc_service.generate_state.return_value = "test-state"
            request.app.state.google_oidc_service.generate_nonce.return_value = "test-nonce"
            request.app.state.google_oidc_service.build_authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth"
            )

            mock_response = MagicMock()
            with patch("arc.api.auth_routes.RedirectResponse", return_value=mock_response):
                import asyncio

                asyncio.get_event_loop().run_until_complete(google_login(request))

            # Check state cookie
            state_call = mock_response.set_cookie.call_args_list[0]
            assert state_call[1]["key"] == "arc_oidc_state"
            assert state_call[1]["secure"] is True

            # Check nonce cookie
            nonce_call = mock_response.set_cookie.call_args_list[1]
            assert nonce_call[1]["key"] == "arc_oidc_nonce"
            assert nonce_call[1]["secure"] is True


class TestOtherAttributesUnchanged:
    """Verify that non-Secure cookie attributes are not affected."""

    def test_session_cookie_httponly_always_true(self):
        """Session cookie always has HttpOnly=True."""
        for env in ["development", "production"]:
            with patch.dict(os.environ, {"APP_ENV": env}):
                response = MagicMock()
                _set_session_cookie(response, "sid", max_age=3600)
                call_kwargs = response.set_cookie.call_args[1]
                assert call_kwargs["httponly"] is True

    def test_session_cookie_samesite_always_lax(self):
        """Session cookie always has SameSite=Lax."""
        for env in ["development", "production"]:
            with patch.dict(os.environ, {"APP_ENV": env}):
                response = MagicMock()
                _set_session_cookie(response, "sid", max_age=3600)
                call_kwargs = response.set_cookie.call_args[1]
                assert call_kwargs["samesite"] == "lax"

    def test_csrf_cookie_httponly_always_false(self):
        """CSRF cookie always has HttpOnly=False (JS needs to read it)."""
        for env in ["development", "production"]:
            with patch.dict(os.environ, {"APP_ENV": env}):
                response = MagicMock()
                _set_csrf_cookie(response, "csrf", max_age=3600)
                call_kwargs = response.set_cookie.call_args[1]
                assert call_kwargs["httponly"] is False

    def test_csrf_cookie_samesite_always_strict(self):
        """CSRF cookie always has SameSite=Strict."""
        for env in ["development", "production"]:
            with patch.dict(os.environ, {"APP_ENV": env}):
                response = MagicMock()
                _set_csrf_cookie(response, "csrf", max_age=3600)
                call_kwargs = response.set_cookie.call_args[1]
                assert call_kwargs["samesite"] == "strict"
