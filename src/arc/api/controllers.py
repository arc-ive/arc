"""API controllers for Arc multi-tenant foundation.

Security-sensitive operations are protected by X-11 authentication and
application RBAC:

- Tenant and user provisioning require a global permission
  (PLATFORM_ADMINISTRATOR only).
- Tenant-scoped reads require a trusted X-10 tenant context and the
  ``tenant:read`` permission.
- Identity-scoped listing is self-only: the requested ``user_id`` must
  equal the authenticated principal's user ID (JWT ``sub``).

Privileged and identity-sensitive development endpoints (membership
provisioning) are isolated in ``arc.api.dev_controllers``.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from arc.domain.models import Tenant, TenantContext, User
from arc.security.authorization import TENANT_CREATE, TENANT_READ, USER_CREATE
from arc.security.dependencies import (
    get_authenticated_principal,
    require_permission,
    require_tenant_permission,
)
from arc.security.models import AuthenticatedPrincipal
from arc.services.domain import (
    MembershipService,
    TenantContextService,
    TenantService,
    UserService,
)


class ServiceRegistry:
    """Registry for accessing domain services."""

    def __init__(self):
        self._services = {}

    def register(self, name: str, service):
        """Register a service."""
        self._services[name] = service

    def get(self, name: str):
        """Get a service by name."""
        return self._services[name]


class ApplicationContext:
    """Application context for service access."""

    def __init__(self):
        self.services = ServiceRegistry()

    def register_services(self, services: Dict[str, Any]):
        """Register domain services."""
        for name, service in services.items():
            self.services.register(name, service)

    @property
    def tenant_service(self) -> TenantService:
        return self.services.get("tenant_service")

    @property
    def user_service(self) -> UserService:
        return self.services.get("user_service")

    @property
    def membership_service(self) -> MembershipService:
        return self.services.get("membership_service")

    @property
    def tenant_context_service(self) -> TenantContextService:
        return self.services.get("tenant_context_service")


# Global application context
app_context = ApplicationContext()


# API routers
api_router = APIRouter()


@api_router.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@api_router.post("/tenants")
async def create_tenant(
    tenant_data: Dict[str, Any],
    _: AuthenticatedPrincipal = Depends(require_permission(TENANT_CREATE)),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Create a new tenant.

    Protected: requires the global ``tenant:create`` permission
    (PLATFORM_ADMINISTRATOR). No tenant context is required.
    """
    tenant = Tenant(
        id=tenant_data.get("id"),
        name=tenant_data.get("name"),
        status=tenant_data.get("status", "active"),
    )
    created_tenant = await tenant_service.create_tenant(tenant)
    return {
        "id": created_tenant.id,
        "name": created_tenant.name,
        "status": created_tenant.status,
        "created_at": created_tenant.created_at.isoformat(),
        "updated_at": created_tenant.updated_at.isoformat(),
    }


@api_router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(TENANT_READ)),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Get tenant by ID.

    Protected: requires a trusted X-10 tenant context for the
    authenticated principal and the ``tenant:read`` permission. Cross-tenant
    access and missing membership are denied.
    """
    tenant = await tenant_service.get_tenant(tenant_id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "status": tenant.status,
        "created_at": tenant.created_at.isoformat(),
        "updated_at": tenant.updated_at.isoformat(),
    }


@api_router.post("/users")
async def create_user(
    user_data: Dict[str, Any],
    _: AuthenticatedPrincipal = Depends(require_permission(USER_CREATE)),
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> Dict[str, Any]:
    """Create a new user.

    Protected: requires the global ``user:create`` permission
    (PLATFORM_ADMINISTRATOR). No tenant context is required.
    """
    user = User(
        id=user_data.get("id"),
        email=user_data.get("email"),
        username=user_data.get("username"),
        status=user_data.get("status", "active"),
    )
    created_user = await user_service.create_user(user)
    return {
        "id": created_user.id,
        "email": created_user.email,
        "username": created_user.username,
        "status": created_user.status,
        "created_at": created_user.created_at.isoformat(),
        "updated_at": created_user.updated_at.isoformat(),
    }


@api_router.get("/tenants/{tenant_id}/users")
async def get_users_for_tenant(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(TENANT_READ)),
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> List[Dict[str, Any]]:
    """Get all users for a tenant.

    Protected: requires a trusted X-10 tenant context and the ``tenant:read``
    permission. Cross-tenant access and missing membership are denied.
    """
    users = await user_service.get_users_for_tenant(tenant_id)
    return [
        {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "status": user.status,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }
        for user in users
    ]


@api_router.get("/users/{user_id}/tenants")
async def get_tenants_for_user(
    user_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    membership_service: MembershipService = Depends(lambda: app_context.membership_service),
) -> List[Dict[str, Any]]:
    """Get all tenants for a user.

    Protected: self-scoped. The authenticated identity (JWT ``sub``) is
    authoritative. If the requested ``user_id`` differs from the principal's
    user ID, the request is denied with 403. The client-supplied ``user_id``
    is never treated as the authenticated identity and never silently
    substituted for the JWT identity.
    """
    if principal.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenants = await membership_service.get_tenants_for_user(principal.user_id)
    return [
        {
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat(),
        }
        for tenant in tenants
    ]
