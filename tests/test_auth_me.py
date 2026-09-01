"""``GET /auth/me`` tests: the authenticated user's authorized profile.

The endpoint is self-scoped: identity comes exclusively from the JWT
``sub``. It exposes the application role, the role's permission matrix,
and the persisted tenant memberships as INFORMATIONAL UX data. It must
never be a substitute for authorization — the backend re-checks every
protected request independently.
"""

import uuid

from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"me-{prefix}-{uuid.uuid4().hex[:10]}"


def test_me_requires_authentication(client):
    """Unauthenticated requests must produce a generic 401."""
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_without_role_assignment_returns_no_role_and_no_permissions(client, make_token):
    """An authenticated user without a role assignment is not special-cased."""
    token = make_token("unassigned-user")
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "unassigned-user"
    assert body["role"] is None
    assert body["permissions"] == []


async def test_me_reflects_assigned_role_permissions(client, make_token, authorization_override):
    """The returned permissions match the role's matrix from the backend."""
    user_id = _unique("admin")
    authorization_override({user_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(user_id)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["role"] == "platform_administrator"
    from arc.security.authorization import ROLE_PERMISSIONS

    expected = {
        permission.value
        for permission in ROLE_PERMISSIONS.get(ApplicationRole.PLATFORM_ADMINISTRATOR, frozenset())
    }
    assert set(body["permissions"]) == expected


async def test_me_reflects_employee_role_with_empty_permissions(
    client, make_token, authorization_override
):
    """EMPLOYEE is an explicit role with an intentionally empty matrix."""
    user_id = _unique("employee")
    authorization_override({user_id: ApplicationRole.EMPLOYEE})
    token = make_token(user_id)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["role"] == "employee"
    assert body["permissions"] == []


async def test_me_lists_persisted_memberships(
    client, repositories, seeded, make_token, authorization_override
):
    """Memberships are read from the persisted membership store."""
    tenant, user, membership = seeded
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user.id
    assert len(body["memberships"]) >= 1
    matching = [m for m in body["memberships"] if m["tenant_id"] == tenant.id]
    assert len(matching) == 1
    assert matching[0]["role"] == membership.role.value
