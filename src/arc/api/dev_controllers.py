"""Development-only API controllers for Arc multi-tenant foundation.

The remaining development endpoint is membership provisioning, mounted
only when ``APP_ENV=development`` (see ``arc.main``). It is protected by
X-11 authentication and the global ``membership:create`` permission
(PLATFORM_ADMINISTRATOR only), because it can grant any membership role,
including OWNER.

The former tenant-context scaffolding endpoints
(``POST /internal/dev/tenant-contexts`` and
``GET /internal/dev/tenant-contexts/validate``) accepted a caller-supplied
``user_id`` and were explicitly reserved by X-10 for replacement by X-11.
They have been REMOVED: X-11 establishes identity exclusively from the
authenticated principal (JWT ``sub``), and the public tenant-scoped
endpoints now build trusted tenant context from that principal.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends

from arc.api.controllers import app_context
from arc.api.schemas import AUTHENTICATED_ERROR_RESPONSES, DevMembershipCreateRequest
from arc.security.authorization import MEMBERSHIP_CREATE
from arc.security.dependencies import require_permission
from arc.security.models import AuthenticatedPrincipal
from arc.services.domain import UserService

dev_router = APIRouter(prefix="/internal/dev")


@dev_router.post(
    "/users/{user_id}/tenants/{tenant_id}/memberships",
    responses=AUTHENTICATED_ERROR_RESPONSES,
)
async def create_membership(
    user_id: str,
    tenant_id: str,
    membership_data: DevMembershipCreateRequest,
    _: AuthenticatedPrincipal = Depends(require_permission(MEMBERSHIP_CREATE)),
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> Dict[str, Any]:
    """Associate a user with a tenant (development-only provisioning).

    DEVELOPMENT-ONLY: mounted only when ``APP_ENV=development``. Protected
    by authentication and the global ``membership:create`` permission
    (PLATFORM_ADMINISTRATOR). The target ``user_id``/``tenant_id`` are
    provisioning targets, not the caller's identity: identity always comes
    from the authenticated principal. The role is stored as the persisted
    membership role; tenant-context role derivation never trusts caller
    input.
    """
    membership = await user_service.associate_user_with_tenant(
        user_id=user_id,
        tenant_id=tenant_id,
        role=membership_data.role,
        membership_id=membership_data.id,
    )

    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "tenant_id": membership.tenant_id,
        "role": membership.role.value,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }
