"""Development-only API controllers for Arc multi-tenant foundation.

These endpoints are development scaffolding, NOT protected application
endpoints. They must not be treated as part of the public API surface:

- ``POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships``
  provisions memberships without authentication and can grant any
  membership role, including OWNER. X-11 will introduce authenticated
  membership management and application RBAC.

- ``POST /internal/dev/tenant-contexts`` and
  ``GET /internal/dev/tenant-contexts/validate`` accept a caller-supplied
  ``user_id``. That value is NOT an authenticated identity. The intended
  identity flow, to be realized in X-11, is:

  Authenticated Principal -> trusted user identity -> TenantContextService
  -> trusted TenantContext

The service-level API (``TenantContextService.create_tenant_context``)
remains unchanged and continues to derive the role exclusively from the
persisted membership. These endpoints are mounted only when
``APP_ENV=development`` (see ``arc.main``).
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from arc.api.controllers import app_context
from arc.db.connection import NotFoundError
from arc.domain.models import TenantContext, UserRole
from arc.services.domain import TenantContextService, UserService

dev_router = APIRouter(prefix="/internal/dev")


@dev_router.post("/users/{user_id}/tenants/{tenant_id}/memberships")
async def create_membership(
    user_id: str,
    tenant_id: str,
    membership_data: Dict[str, Any],
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> Dict[str, Any]:
    """Associate a user with a tenant (development-only provisioning).

    DEVELOPMENT-ONLY: this endpoint has no authentication and can grant
    any membership role, including OWNER. It must not be treated as a
    protected application endpoint. X-11 will provide authenticated
    membership management. The role is stored as the persisted membership
    role; tenant-context role derivation never trusts caller input.
    """
    role_str = membership_data.get("role", "member")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role_str}"
        )

    membership = await user_service.associate_user_with_tenant(
        user_id=user_id, tenant_id=tenant_id, role=role, membership_id=membership_data.get("id")
    )

    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "tenant_id": membership.tenant_id,
        "role": membership.role.value,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }


@dev_router.post("/tenant-contexts")
async def create_tenant_context(
    context_data: Dict[str, Any],
    tenant_context_service: TenantContextService = Depends(
        lambda: app_context.tenant_context_service
    ),
) -> Dict[str, Any]:
    """Create a tenant context (development-only).

    DEVELOPMENT-ONLY: the caller-supplied ``user_id`` is NOT treated as an
    authenticated identity. X-11 will supply the trusted user identity
    from an authenticated principal. The context role is derived from the
    verified persisted membership; caller-provided roles are never trusted.
    """
    context = await tenant_context_service.create_tenant_context(
        tenant_id=context_data.get("tenant_id"), user_id=context_data.get("user_id")
    )

    return {
        "tenant_id": context.tenant_id,
        "tenant_name": context.tenant_name,
        "user_id": context.user_id,
        "role": context.role.value,
    }


@dev_router.get("/tenant-contexts/validate")
async def validate_tenant_context(
    tenant_id: str,
    user_id: str,
    role: str,
    tenant_context_service: TenantContextService = Depends(
        lambda: app_context.tenant_context_service
    ),
) -> Dict[str, Any]:
    """Validate a tenant context (development-only).

    DEVELOPMENT-ONLY: accepts a caller-supplied ``user_id`` and ``role``.
    The response reflects whether the supplied values match a persisted
    membership. X-11 will replace this scaffolding with validation driven
    by the authenticated principal.
    """
    try:
        role_enum = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role}")

    try:
        tenant = await app_context.tenant_service.get_tenant(tenant_id)
    except NotFoundError:
        return {"is_valid": False}

    context = TenantContext(
        tenant_id=tenant_id,
        tenant_name=tenant.name,
        user_id=user_id,
        role=role_enum,
    )

    is_valid = await tenant_context_service.validate_context(context)

    return {"is_valid": is_valid}
