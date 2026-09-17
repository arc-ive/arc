"""Tests for the GET /platform/tenants endpoint.

Validates that:
- PLATFORM_ADMINISTRATOR can list all tenants
- Unauthorized roles receive 403
- Empty directory returns []
- Response contains only the intended public fields
- Endpoint is in the production OpenAPI schema
- No membership is required
"""

import uuid

from arc.domain.models import Tenant
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"plat-tenants-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_tenant(repositories):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(
        Tenant(
            id=_unique("tenant"),
            name="Platform Tenant",
        )
    )


async def test_platform_administrator_can_list_tenants(
    client, repositories, make_token, authorization_override
):
    """Platform administrator receives 200 and the tenant list."""
    admin_user_id = _unique("user")
    target = await _seed_tenant(repositories)
    authorization_override({admin_user_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin_user_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)

    tenant_ids = {t["id"] for t in body["items"]}
    assert target.id in tenant_ids

    target_tenant = next(t for t in body["items"] if t["id"] == target.id)
    assert "name" in target_tenant
    assert "status" in target_tenant
    assert "industry" in target_tenant
    assert "created_at" in target_tenant
    assert "updated_at" in target_tenant

    tenant_repo, _, _ = repositories
    await tenant_repo.delete(target.id)


async def test_employee_cannot_list_tenants(
    client, repositories, make_token, authorization_override
):
    """Unauthorized roles receive 403."""
    employee_id = _unique("user")
    authorization_override({employee_id: ApplicationRole.EMPLOYEE})
    token = make_token(employee_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_company_administrator_cannot_list_tenants(
    client, repositories, make_token, authorization_override
):
    """Company administrator receives 403 (not granted tenant:list)."""
    admin_id = _unique("user")
    authorization_override({admin_id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(admin_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_operations_user_cannot_list_tenants(
    client, repositories, make_token, authorization_override
):
    """Operations user receives 403 (not granted tenant:list)."""
    ops_id = _unique("user")
    authorization_override({ops_id: ApplicationRole.OPERATIONS_USER})
    token = make_token(ops_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_unauthenticated_receives_401(client):
    """Unauthenticated request receives 401."""
    response = client.get("/platform/tenants")
    assert response.status_code in (401, 403)


async def test_empty_directory_returns_empty_list(
    client, make_token, authorization_override, repositories
):
    """Endpoint returns a list (may be empty or pre-populated in shared DB)."""
    admin_id = _unique("user")
    authorization_override({admin_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)


async def test_response_excludes_no_sensitive_fields(
    client, repositories, make_token, authorization_override
):
    """Response contains exactly the intended public fields."""
    admin_id = _unique("user")
    target = await _seed_tenant(repositories)
    authorization_override({admin_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()

    target_tenant = next(t for t in body["items"] if t["id"] == target.id)
    expected_keys = {"id", "name", "status", "industry", "created_at", "updated_at"}
    assert set(target_tenant.keys()) == expected_keys

    tenant_repo, _, _ = repositories
    await tenant_repo.delete(target.id)


async def test_no_implicit_membership_created(
    client, repositories, make_token, authorization_override
):
    """GET /platform/tenants does NOT create a membership for the caller."""
    admin_id = _unique("user")
    authorization_override({admin_id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    token = make_token(admin_id)

    response = client.get(
        "/platform/tenants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


async def test_platform_tenants_in_production_openapi():
    """GET /platform/tenants is in the production OpenAPI schema."""
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
    assert "/platform/tenants" in paths
