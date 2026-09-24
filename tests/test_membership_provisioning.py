"""Tests for the production tenant membership provisioning endpoints.

Validates that:
- POST /tenants/{tenant_id}/memberships creates memberships
- DELETE /tenants/{tenant_id}/memberships/{user_id} removes memberships
- Both endpoints require membership:create permission (PLATFORM_ADMINISTRATOR)
- Duplicate memberships return 409
- Missing users/tenants return appropriate errors
"""

import uuid

from arc.domain.models import Membership, Tenant, User, UserRole
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


async def test_create_membership_success(client, repositories, make_token, authorization_override):
    """Platform administrator can create a membership."""
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    """An invalid role string is rejected by request validation (Issue #135).

    This returned a hand-raised 400 until ``role`` became a ``UserRole`` field
    on the request model. It is now FastAPI's native 422 with a structured
    detail naming the offending field.
    """
    admin = await _seed_user(repositories)
    target_user = await _seed_user(repositories)
    tenant = await _seed_tenant(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target_user.id, "role": "superadmin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any("role" in error["loc"] for error in detail)

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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    # Still 422, but the detail is now FastAPI's structured list rather than
    # the hand-written string "user_id is required" (Issue #135).
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any("user_id" in error["loc"] for error in detail)

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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
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


# ---------------------------------------------------------------------------
# ADR-009: tenant-scoped membership administration
# ---------------------------------------------------------------------------


async def _seed_tenant_with_owner(repositories, owner_role=UserRole.OWNER):
    """A tenant, an owner, and the owner's membership."""
    tenant_repo, _, membership_repo = repositories
    tenant = await tenant_repo.create(
        Tenant(id=_unique("tenant"), name=f"Company {uuid.uuid4().hex[:6]}")
    )
    owner = await _seed_user(repositories)
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=owner.id,
            tenant_id=tenant.id,
            role=owner_role,
        )
    )
    return tenant, owner


async def test_company_administrator_can_add_a_member_to_their_own_tenant(
    client, repositories, make_token, authorization_override
):
    """ADR-009. Before this, every joiner needed the platform operator."""
    tenant, admin = await _seed_tenant_with_owner(repositories)
    newcomer = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.COMPANY_ADMINISTRATOR})

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": newcomer.id, "role": "member"},
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == newcomer.id


async def test_company_administrator_cannot_touch_another_tenant(
    client, repositories, make_token, authorization_override
):
    """The scoped permission is only ever evaluated against a context the
    caller proved membership of, so another tenant fails before the
    handler runs."""
    _, admin = await _seed_tenant_with_owner(repositories)
    other_tenant, _ = await _seed_tenant_with_owner(repositories)
    victim = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.COMPANY_ADMINISTRATOR})

    response = client.post(
        f"/tenants/{other_tenant.id}/memberships",
        json={"user_id": victim.id, "role": "member"},
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    assert response.status_code == 403


async def test_company_administrator_can_remove_a_member(
    client, repositories, make_token, authorization_override
):
    tenant, admin = await _seed_tenant_with_owner(repositories)
    member = await _seed_user(repositories)
    _, _, membership_repo = repositories
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=member.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )
    authorization_override({admin.id: ApplicationRole.COMPANY_ADMINISTRATOR})

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{member.id}",
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    assert response.status_code == 200


async def test_the_last_owner_cannot_be_removed(
    client, repositories, make_token, authorization_override
):
    """A workspace with no owner cannot be administered by anyone in it.

    Enforced server-side rather than by hiding a control: a hidden
    control does not prevent the request.
    """
    tenant, owner = await _seed_tenant_with_owner(repositories)
    platform_admin = await _seed_user(repositories)
    authorization_override({platform_admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{owner.id}",
        headers={"Authorization": f"Bearer {make_token(platform_admin.id)}"},
    )

    assert response.status_code == 409
    assert "only owner" in response.json()["detail"].lower()


async def test_an_owner_can_be_removed_when_another_owner_remains(
    client, repositories, make_token, authorization_override
):
    """The invariant is 'at least one owner', not 'owners are permanent'."""
    tenant, first_owner = await _seed_tenant_with_owner(repositories)
    second_owner = await _seed_user(repositories)
    _, _, membership_repo = repositories
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=second_owner.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )
    )
    authorization_override({first_owner.id: ApplicationRole.COMPANY_ADMINISTRATOR})

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{second_owner.id}",
        headers={"Authorization": f"Bearer {make_token(first_owner.id)}"},
    )

    assert response.status_code == 200


async def test_nobody_can_remove_their_own_membership(
    client, repositories, make_token, authorization_override
):
    """Self-removal locks an administrator out of the workspace they are
    responsible for, and reads as an accident far more often than an
    intention."""
    tenant, admin = await _seed_tenant_with_owner(repositories)
    second_owner = await _seed_user(repositories)
    _, _, membership_repo = repositories
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=second_owner.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )
    )
    authorization_override({admin.id: ApplicationRole.COMPANY_ADMINISTRATOR})

    response = client.delete(
        f"/tenants/{tenant.id}/memberships/{admin.id}",
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    # Refused even though another owner remains, so this is the
    # self-removal rule and not the last-owner rule.
    assert response.status_code == 409
    assert "your own membership" in response.json()["detail"].lower()


async def test_operations_user_still_cannot_manage_membership(
    client, repositories, make_token, authorization_override
):
    """ADR-009 widened authority to company administrators only."""
    tenant, _ = await _seed_tenant_with_owner(repositories)
    ops = await _seed_user(repositories)
    _, _, membership_repo = repositories
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=ops.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )
    target = await _seed_user(repositories)
    authorization_override({ops.id: ApplicationRole.OPERATIONS_USER})

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target.id, "role": "member"},
        headers={"Authorization": f"Bearer {make_token(ops.id)}"},
    )

    assert response.status_code == 403


async def test_employee_still_cannot_manage_membership(
    client, repositories, make_token, authorization_override
):
    tenant, _ = await _seed_tenant_with_owner(repositories)
    employee = await _seed_user(repositories)
    target = await _seed_user(repositories)
    authorization_override({employee.id: ApplicationRole.EMPLOYEE})

    response = client.post(
        f"/tenants/{tenant.id}/memberships",
        json={"user_id": target.id, "role": "member"},
        headers={"Authorization": f"Bearer {make_token(employee.id)}"},
    )

    assert response.status_code == 403
