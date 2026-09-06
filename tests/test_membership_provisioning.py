"""Tests for the production tenant membership provisioning endpoints.

Validates that:
- POST /tenants/{tenant_id}/memberships creates memberships
- DELETE /tenants/{tenant_id}/memberships/{user_id} removes memberships
- Both endpoints require membership:create permission (PLATFORM_ADMINISTRATOR)
- Duplicate memberships return 409
- Missing users/tenants return appropriate errors
"""

import uuid

from arc.domain.models import Tenant, User
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"memb-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="memb-user")
    )


async def _seed_tenant(repositories):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name="Memb Tenant"))


async def test_create_membership_requires_permission(
    client, repositories, make_token, authorization_override
):
    """Unauthenticated or unauthorized users cannot create memberships."""
    user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override({user.id: ApplicationRole.EMPLOYEE})
    token = make_token(user.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": user.id, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    tenant_repo, _, membership_repo = repositories
    _, user_repo, _ = repositories
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(user.id)


async def test_create_membership_success(
    client, repositories, make_token, authorization_override
):
    """Platform administrator can create a membership."""
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target_user.id, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == target_user.id
    assert body["tenant_id"] == tenant.id
    assert body["role"] == "member"
    assert "id" in body
    assert "created_at" in body

    tenant_repo, user_repo, membership_repo = repositories
    await membership_repo.delete(body["id"])
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(target_user.id)
    await user_repo.delete(admin.id)


async def test_create_membership_duplicate_returns_409(
    client, repositories, make_token, authorization_override, seeded
):
    """Creating a duplicate membership returns 409 Conflict."""
    tenant, user, membership = seeded
    admin = await _seed_user(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": user.id, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert "already belongs" in response.json()["detail"]

    _, user_repo, _ = repositories
    await user_repo.delete(admin.id)


async def test_create_membership_missing_user_returns_409(
    client, repositories, make_token, authorization_override
):
    """Creating a membership for a nonexistent user returns 409."""
    admin = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": "nonexistent-user", "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert "does not exist" in response.json()["detail"]

    tenant_repo, user_repo, _ = repositories
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(admin.id)


async def test_create_membership_missing_tenant_returns_409(
    client, repositories, make_token, authorization_override
):
    """Creating a membership in a nonexistent tenant returns 409."""
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        "/tenants/nonexistent-tenant/memberships",
        json={"user_id": target_user.id, "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert "does not exist" in response.json()["detail"]

    _, user_repo, _ = repositories
    await user_repo.delete(target_user.id)
    await user_repo.delete(admin.id)


async def test_create_membership_invalid_role_returns_400(
    client, repositories, make_token, authorization_override
):
    """An invalid role string returns 400 Bad Request."""
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target_user.id, "role": "superadmin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert "Invalid role" in response.json()["detail"]

    tenant_repo, user_repo, _ = repositories
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(target_user.id)
    await user_repo.delete(admin.id)


async def test_create_membership_missing_user_id_returns_422(
    client, repositories, make_token, authorization_override
):
    """A request without user_id returns 422 Unprocessable Entity."""
    admin = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "user_id is required" in response.json()["detail"]

    tenant_repo, user_repo, _ = repositories
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(admin.id)


async def test_create_membership_default_role(
    client, repositories, make_token, authorization_override
):
    """When role is omitted, the default is 'member'."""
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target_user.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "member"

    tenant_repo, user_repo, membership_repo = repositories
    await membership_repo.delete(response.json()["id"])
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(target_user.id)
    await user_repo.delete(admin.id)


async def test_delete_membership_requires_permission(
    client, repositories, seeded, make_token, authorization_override
):
    """Unauthenticated or unauthorized users cannot delete memberships."""
    tenant, user, membership = seeded
    employee = await _seed_user(repositories)
    authorization_override({employee.id: ApplicationRole.EMPLOYEE})
    token = make_token(employee.id)

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(employee.id)


async def test_delete_membership_success(
    client, repositories, seeded, make_token, authorization_override
):
    """Platform administrator can delete a membership."""
    tenant, user, membership = seeded
    admin = await _seed_user(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["detail"] == "Membership removed"

    _, user_repo, _ = repositories
    await user_repo.delete(admin.id)


async def test_delete_membership_not_found_returns_404(
    client, repositories, make_token, authorization_override
):
    """Deleting a nonexistent membership returns 404."""
    admin = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override(
        {admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR}
    )
    token = make_token(admin.id)

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/nonexistent-user",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert "No membership found" in response.json()["detail"]

    tenant_repo, user_repo, _ = repositories
    await tenant_repo.delete(tenant.id)
    await user_repo.delete(admin.id)


async def test_membership_endpoints_in_production_openapi():
    """Membership endpoints are in the production OpenAPI schema."""
    import json
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["APP_ENV"] = "production"
    script = (
        "import json\n"
        "import arc.main as main_module\n"
        "print(json.dumps(sorted(main_module.app.openapi().get('paths', {}))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"openapi subprocess failed: {result.stderr}"
    paths = set(json.loads(result.stdout))
    assert "/tenants/{tenant_id}/memberships" in paths
