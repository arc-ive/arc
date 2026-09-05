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
    assert isinstance(body, list)

    user_ids = {u["id"] for u in body}
    assert target.id in user_ids
    assert admin.id in user_ids

    target_user = next(u for u in body if u["id"] == target.id)
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
    assert isinstance(body, list)

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

    target_user = next(u for u in body if u["id"] == target.id)
    expected_keys = {"id", "email", "username", "status", "created_at", "updated_at"}
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
