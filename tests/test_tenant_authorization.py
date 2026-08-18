"""X-11 tenant-scoped authorization tests against PostgreSQL.

The trusted tenant context comes exclusively from the X-10 persisted
membership, keyed by the authenticated principal (JWT ``sub``). The
client-supplied ``tenant_id`` is request input only: missing membership,
cross-tenant access, and missing tenants are denied with 403 (fail closed).
"""

import uuid

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"authz-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_tenant(repositories, name="Authz Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="authz-user")
    )


async def test_valid_member_with_tenant_read_can_access(
    client, repositories, seeded, make_token, authorization_override
):
    """A trusted member with tenant:read may read the tenant."""
    tenant, user, _ = seeded
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get(f"/tenants/{tenant.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["id"] == tenant.id


async def test_member_without_tenant_read_is_denied(
    client, repositories, seeded, make_token, authorization_override
):
    """A valid membership does not grant permission without the application role."""
    tenant, user, _ = seeded
    authorization_override({user.id: ApplicationRole.EMPLOYEE})
    token = make_token(user.id)

    response = client.get(f"/tenants/{tenant.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_cross_tenant_access_is_denied(
    client, repositories, seeded, make_token, authorization_override
):
    """A tenant member must not access another tenant they do not belong to."""
    tenant, user, _ = seeded
    other_tenant = await _seed_tenant(repositories, "Other Tenant")
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get(
        f"/tenants/{other_tenant.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

    tenant_repo, _, _ = repositories
    await tenant_repo.delete(other_tenant.id)


async def test_missing_membership_is_denied(
    client, repositories, seeded, make_token, authorization_override
):
    """A user without any membership must be denied the tenant."""
    tenant, _, _ = seeded
    orphan = await _seed_user(repositories)
    authorization_override({orphan.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(orphan.id)

    response = client.get(f"/tenants/{tenant.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(orphan.id)


async def test_missing_tenant_is_denied(
    client, repositories, seeded, make_token, authorization_override
):
    """A nonexistent tenant must be denied: no data leakage about existence."""
    _, user, _ = seeded
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get(
        f"/tenants/{_unique('missing')}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


async def test_client_tenant_id_cannot_override_identity(
    client, repositories, seeded, make_token, authorization_override
):
    """The membership lookup keys on the JWT identity, never on client claims."""
    tenant, user, _ = seeded
    other_tenant = await _seed_tenant(repositories, "Other Tenant")
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get(
        f"/tenants/{other_tenant.id}",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant.id},
        params={"tenant_id": tenant.id},
    )
    assert response.status_code == 403

    tenant_repo, _, _ = repositories
    await tenant_repo.delete(other_tenant.id)


async def test_membership_role_never_grants_application_permissions(
    client, repositories, make_token, authorization_override
):
    """An OWNER membership without an application role assignment is denied."""
    tenant_repo, user_repo, membership_repo = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Owner Tenant"))
    user = await _seed_user(repositories)
    membership = await membership_repo.create(
        Membership(
            id=_unique("membership"), user_id=user.id, tenant_id=tenant.id, role=UserRole.OWNER
        )
    )
    authorization_override({})
    token = make_token(user.id)

    response = client.get(f"/tenants/{tenant.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    await membership_repo.delete(membership.id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant.id)


async def test_self_scoped_listing_allowed_without_matrix_permission(
    client, repositories, seeded, make_token, authorization_override
):
    """EMPLOYEE (no matrix permissions) may still list their own tenants."""
    _, user, _ = seeded
    authorization_override({user.id: ApplicationRole.EMPLOYEE})
    token = make_token(user.id)

    response = client.get(f"/users/{user.id}/tenants", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_self_scoped_other_user_is_denied(
    client, repositories, seeded, make_token, authorization_override
):
    """Listing another user's tenants is denied even with a valid role."""
    _, user, _ = seeded
    other = await _seed_user(repositories)
    authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(user.id)

    response = client.get(
        f"/users/{other.id}/tenants", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(other.id)


async def test_global_permission_requires_no_tenant_context(
    client, repositories, make_token, authorization_override
):
    """A global permission (tenant:create) needs no tenant membership."""
    authorization_override({"admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token("admin")

    response = client.post(
        "/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": _unique("tenant"), "name": "Global Admin Tenant"},
    )
    assert response.status_code == 200
