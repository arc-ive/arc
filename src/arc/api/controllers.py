"""API controllers for Arc multi-tenant foundation."""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status

from arc.domain.models import Tenant, User, Membership, UserRole, TenantContext
from arc.services.domain import (
    TenantService,
    UserService,
    MembershipService,
    TenantContextService,
)
from arc.repositories import TenantRepository, UserRepository, MembershipRepository


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
        return self.services.get('tenant_service')

    @property
    def user_service(self) -> UserService:
        return self.services.get('user_service')

    @property
    def membership_service(self) -> MembershipService:
        return self.services.get('membership_service')

    @property
    def tenant_context_service(self) -> TenantContextService:
        return self.services.get('tenant_context_service')


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
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Create a new tenant."""
    tenant = Tenant(
        id=tenant_data.get("id"),
        name=tenant_data.get("name"),
        status=tenant_data.get("status", "active")
    )
    created_tenant = await tenant_service.create_tenant(tenant)
    return {
        "id": created_tenant.id,
        "name": created_tenant.name,
        "status": created_tenant.status,
        "created_at": created_tenant.created_at.isoformat(),
        "updated_at": created_tenant.updated_at.isoformat()
    }


@api_router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Get tenant by ID."""
    tenant = await tenant_service.get_tenant(tenant_id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "status": tenant.status,
        "created_at": tenant.created_at.isoformat(),
        "updated_at": tenant.updated_at.isoformat()
    }


@api_router.post("/users")
async def create_user(
    user_data: Dict[str, Any],
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> Dict[str, Any]:
    """Create a new user."""
    user = User(
        id=user_data.get("id"),
        email=user_data.get("email"),
        username=user_data.get("username"),
        status=user_data.get("status", "active")
    )
    created_user = await user_service.create_user(user)
    return {
        "id": created_user.id,
        "email": created_user.email,
        "username": created_user.username,
        "status": created_user.status,
        "created_at": created_user.created_at.isoformat(),
        "updated_at": created_user.updated_at.isoformat()
    }


@api_router.post("/users/{user_id}/tenants/{tenant_id}/memberships")
async def create_membership(
    user_id: str,
    tenant_id: str,
    membership_data: Dict[str, Any],
    user_service: UserService = Depends(lambda: app_context.user_service),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Associate a user with a tenant."""
    role_str = membership_data.get("role", "member")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role_str}"
        )

    membership = await user_service.associate_user_with_tenant(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        membership_id=membership_data.get("id")
    )

    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "tenant_id": membership.tenant_id,
        "role": membership.role.value,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat()
    }


@api_router.get("/tenants/{tenant_id}/users")
async def get_users_for_tenant(
    tenant_id: str,
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> List[Dict[str, Any]]:
    """Get all users for a tenant."""
    users = await user_service.get_users_for_tenant(tenant_id)
    return [
        {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "status": user.status,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat()
        }
        for user in users
    ]


@api_router.get("/users/{user_id}/tenants")
async def get_tenants_for_user(
    user_id: str,
    membership_service: MembershipService = Depends(lambda: app_context.membership_service),
) -> List[Dict[str, Any]]:
    """Get all tenants for a user."""
    tenants = await membership_service.get_tenants_for_user(user_id)
    return [
        {
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat()
        }
        for tenant in tenants
    ]


@api_router.post("/tenant-contexts")
async def create_tenant_context(
    context_data: Dict[str, Any],
    tenant_context_service: TenantContextService = Depends(lambda: app_context.tenant_context_service),
) -> Dict[str, Any]:
    """Create a tenant context."""
    role_str = context_data.get("role", "member")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role_str}"
        )

    context = await tenant_context_service.create_tenant_context(
        tenant_id=context_data.get("tenant_id"),
        user_id=context_data.get("user_id"),
        role=role
    )

    return {
        "tenant_id": context.tenant_id,
        "tenant_name": context.tenant_name,
        "user_id": context.user_id,
        "role": context.role.value
    }


@api_router.get("/tenant-contexts/validate")
async def validate_tenant_context(
    tenant_id: str,
    user_id: str,
    role: str,
    tenant_context_service: TenantContextService = Depends(lambda: app_context.tenant_context_service),
) -> Dict[str, Any]:
    """Validate a tenant context."""
    try:
        role_enum = UserRole(role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}"
        )

    context = TenantContext(
        tenant_id=tenant_id,
        tenant_name="",
        user_id=user_id,
        role=role_enum
    )

    is_valid = await tenant_context_service.validate_context(context)

    return {"is_valid": is_valid}