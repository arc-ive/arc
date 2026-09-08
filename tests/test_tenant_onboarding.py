"""Tests for tenant creation with automatic OWNER membership (Issue #58).

When an authenticated Platform Administrator creates a tenant via
POST /tenants, the authenticated creator is automatically assigned
OWNER membership for that tenant. The tenant and membership are
created atomically.
"""

import uuid
from datetime import datetime, timezone

from arc.db.connection import ArcDatabase, DatabaseError
from arc.domain.models import Membership, Tenant, User, UserRole
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"onboard-{prefix}-{uuid.uuid4().hex[:10]}"


async def test_tenant_creation_assigns_owner_membership(
    client, repositories, make_token, authorization_override
):
    """POST /tenants creates the tenant and assigns OWNER membership to the creator."""
    tenant_repo, user_repo, membership_repo = repositories

    # Create a user to act as the Platform Administrator
    user = await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-admin",
        )
    )
    authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(user.id)

    tenant_id = _unique("tenant")
    response = client.post(
        "/tenants",
        json={"id": tenant_id, "name": "Onboard Test Tenant"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tenant_id
    assert data["name"] == "Onboard Test Tenant"
    assert data["status"] == "active"

    # Verify exactly one OWNER membership exists for the creator
    membership = await membership_repo.get_by_user_and_tenant(user.id, tenant_id)
    assert membership is not None
    assert membership.role == UserRole.OWNER
    assert membership.user_id == user.id
    assert membership.tenant_id == tenant_id

    # Verify the creator can list the tenant
    response = client.get(
        f"/users/{user.id}/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    tenants = response.json()
    assert any(t["id"] == tenant_id for t in tenants)

    # Verify the creator can access the tenant
    response = client.get(
        f"/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == tenant_id

    # Cleanup
    await membership_repo.delete(membership.id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant_id)


async def test_tenant_creation_no_duplicate_membership(
    client, repositories, make_token, authorization_override
):
    """Creating a tenant does not create duplicate memberships."""
    tenant_repo, user_repo, membership_repo = repositories

    user = await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-dup",
        )
    )
    authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(user.id)

    tenant_id = _unique("tenant")
    response = client.post(
        "/tenants",
        json={"id": tenant_id, "name": "Dup Test Tenant"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # Verify only one membership exists
    memberships = await membership_repo.get_memberships_for_tenant(tenant_id)
    assert len(memberships) == 1
    assert memberships[0].role == UserRole.OWNER
    assert memberships[0].user_id == user.id

    # Cleanup
    await membership_repo.delete(memberships[0].id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant_id)


async def test_tenant_creation_requires_permission(
    client, repositories, make_token, authorization_override
):
    """POST /tenants is rejected without TENANT_CREATE permission."""
    _, user_repo, _ = repositories

    user = await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-noperm",
        )
    )
    # EMPLOYEE has no TENANT_CREATE permission
    authorization_override({user.id: ApplicationRole.EMPLOYEE})
    token = make_token(user.id)

    response = client.post(
        "/tenants",
        json={"id": _unique("tenant"), "name": "Should Fail"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

    # Cleanup
    await user_repo.delete(user.id)


async def test_duplicate_tenant_creation_returns_conflict(
    db, repositories, make_token, authorization_override, client
):
    """POST /tenants with a duplicate tenant ID returns 409 Conflict.

    The DuplicateKeyError raised by the unique tenants_pkey constraint is
    translated to a 409 by the global exception handler.  The original
    tenant is unchanged and no membership is created for the duplicate
    attempt.
    """
    tenant_repo, user_repo, membership_repo = repositories

    user = await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-rollback",
        )
    )
    authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(user.id)

    # Attempt to create a tenant with duplicate ID (should trigger atomic rollback)
    tenant_id = _unique("tenant")
    await tenant_repo.create(Tenant(id=tenant_id, name="Pre-existing Tenant"))

    # Attempt to create a tenant with the same ID (should fail with 409)
    response = client.post(
        "/tenants",
        json={"id": tenant_id, "name": "Should Fail"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409

    # Verify the original tenant is unchanged
    existing_tenant = await tenant_repo.get_by_id(tenant_id)
    assert existing_tenant.name == "Pre-existing Tenant"

    # Verify no new memberships were created (the operation was rolled back)
    # The pre-existing tenant has no membership (we didn't create one)
    # So there should be no memberships for this tenant
    memberships = await membership_repo.get_memberships_for_tenant(tenant_id)
    assert len(memberships) == 0

    # Cleanup
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant_id)


async def test_tenant_rollback_on_membership_fk_failure(db: ArcDatabase):
    """Database-level atomicity: failed membership INSERT rolls back tenant INSERT.

    Exercises ArcDatabase.create_tenant_with_owner() directly.  The
    membership references a nonexistent user_id, triggering the
    memberships FOREIGN KEY constraint.  The entire transaction must
    roll back — the tenant row must not persist.
    """
    tenant_id = _unique("atomic")
    nonexistent_user_id = _unique("ghost")

    tenant = Tenant(id=tenant_id, name="Atomic Rollback Tenant")
    membership = Membership(
        id=_unique("membership"),
        user_id=nonexistent_user_id,
        tenant_id=tenant_id,
        role=UserRole.OWNER,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # The FK violation must raise a DatabaseError (or subclass)
    try:
        await db.create_tenant_with_owner(tenant, membership)
        raise AssertionError("Expected DatabaseError was not raised")
    except DatabaseError:
        pass  # expected — membership FK violation propagated as DatabaseError

    # Verify the tenant was rolled back and does not exist
    from arc.db.connection import NotFoundError

    try:
        await db.get_tenant(tenant_id)
        raise AssertionError("Tenant should have been rolled back but still exists")
    except NotFoundError:
        pass  # expected — tenant was rolled back


async def test_tenant_isolation_after_creation(
    client, repositories, make_token, authorization_override
):
    """Another user cannot access the newly created tenant without membership."""
    tenant_repo, user_repo, membership_repo = repositories

    # Create admin user and tenant
    admin = await user_repo.create(
        User(
            id=_unique("admin"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-admin-iso",
        )
    )
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    admin_token = make_token(admin.id)

    tenant_id = _unique("tenant")
    response = client.post(
        "/tenants",
        json={"id": tenant_id, "name": "Isolation Test Tenant"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200

    # Create another user without membership
    other = await user_repo.create(
        User(
            id=_unique("other"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="onboard-other-iso",
        )
    )
    authorization_override({other.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    other_token = make_token(other.id)

    # Other user should not see the tenant
    response = client.get(
        f"/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 403

    # Other user's tenant list should be empty
    response = client.get(
        f"/users/{other.id}/tenants",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0

    # Cleanup
    admin_membership = await membership_repo.get_by_user_and_tenant(admin.id, tenant_id)
    await membership_repo.delete(admin_membership.id)
    await user_repo.delete(admin.id)


async def test_tenant_creation_returns_400_when_user_not_in_users_table(
    client, repositories, make_token, authorization_override
):
    """POST /tenants returns 400 (not 500) when the authenticated user_id
    does not exist in the users table (FK violation on memberships.user_id).

    Regression test for Issue #116: the endpoint previously returned a raw
    500 because the ForeignKeyViolation was wrapped in DatabaseError and not
    caught by the controller.
    """
    tenant_repo, user_repo, membership_repo = repositories

    # Pick a user_id that is guaranteed NOT to exist in the users table
    ghost_id = f"ghost-{uuid.uuid4().hex[:10]}"
    authorization_override({ghost_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(ghost_id)

    tenant_id = _unique("tenant")
    response = client.post(
        "/tenants",
        json={"id": tenant_id, "name": "Should Fail Tenant"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Must NOT be 500 — the FK violation should be caught and returned as 400
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
    assert "does not exist in the users table" in body["detail"]
