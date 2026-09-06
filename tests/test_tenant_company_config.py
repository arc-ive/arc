"""API-level tests for tenant company configuration (Issue #70).

Covers authorization (401, 403 matrix), tenant boundary enforcement,
successful update with company config fields, field persistence, and
sensitive-material absence.
"""

import uuid

import pytest

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"cfg-{prefix}-{uuid.uuid4().hex[:8]}"


def _authed_request(http_client, method, url, token, json=None):
    kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
    if json is not None:
        kwargs["json"] = json
    return getattr(http_client, method)(url, **kwargs)


@pytest.fixture
async def seeded(db):
    """Provision a tenant, user, and membership for testing."""
    tenants = PostgreSQLTenantRepository(db)
    users = PostgreSQLUserRepository(db)
    memberships = PostgreSQLMembershipRepository(db)

    tenant_id = _unique("t")
    user_id = _unique("u")
    tenant = await tenants.create(Tenant(id=tenant_id, name="Config Test Tenant", status="active"))
    user = await users.create(
        User(id=user_id, email=f"{_unique('e')}@example.com", username="cfguser")
    )
    await memberships.create(
        Membership(
            id=_unique("m"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )
    yield tenant, user
    async with db._connection_pool.acquire() as conn:
        await conn.execute("DELETE FROM memberships WHERE tenant_id = $1", tenant.id)
        await conn.execute("DELETE FROM users WHERE id = $1", user.id)
        await conn.execute("DELETE FROM tenants WHERE id = $1", tenant.id)


class TestAuthenticationAndAuthorization:
    async def test_update_requires_authentication(self, client, seeded):
        tenant, _ = seeded
        response = client.put(f"/tenants/{tenant.id}", json={"name": "X"})
        assert response.status_code == 401

    async def test_employee_denied_update(self, client, seeded, make_token, authorization_override):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "X"})
        assert response.status_code == 403

    async def test_operations_user_denied_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "X"})
        assert response.status_code == 403

    async def test_company_administrator_allowed_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Updated Name"}
        )
        assert response.status_code == 200

    async def test_platform_administrator_allowed_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Updated Name"}
        )
        assert response.status_code == 200


class TestTenantBoundary:
    async def test_cross_tenant_update_denied(
        self, client, seeded, db, make_token, authorization_override
    ):
        tenant_a, user_a = seeded
        # Create a second tenant the user is NOT a member of
        tenants = PostgreSQLTenantRepository(db)
        tenant_b = await tenants.create(
            Tenant(id=_unique("b"), name="Other Tenant", status="active")
        )
        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user_a.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant_b.id}", token, {"name": "Hacked"}
        )
        assert response.status_code == 403
        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_b.id)


class TestUpdateCompanyConfig:
    async def test_update_persists_company_fields(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        payload = {
            "name": "Updated Tenant",
            "industry": "Healthcare",
            "address": "456 Hospital Ave",
            "phone": "+1-555-0200",
            "website": "https://health.example.com",
            "logo_url": "https://health.example.com/logo.png",
        }
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, payload)
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Updated Tenant"
        assert body["industry"] == "Healthcare"
        assert body["address"] == "456 Hospital Ave"
        assert body["phone"] == "+1-555-0200"
        assert body["website"] == "https://health.example.com"
        assert body["logo_url"] == "https://health.example.com/logo.png"

    async def test_update_returns_full_tenant_shape(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "Test"})
        body = response.json()
        assert set(body) == {
            "id",
            "name",
            "status",
            "industry",
            "address",
            "phone",
            "website",
            "logo_url",
            "created_at",
            "updated_at",
        }

    async def test_get_tenant_returns_company_fields(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # First update
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "Finance", "phone": "+1-555-0300"},
        )
        # Then GET
        response = _authed_request(client, "get", f"/tenants/{tenant.id}", token)
        assert response.status_code == 200
        body = response.json()
        assert body["industry"] == "Finance"
        assert body["phone"] == "+1-555-0300"

    async def test_update_preserves_existing_fields_when_not_provided(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # First update with full payload
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"name": "Full Update", "industry": "Tech", "phone": "123"},
        )
        # Second update with partial payload
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Partial Update"}
        )
        body = response.json()
        assert body["name"] == "Partial Update"
        assert body["industry"] == "Tech"
        assert body["phone"] == "123"

    async def test_update_clears_fields_with_empty_strings(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # Set fields
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "Tech", "phone": "123"},
        )
        # Clear fields
        response = _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "", "phone": ""},
        )
        body = response.json()
        assert body["industry"] == ""
        assert body["phone"] == ""
