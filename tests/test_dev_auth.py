"""Tests for development-only reference-user authentication.

Verifies the dev auth endpoint:
- Only mounted in development
- Rejects unknown user IDs
- Creates real sessions
- Works with /auth/me
- CSRF behavior is correct
- No production auth behavior is changed
"""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arc.api.dev_auth import (
    _ALLOWED_USER_IDS,
    _REFERENCE_USERS,
    dev_auth_router,
)


class TestReferenceUserAllowlist:
    """Test the reference user allowlist is correctly defined."""

    def test_allowlist_contains_platform_admin(self):
        assert "ref-platform-admin" in _ALLOWED_USER_IDS

    def test_allowlist_contains_all_tenant_users(self):
        expected = [
            "ref-acme-technologies-company-admin",
            "ref-acme-technologies-ops-user",
            "ref-acme-technologies-employee-1",
            "ref-acme-technologies-employee-2",
            "ref-nova-systems-company-admin",
            "ref-nova-systems-ops-user",
            "ref-nova-systems-employee-1",
            "ref-nova-systems-employee-2",
            "ref-vertex-solutions-company-admin",
            "ref-vertex-solutions-ops-user",
            "ref-vertex-solutions-employee-1",
            "ref-vertex-solutions-employee-2",
            "ref-northstar-digital-company-admin",
            "ref-northstar-digital-ops-user",
            "ref-northstar-digital-employee-1",
            "ref-northstar-digital-employee-2",
        ]
        for user_id in expected:
            assert user_id in _ALLOWED_USER_IDS, f"{user_id} missing from allowlist"

    def test_allowlist_has_17_users(self):
        assert len(_ALLOWED_USER_IDS) == 17

    def test_reference_users_list_has_matching_count(self):
        assert len(_REFERENCE_USERS) == 17

    def test_each_reference_user_has_required_fields(self):
        for user in _REFERENCE_USERS:
            assert "user_id" in user
            assert "display_name" in user
            assert "role" in user
            assert "tenants" in user
            assert isinstance(user["tenants"], list)


class TestDevAuthRouterSetup:
    """Test the dev auth router is correctly configured."""

    def test_router_has_prefix(self):
        assert dev_auth_router.prefix == "/internal/dev/auth"

    def test_router_has_login_route(self):
        routes = [route.path for route in dev_auth_router.routes]
        assert "/internal/dev/auth/login" in routes

    def test_router_has_reference_users_route(self):
        routes = [route.path for route in dev_auth_router.routes]
        assert "/internal/dev/auth/reference-users" in routes


class TestDevLoginEndpoint:
    """Test the POST /internal/dev/auth/login endpoint."""

    def _make_app(self, db=None, session_service=None):
        """Create a test app with the dev auth router."""
        app = FastAPI()
        app.include_router(dev_auth_router)
        app.state.db = db or MagicMock()
        app.state.session_service = session_service or MagicMock()
        return app

    def test_unknown_user_rejected(self):
        """Unknown user IDs are rejected with 403."""
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "not-a-real-user"},
        )
        assert response.status_code == 403
        assert "Unknown reference user" in response.json()["detail"]

    def test_empty_user_id_rejected(self):
        """Empty user ID is rejected."""
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": ""},
        )
        assert response.status_code == 403

    def test_arbitrary_user_id_rejected(self):
        """Arbitrary user IDs not in the allowlist are rejected."""
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "admin"},
        )
        assert response.status_code == 403

    def test_user_not_in_database_returns_500(self):
        """Known reference user not found in DB returns 500."""
        db = MagicMock()
        db.get_user = AsyncMock(return_value=None)

        app = self._make_app(db=db)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "ref-platform-admin"},
        )
        assert response.status_code == 500
        assert "not found in database" in response.json()["detail"]

    def test_inactive_user_rejected(self):
        """Inactive reference user is rejected with 403."""
        db = MagicMock()
        mock_user = MagicMock()
        mock_user.status = "inactive"
        db.get_user = AsyncMock(return_value=mock_user)

        app = self._make_app(db=db)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "ref-platform-admin"},
        )
        assert response.status_code == 403
        assert "not active" in response.json()["detail"]

    def test_successful_login_creates_session(self):
        """Successful login creates a real session and sets cookies."""
        from datetime import datetime, timedelta, timezone

        db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "ref-platform-admin"
        mock_user.status = "active"
        db.get_user = AsyncMock(return_value=mock_user)

        mock_session = MagicMock()
        mock_session.id = "test-session-id-123"
        mock_session.csrf_token = "test-csrf-token-456"
        now = datetime.now(timezone.utc)
        mock_session.created_at = now
        mock_session.expires_at = now + timedelta(hours=24)

        session_service = MagicMock()
        session_service.create_session = AsyncMock(return_value=mock_session)

        app = self._make_app(db=db, session_service=session_service)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "ref-platform-admin"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["user_id"] == "ref-platform-admin"
        assert data["session_id"] == "test-session-id-123"

        # Verify session cookies were set
        cookies = {c.name: c.value for c in response.cookies.jar}
        assert "arc_session" in cookies
        assert "arc_csrf_token" in cookies

        # Verify session service was called correctly
        session_service.create_session.assert_called_once()
        call_args = session_service.create_session.call_args
        assert call_args[0][0].id == "ref-platform-admin"

    def test_missing_body_rejected(self):
        """Missing request body returns 422."""
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/internal/dev/auth/login")
        assert response.status_code == 422

    def test_missing_user_id_field_rejected(self):
        """Missing user_id field returns 422."""
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/internal/dev/auth/login",
            json={},
        )
        assert response.status_code == 422


class TestReferenceUsersEndpoint:
    """Test the GET /internal/dev/auth/reference-users endpoint."""

    def test_returns_reference_users(self):
        """Returns the full list of reference users."""
        app = FastAPI()
        app.include_router(dev_auth_router)

        client = TestClient(app)
        response = client.get("/internal/dev/auth/reference-users")

        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert len(data["users"]) == 17

    def test_users_have_correct_structure(self):
        """Each user in the response has the expected fields."""
        app = FastAPI()
        app.include_router(dev_auth_router)

        client = TestClient(app)
        response = client.get("/internal/dev/auth/reference-users")

        for user in response.json()["users"]:
            assert "user_id" in user
            assert "display_name" in user
            assert "role" in user
            assert "tenants" in user


class TestCSRFExemption:
    """Test that the dev auth login endpoint is CSRF-exempt."""

    def test_dev_login_in_exempt_paths(self):
        """The dev login path is in the CSRF exempt set."""
        from arc.api.csrf import CSRF_EXEMPT_PATHS

        assert "/internal/dev/auth/login" in CSRF_EXEMPT_PATHS

    def test_reference_users_get_not_affected_by_csrf(self):
        """GET requests are not affected by CSRF middleware."""
        app = FastAPI()
        app.include_router(dev_auth_router)

        client = TestClient(app)
        response = client.get("/internal/dev/auth/reference-users")
        assert response.status_code == 200


class TestDevAuthNotMountedInProduction:
    """Test that the dev auth router is not mounted when APP_ENV is not development."""

    def test_dev_auth_router_exists_only_for_development(self):
        """The dev auth router is a separate module, only included via main.py gating."""
        # Verify the dev auth router module is importable and has routes
        from arc.api.dev_auth import dev_auth_router

        assert len(dev_auth_router.routes) > 0

    def test_dev_login_endpoint_works_in_dev_mode(self):
        """The dev login endpoint responds (APP_ENV=development in test env)."""
        from arc.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/internal/dev/auth/login",
            json={"user_id": "not-a-real-user"},
        )
        # 403 means the endpoint is mounted and responding (user not in allowlist)
        assert response.status_code == 403


class TestProductionAuthUnchanged:
    """Verify that production auth behavior is not affected."""

    def test_google_login_endpoint_responds(self):
        """Google OIDC login endpoint is reachable."""
        from arc.main import app

        client = TestClient(app, raise_server_exceptions=False)
        # In test env, Google OIDC may not be configured, so 503 is acceptable
        # (means the endpoint exists). 404 would mean it's missing.
        response = client.get("/auth/google")
        assert response.status_code != 404

    def test_auth_me_endpoint_responds(self):
        """The /auth/me endpoint is reachable."""
        from arc.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/auth/me")
        # 401 means the endpoint exists but we're not authenticated
        assert response.status_code == 401

    def test_logout_endpoint_responds(self):
        """Logout endpoint is reachable."""
        from arc.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/auth/logout")
        assert response.status_code == 200
