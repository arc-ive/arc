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

from arc.db.connection import NotFoundError
from arc.domain.models import (
    KnowledgeDocument,
    KnowledgeSource,
    Tenant,
    TenantContext,
    User,
)
from arc.security.authorization import (
    KNOWLEDGE_CREATE,
    KNOWLEDGE_READ,
    ROLE_PERMISSIONS,
    TENANT_CREATE,
    TENANT_READ,
    USER_CREATE,
    AuthorizationService,
)
from arc.security.dependencies import (
    get_authenticated_principal,
    get_authorization_service,
    require_permission,
    require_tenant_permission,
)
from arc.security.models import AuthenticatedPrincipal
from arc.services.connectors import ConnectorService
from arc.services.domain import (
    MembershipService,
    TenantContextService,
    TenantService,
    UserService,
)
from arc.services.knowledge import KnowledgeService
from arc.services.pii import PiiGuardError
from arc.services.skills import SkillService


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

    @property
    def connector_service(self) -> ConnectorService:
        return self.services.get("connector_service")

    @property
    def knowledge_service(self) -> KnowledgeService:
        return self.services.get("knowledge_service")

    @property
    def skill_service(self) -> SkillService:
        return self.services.get("skill_service")


# Global application context
app_context = ApplicationContext()


# API routers
api_router = APIRouter()


@api_router.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@api_router.get("/auth/me")
async def get_authenticated_profile(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization_service: AuthorizationService = Depends(get_authorization_service),
    membership_service: MembershipService = Depends(lambda: app_context.membership_service),
) -> Dict[str, Any]:
    """Return the authenticated user's authorized profile.

    Self-scoped: identity comes exclusively from the JWT ``sub``; no
    client-supplied user ID or tenant context is accepted. The application
    role is resolved server-side from the explicit X-11 role assignments,
    and the role's permission matrix is returned so the frontend can render
    capability-aware UI.

    The returned permissions are INFORMATIONAL (UX hints) only. The backend
    re-checks authentication, tenant membership, and permissions on every
    protected request and remains the authorization authority.
    """
    role = authorization_service.role_for(principal.user_id)
    permissions = sorted(
        permission.value for permission in ROLE_PERMISSIONS.get(role, frozenset())
    )
    memberships = await membership_service.get_memberships_for_user(principal.user_id)
    return {
        "user_id": principal.user_id,
        "role": role.value if role else None,
        "permissions": permissions,
        "memberships": [
            {
                "tenant_id": membership.tenant_id,
                "role": membership.role.value,
                "created_at": membership.created_at.isoformat(),
                "updated_at": membership.updated_at.isoformat(),
            }
            for membership in memberships
        ],
    }


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


def _knowledge_document_payload(document: KnowledgeDocument) -> Dict[str, Any]:
    """Serialize a knowledge document for API responses.

    Only sanitized content is ever returned; raw content never reaches
    persistence or a response.
    """
    return {
        "id": document.id,
        "tenant_id": document.tenant_id,
        "source": document.source.value,
        "provenance": document.provenance,
        "version": document.version,
        "status": document.status.value,
        "content": document.content,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _require_path_tenant_matches_context(path_tenant_id: str, context: TenantContext) -> None:
    """Reject a request whose path tenant does not match the trusted context.

    The trusted ``TenantContext`` remains the authoritative tenant boundary:
    the service derives the tenant exclusively from it. This is a defensive
    consistency check that makes the invariant explicit and fails closed
    (403) if the path tenant ever diverges from the established context.
    """
    if path_tenant_id != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to the requested tenant is denied",
        )


@api_router.post("/tenants/{tenant_id}/knowledge")
async def create_knowledge_document(
    tenant_id: str,
    knowledge_data: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_CREATE)),
    knowledge_service: KnowledgeService = Depends(lambda: app_context.knowledge_service),
) -> Dict[str, Any]:
    """Create a knowledge document for a tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``knowledge:create`` permission. The tenant boundary is derived from
    the trusted context, never from the request payload. The path
    ``tenant_id`` is validated for consistency against the trusted context
    but is never trusted as the security boundary. Raw content is
    sanitized by the PII Guard before persistence.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    source_value = knowledge_data.get("source")
    try:
        source = KnowledgeSource(source_value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid knowledge source"
        )

    provenance = knowledge_data.get("provenance")
    content = knowledge_data.get("content")
    version = knowledge_data.get("version", 1)

    try:
        document = await knowledge_service.ingest_document(
            context=context,
            source=source,
            provenance=provenance,
            content=content,
            version=version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PiiGuardError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge ingestion failed",
        )

    return _knowledge_document_payload(document)


@api_router.get("/tenants/{tenant_id}/knowledge/{document_id}")
async def get_knowledge_document(
    tenant_id: str,
    document_id: str,
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_READ)),
    knowledge_service: KnowledgeService = Depends(lambda: app_context.knowledge_service),
) -> Dict[str, Any]:
    """Get a knowledge document by ID within a tenant.

    Protected: requires a trusted X-10 tenant context and the
        ``knowledge:read`` permission. Cross-tenant access is denied: a member
        of tenant A can never retrieve tenant B's document, and a missing
        document is indistinguishable from an inaccessible one (404). The path
        ``tenant_id`` is validated for consistency against the trusted context.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        document = await knowledge_service.get_document(context, document_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )
    return _knowledge_document_payload(document)


@api_router.get("/tenants/{tenant_id}/knowledge")
async def list_knowledge_documents(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_READ)),
    knowledge_service: KnowledgeService = Depends(lambda: app_context.knowledge_service),
) -> List[Dict[str, Any]]:
    """List knowledge documents for a tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``knowledge:read`` permission. Only the caller's own tenant documents
    are returned. The path ``tenant_id`` is validated for consistency
    against the trusted context.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    documents = await knowledge_service.list_documents(context)
    return [_knowledge_document_payload(document) for document in documents]
