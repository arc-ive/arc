"""API integration tests for platform capability management endpoints.

Tests the 6 endpoints under /platform/capabilities and
/tenants/{tenant_id}/capabilities against a real PostgreSQL database.
"""

import os
import uuid

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import Tenant
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.security.models import ApplicationRole

TEST_JWT_SECRET = "test-jwt-secret-0123456789-abcdef"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://arc:arc-dev-password@localhost:5432/arc",
)


def _unique(prefix: str) -> str:
    return f"cap-api-{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def platform_admin_authorization(client, authorization_override):
    """Set up a PLATFORM_ADMINISTRATOR authorization for test principal."""
    uid = _unique("admin")
    return authorization_override({uid: ApplicationRole.PLATFORM_ADMINISTRATOR}), uid


@pytest.fixture
def non_admin_authorization(client, authorization_override):
    """Set up a non-admin authorization (MEMBER only)."""
    uid = _unique("member")
    return authorization_override({uid: ApplicationRole.EMPLOYEE}), uid


@pytest.fixture
async def real_tenant():
    """Create a real tenant in the DB and clean up afterwards."""
    db = ArcDatabase(DATABASE_URL)
    await db.connect()
    repo = PostgreSQLTenantRepository(db)
    tenant_id = _unique("tenant")
    tenant = await repo.create(Tenant(id=tenant_id, name="Cap Test Tenant"))
    yield tenant_id
    await repo.delete(tenant.id)
    await db.disconnect()


class TestPlatformCapabilitiesAPI:
    def test_list_platform_capabilities_unauthenticated(self, client):
        resp = client.get("/platform/capabilities")
        assert resp.status_code == 401

    def test_list_platform_capabilities_non_admin(
        self, client, non_admin_authorization, make_token
    ):
        auth_svc, uid = non_admin_authorization
        token = make_token(uid)
        resp = client.get(
            "/platform/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_list_platform_capabilities_empty(
        self, client, platform_admin_authorization, make_token
    ):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        resp = client.get(
            "/platform/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Initially empty (no platform capabilities seeded)
        assert isinstance(data, list)

    def test_set_and_get_platform_capability(
        self, client, platform_admin_authorization, make_token
    ):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)

        # Enable skill_execution at platform level
        resp = client.put(
            "/platform/capabilities/skill_execution",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["capability_id"] == "skill_execution"
        assert data["enabled"] is True

        # Read it back
        resp = client.get(
            "/platform/capabilities/skill_execution",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_set_unknown_capability_returns_400(
        self, client, platform_admin_authorization, make_token
    ):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        resp = client.put(
            "/platform/capabilities/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True},
        )
        assert resp.status_code == 400

    def test_get_unknown_capability_returns_404(
        self, client, platform_admin_authorization, make_token
    ):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        resp = client.get(
            "/platform/capabilities/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_list_after_set_shows_all_four(self, client, platform_admin_authorization, make_token):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)

        for cap_id in ["skill_execution", "tool_execution", "agent_execution", "connector_sync"]:
            client.put(
                f"/platform/capabilities/{cap_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"enabled": True},
            )

        resp = client.get(
            "/platform/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        ids = {d["capability_id"] for d in data}
        assert ids == {"skill_execution", "tool_execution", "agent_execution", "connector_sync"}


class TestTenantCapabilitiesAPI:
    def _seed_platform(self, client, token, capability_id, enabled=True):
        client.put(
            f"/platform/capabilities/{capability_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": enabled},
        )

    def test_list_tenant_capabilities(self, client, platform_admin_authorization, make_token):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        tenant_id = _unique("tenant")

        self._seed_platform(client, token, "skill_execution", True)

        resp = client.get(
            f"/tenants/{tenant_id}/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        skill_cap = [d for d in data if d["capability_id"] == "skill_execution"]
        assert len(skill_cap) == 1
        assert (
            skill_cap[0]["effective_enabled"] is True
        )  # platform enabled, tenant absent -> enabled

    def test_set_and_get_tenant_capability(
        self, client, platform_admin_authorization, make_token, real_tenant
    ):
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        tenant_id = real_tenant

        self._seed_platform(client, token, "tool_execution", True)

        # Enable for tenant
        resp = client.put(
            f"/tenants/{tenant_id}/capabilities/tool_execution",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["effective_enabled"] is True

        # Read it back
        resp = client.get(
            f"/tenants/{tenant_id}/capabilities/tool_execution",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["effective_enabled"] is True

    def test_hard_ceiling_enforced(
        self, client, platform_admin_authorization, make_token, real_tenant
    ):
        """Platform disabled -> DISABLED regardless of tenant config."""
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)
        tenant_id = real_tenant

        # Platform disabled
        self._seed_platform(client, token, "skill_execution", False)

        # Tenant enabled (attempt)
        resp = client.put(
            f"/tenants/{tenant_id}/capabilities/skill_execution",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Hard ceiling: effective is False even though tenant_enabled is True
        assert data["effective_enabled"] is False

    def test_tenant_non_admin_denied(self, client, non_admin_authorization, make_token):
        auth_svc, uid = non_admin_authorization
        token = make_token(uid)
        tenant_id = _unique("tenant")

        resp = client.get(
            f"/tenants/{tenant_id}/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_platform_capability_not_body_required(
        self, client, platform_admin_authorization, make_token
    ):
        """PUT /platform/capabilities/{id} requires enabled in body."""
        auth_svc, uid = platform_admin_authorization
        token = make_token(uid)

        resp = client.put(
            "/platform/capabilities/skill_execution",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert resp.status_code == 400
