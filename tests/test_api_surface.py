"""API-boundary regression tests for the X-10 review fix and X-11.

These tests prove that privileged and identity-sensitive endpoints
(membership provisioning and tenant-context creation/validation) are
isolated from the public application API surface.

X-11 changes:
- Membership provisioning is protected by authentication and the global
  ``membership:create`` permission (PLATFORM_ADMINISTRATOR only) and remains
  development-only.
- The tenant-context scaffolding endpoints
  (``POST /internal/dev/tenant-contexts``,
  ``GET /internal/dev/tenant-contexts/validate``) accepted a caller-supplied
  ``user_id`` and are REMOVED. X-11 establishes identity exclusively from
  the authenticated principal (JWT ``sub``).
"""

import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from arc.api.controllers import api_router
from arc.api.dev_controllers import dev_router
from arc.db.connection import NotFoundError
from arc.domain.models import Membership, Tenant, User, UserRole
from arc.repositories import MembershipRepository, TenantRepository, UserRepository
from arc.services.domain import TenantContextService

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

DEV_PATHS = {
    "POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships",
}

DEV_OPENAPI_PATHS = {
    "/internal/dev/users/{user_id}/tenants/{tenant_id}/memberships",
}

LEGACY_PUBLIC_OPENAPI_PATHS = {
    "/users/{user_id}/tenants/{tenant_id}/memberships",
    "/tenant-contexts",
    "/tenant-contexts/validate",
}

REMOVED_DEV_OPENAPI_PATHS = {
    "/internal/dev/tenant-contexts",
    "/internal/dev/tenant-contexts/validate",
}


def _route_paths(routes) -> set:
    """Return the set of "METHOD /path" strings for the given routes."""
    paths = set()
    for route in routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method in HTTP_METHODS:
                    paths.add(f"{method} {route.path}")
    return paths


def test_public_api_does_not_expose_membership_provisioning():
    """Concern 1: OWNER-capable membership provisioning is not a public endpoint."""
    public = _route_paths(api_router.routes)
    assert "POST /users/{user_id}/tenants/{tenant_id}/memberships" not in public


def test_public_api_does_not_expose_caller_supplied_identity_context():
    """Concern 2/6: tenant-context endpoints are not part of the public API."""
    public = _route_paths(api_router.routes)
    assert "POST /tenant-contexts" not in public
    assert "GET /tenant-contexts/validate" not in public


def test_ai_tools_routes_are_public_api_surface():
    """The AI Tools catalog and execution endpoints are public application routes."""
    public = _route_paths(api_router.routes)
    assert "GET /tenants/{tenant_id}/tools" in public
    assert "POST /tenants/{tenant_id}/tools/{name}/execute" in public


def test_ai_tools_routes_present_in_production_openapi():
    """AI Tools endpoints are production application routes (not dev-only)."""
    paths = _openapi_paths("production")
    assert "/tenants/{tenant_id}/tools" in paths
    assert "/tenants/{tenant_id}/tools/{name}/execute" in paths


def test_public_api_exposes_connector_endpoints():
    """Connector endpoints (PRD 22) are public API and permission-protected.

    The tenant boundary comes from the trusted context and the connector
    permissions; no credential material is accepted or returned.
    """
    public = _route_paths(api_router.routes)
    assert "GET /tenants/{tenant_id}/connectors" in public
    assert "POST /tenants/{tenant_id}/connectors" in public
    assert "POST /tenants/{tenant_id}/connectors/{connector_id}/sync" in public


def test_public_api_exposes_observability_endpoints():
    """Observability endpoints (PRD 17) are public API, RBAC-protected.

    Tenant usage summaries are tenant-scoped behind ``observability:read``;
    the platform summary and component health are strictly tenant-agnostic
    and restricted to ``observability:platform_read`` (platform admin).
    """
    public = _route_paths(api_router.routes)
    assert "GET /tenants/{tenant_id}/observability/usage-summary" in public
    assert "GET /platform/observability/summary" in public
    assert "GET /observability/health" in public


def test_dev_router_isolates_development_endpoints():
    """The dev-only router retains membership provisioning under /internal/dev."""
    dev = _route_paths(dev_router.routes)
    assert dev == DEV_PATHS


def test_dev_router_has_no_caller_supplied_identity_scaffolding():
    """X-11 removed the tenant-context scaffolding that trusted a caller-supplied user_id."""
    dev = _route_paths(dev_router.routes)
    assert "POST /internal/dev/tenant-contexts" not in dev
    assert "GET /internal/dev/tenant-contexts/validate" not in dev


def _openapi_paths(app_env) -> set:
    """Return the mounted app's OpenAPI paths under an explicit APP_ENV.

    The app is loaded in a fresh subprocess so the module-level router
    mount in ``arc.main`` is evaluated with exactly the environment under
    test, independent of the developer's ambient APP_ENV. ``app_env=None``
    means APP_ENV is unset.
    """
    env = os.environ.copy()
    if app_env is None:
        env.pop("APP_ENV", None)
    else:
        env["APP_ENV"] = app_env

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
    return set(json.loads(result.stdout))


def test_dev_routes_mounted_when_app_env_is_development():
    """APP_ENV=development must mount the development-only routes."""
    paths = _openapi_paths("development")
    assert DEV_OPENAPI_PATHS.issubset(paths)


def test_dev_routes_absent_when_app_env_is_production():
    """APP_ENV=production must NOT expose the development-only routes."""
    paths = _openapi_paths("production")
    assert not DEV_OPENAPI_PATHS.intersection(paths)


def test_dev_routes_absent_when_app_env_unset():
    """An unset APP_ENV must fail closed and NOT expose the dev routes."""
    paths = _openapi_paths(None)
    assert not DEV_OPENAPI_PATHS.intersection(paths)


def test_legacy_public_paths_absent_in_all_environments():
    """The old public endpoints must never be mounted in any environment."""
    for app_env in ("development", "production", None):
        paths = _openapi_paths(app_env)
        assert not LEGACY_PUBLIC_OPENAPI_PATHS.intersection(paths)


def test_removed_dev_scaffolding_absent_in_all_environments():
    """The caller-supplied-identity dev scaffolding must be absent everywhere."""
    for app_env in ("development", "production", None):
        paths = _openapi_paths(app_env)
        assert not REMOVED_DEV_OPENAPI_PATHS.intersection(paths)


async def test_context_security_does_not_depend_on_provisioning_endpoint():
    """Requirement 1: TenantContextService fails closed on missing membership.

    The security decision depends only on persisted membership, never on
    any provisioning endpoint or caller-supplied role.
    """
    tenant_repo = AsyncMock(spec=TenantRepository)
    user_repo = AsyncMock(spec=UserRepository)
    membership_repo = AsyncMock(spec=MembershipRepository)

    tenant_repo.get_by_id.return_value = Tenant(id="tenant-a", name="Tenant A")
    user_repo.get_by_id.return_value = User(id="u-1", email="u-1@example.com")
    membership_repo.get_by_user_and_tenant.side_effect = NotFoundError("No membership")

    service = TenantContextService(user_repo, tenant_repo, membership_repo)

    with pytest.raises(NotFoundError):
        await service.create_tenant_context("tenant-a", "u-1")


async def test_intended_identity_flow_authenticated_principal_to_context():
    """Requirement 5: the intended identity flow is explicitly represented.

    Authenticated Principal -> trusted user identity -> TenantContextService
    -> TenantContext. The role comes exclusively from the persisted
    membership, never from caller input.
    """
    tenant_repo = AsyncMock(spec=TenantRepository)
    user_repo = AsyncMock(spec=UserRepository)
    membership_repo = AsyncMock(spec=MembershipRepository)

    tenant_repo.get_by_id.return_value = Tenant(id="tenant-a", name="Tenant A")
    user_repo.get_by_id.return_value = User(id="principal-user", email="p@example.com")
    membership_repo.get_by_user_and_tenant.return_value = Membership(
        id="m-1",
        user_id="principal-user",
        tenant_id="tenant-a",
        role=UserRole.VIEWER,
    )

    service = TenantContextService(user_repo, tenant_repo, membership_repo)

    context = await service.create_tenant_context("tenant-a", "principal-user")

    assert context.tenant_id == "tenant-a"
    assert context.user_id == "principal-user"
    assert context.role == UserRole.VIEWER
