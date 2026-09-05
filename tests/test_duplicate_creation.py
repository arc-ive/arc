"""Regression tests for DuplicateKeyError handling on resource creation.

Issue #76: Creating a tenant, user, or skill with a duplicate ID/name
should return HTTP 409 Conflict instead of HTTP 500.
"""

import uuid

from arc.security.authorization import ApplicationRole


def _unique(prefix: str) -> str:
    return f"dup-{prefix}-{uuid.uuid4().hex[:10]}"


class TestDuplicateTenantCreation:
    """POST /tenants with duplicate ID returns 409."""

    async def test_duplicate_tenant_id_returns_409(
        self, client, make_token, authorization_override
    ):
        user_id = _unique("admin")
        authorization_override({user_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user_id)

        # Create the user first so FK constraint is satisfied when OWNER membership is created
        user_resp = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": user_id, "email": f"{user_id}@example.com", "username": user_id},
        )
        assert user_resp.status_code == 200

        tenant_id = _unique("tenant")

        first = client.post(
            "/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": tenant_id, "name": "First Tenant"},
        )
        assert first.status_code == 200

        second = client.post(
            "/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": tenant_id, "name": "Duplicate Tenant"},
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()

    async def test_different_tenant_ids_succeed(self, client, make_token, authorization_override):
        user_id = _unique("admin")
        authorization_override({user_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user_id)

        # Create the user first so FK constraint is satisfied when OWNER membership is created
        user_resp = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": user_id, "email": f"{user_id}@example.com", "username": user_id},
        )
        assert user_resp.status_code == 200

        first = client.post(
            "/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("tenant"), "name": "First"},
        )
        assert first.status_code == 200

        second = client.post(
            "/tenants",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("tenant"), "name": "Second"},
        )
        assert second.status_code == 200


class TestDuplicateUserCreation:
    """POST /users with duplicate ID returns 409."""

    async def test_duplicate_user_id_returns_409(self, client, make_token, authorization_override):
        authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token("admin")

        user_id = _unique("user")

        first = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": user_id, "email": f"{user_id}@example.com"},
        )
        assert first.status_code == 200

        second = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": user_id, "email": f"other-{user_id}@example.com"},
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()

    async def test_duplicate_user_email_returns_409(
        self, client, make_token, authorization_override
    ):
        authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token("admin")

        email = f"dup-{uuid.uuid4().hex[:10]}@example.com"

        first = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("user"), "email": email},
        )
        assert first.status_code == 200

        second = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("user"), "email": email},
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()

    async def test_different_user_ids_succeed(self, client, make_token, authorization_override):
        authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token("admin")

        first = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("user"), "email": f"{_unique('user')}@example.com"},
        )
        assert first.status_code == 200

        second = client.post(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": _unique("user"), "email": f"{_unique('user')}@example.com"},
        )
        assert second.status_code == 200
