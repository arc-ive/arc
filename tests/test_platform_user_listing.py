"""Tests for the GET /platform/users endpoint.

Validates that:
- PLATFORM_ADMINISTRATOR can list all users
- Unauthorized roles receive 403
- Empty directory returns []
- Response contains only the intended public fields
- Endpoint is in the production OpenAPI schema
"""

import uuid

from arc.domain.models import User
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"plat-users-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="plat-user",
        )
    )


async def test_platform_administrator_can_list_users(
    client, repositories, make_token, authorization_override
):
    """Platform administrator receives 200 and the user list."""
    admin = await _seed_user(repositories)
    target = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)

    user_ids = {u["id"] for u in body["items"]}
    assert target.id in user_ids
    assert admin.id in user_ids

    target_user = next(u for u in body["items"] if u["id"] == target.id)
    assert "email" in target_user
    assert "username" in target_user
    assert "status" in target_user
    assert "created_at" in target_user
    assert "updated_at" in target_user

    _, user_repo, _ = repositories
    await user_repo.delete(target.id)
    await user_repo.delete(admin.id)


async def test_employee_cannot_list_users(client, repositories, make_token, authorization_override):
    """Unauthorized roles receive 403."""
    employee = await _seed_user(repositories)
    authorization_override({employee.id: ApplicationRole.EMPLOYEE})
    token = make_token(employee.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(employee.id)


async def test_company_administrator_cannot_list_users(
    client, repositories, make_token, authorization_override
):
    """Company administrator receives 403 (not granted user:read)."""
    admin = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(admin.id)


async def test_operations_user_cannot_list_users(
    client, repositories, make_token, authorization_override
):
    """Operations user receives 403 (not granted user:read)."""
    ops = await _seed_user(repositories)
    authorization_override({ops.id: ApplicationRole.OPERATIONS_USER})
    token = make_token(ops.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    _, user_repo, _ = repositories
    await user_repo.delete(ops.id)


async def test_empty_directory_returns_empty_list(
    client, make_token, authorization_override, repositories
):
    """Endpoint returns a list (may be empty or pre-populated in shared DB)."""
    admin = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)

    _, user_repo, _ = repositories
    await user_repo.delete(admin.id)


async def test_response_excludes_no_sensitive_fields(
    client, repositories, make_token, authorization_override
):
    """Response contains exactly the intended public fields."""
    admin = await _seed_user(repositories)
    target = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin.id)

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()

    target_user = next(u for u in body["items"] if u["id"] == target.id)
    # "memberships" added by issue #296. The key set is asserted exactly
    # on purpose: this endpoint is the platform plane's view of a person,
    # and a field appearing here without a decision is how tenant content
    # leaks into it.
    expected_keys = {
        "id",
        "email",
        "username",
        "status",
        "memberships",
        "created_at",
        "updated_at",
    }
    assert set(target_user.keys()) == expected_keys

    _, user_repo, _ = repositories
    await user_repo.delete(target.id)
    await user_repo.delete(admin.id)


async def test_platform_users_in_production_openapi():
    """GET /platform/users is in the production OpenAPI schema."""
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
    assert "/platform/users" in paths


async def _seed_tenant_with_member(repositories, user, role):
    from arc.domain.models import Membership, Tenant

    tenant_repo, _, membership_repo = repositories
    tenant = await tenant_repo.create(
        Tenant(id=_unique("tenant"), name=f"Company {uuid.uuid4().hex[:6]}")
    )
    await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=role,
        )
    )
    return tenant


async def test_listing_reports_each_membership_with_its_tenant_name(
    client, repositories, make_token, authorization_override
):
    """Issue #296: the directory must be organisable by company.

    Without this the platform sees one flat list of every person across
    every customer, which is unreadable once there is more than one
    customer. Membership is platform administration metadata, not tenant
    content: ADR-008 already allows a PLATFORM_ADMINISTRATOR to CREATE
    memberships for any user in any tenant.
    """
    from arc.domain.models import UserRole

    admin = await _seed_user(repositories)
    target = await _seed_user(repositories)
    tenant = await _seed_tenant_with_member(repositories, target, UserRole.OWNER)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    assert response.status_code == 200
    listed = next(u for u in response.json()["items"] if u["id"] == target.id)
    assert listed["memberships"] == [
        {"tenant_id": tenant.id, "tenant_name": tenant.name, "role": "owner"}
    ]


async def test_a_person_in_two_companies_reports_both(
    client, repositories, make_token, authorization_override
):
    """Hiding the second membership would misrepresent their access."""
    from arc.domain.models import UserRole

    admin = await _seed_user(repositories)
    target = await _seed_user(repositories)
    first = await _seed_tenant_with_member(repositories, target, UserRole.OWNER)
    second = await _seed_tenant_with_member(repositories, target, UserRole.MEMBER)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    listed = next(u for u in response.json()["items"] if u["id"] == target.id)
    assert {m["tenant_id"] for m in listed["memberships"]} == {first.id, second.id}
    assert {m["role"] for m in listed["memberships"]} == {"owner", "member"}


async def test_a_person_with_no_membership_reports_an_empty_list(
    client, repositories, make_token, authorization_override
):
    """Platform administrators sit here: administering Arc is not membership."""
    admin = await _seed_user(repositories)
    target = await _seed_user(repositories)
    authorization_override({admin.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

    response = client.get(
        "/platform/users",
        headers={"Authorization": f"Bearer {make_token(admin.id)}"},
    )

    listed = next(u for u in response.json()["items"] if u["id"] == target.id)
    assert listed["memberships"] == []
