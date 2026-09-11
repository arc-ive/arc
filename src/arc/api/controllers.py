"""API controllers for Arc multi-tenant foundation.

Security-sensitive operations are protected by X-11 authentication and
application RBAC:

- Tenant and user provisioning require a global permission
  (PLATFORM_ADMINISTRATOR only).
- Tenant-scoped reads require a trusted X-10 tenant context and the
  ``tenant:read`` permission.
- Tenant-scoped Skills management requires a trusted X-10 tenant context
  and the approved ``skill:create``/``skill:read``/``skill:delete``
  permissions.
- Tenant-scoped access to the platform-owned AI Tool catalog requires a
  trusted X-10 tenant context and the approved ``tool:read`` /
  ``tool:execute`` permissions; per-tool authorization additionally
  requires every permission declared by the tool.
- Identity-scoped listing is self-only: the requested ``user_id`` must
  equal the authenticated principal's user ID (JWT ``sub``).

Privileged and identity-sensitive development endpoints (membership
provisioning) are isolated in ``arc.api.dev_controllers``.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from arc.db.connection import DatabaseError, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    AgentExecutionResult,
    ApprovalStatus,
    ConnectorProvider,
    IntelligenceAnswer,
    KnowledgeDocument,
    KnowledgeMatch,
    KnowledgeSource,
    Skill,
    SkillExecutionResult,
    SkillExecutionStepOutcome,
    SkillStatus,
    Tenant,
    TenantContext,
    ToolExecutionStatus,
    User,
    UserRole,
    WebhookEvent,
)
from arc.security.authorization import (
    AGENT_EXECUTE,
    APPROVAL_DECIDE,
    APPROVAL_READ,
    CONNECTOR_CREATE,
    CONNECTOR_MANAGE_CREDENTIALS,
    CONNECTOR_READ,
    CONNECTOR_SYNC,
    KNOWLEDGE_CREATE,
    KNOWLEDGE_READ,
    MEMBERSHIP_CREATE,
    OBSERVABILITY_PLATFORM_READ,
    OBSERVABILITY_READ,
    ROLE_PERMISSIONS,
    SKILL_CREATE,
    SKILL_DELETE,
    SKILL_EXECUTE,
    SKILL_READ,
    SKILL_UPDATE,
    TENANT_CREATE,
    TENANT_LIST,
    TENANT_READ,
    TENANT_UPDATE,
    TOOL_EXECUTE,
    TOOL_READ,
    USER_CREATE,
    USER_READ,
    WEBHOOK_PROCESS,
    WEBHOOK_READ,
    AuthorizationService,
)
from arc.security.dependencies import (
    get_authenticated_principal,
    get_authorization_service,
    require_permission,
    require_tenant_permission,
)
from arc.security.models import AuthenticatedPrincipal
from arc.services.agent import AgentExecutionService
from arc.services.approvals import (
    ApprovalConsumedError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalSelfDecisionError,
    ApprovalStateError,
    HumanApprovalService,
)
from arc.services.connector_credentials import (
    ConnectorCredentialError,
    ConnectorCredentialService,
)
from arc.services.connector_sync import ConnectorSyncError, ConnectorSyncService
from arc.services.connectors import ConnectorService
from arc.services.domain import (
    MembershipService,
    TenantContextService,
    TenantService,
    UserService,
)
from arc.services.embeddings import EmbeddingError
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.knowledge import KnowledgeService
from arc.services.llm import LlmError
from arc.services.observability import ObservabilityService
from arc.services.pii import PiiGuardError
from arc.services.retrieval import RetrievalService
from arc.services.skill_execution import SkillExecutionService
from arc.services.skills import SkillService
from arc.services.tools import (
    ToolDefinition,
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionService,
    ToolNotFoundError,
    ToolValidationError,
)
from arc.services.webhook_ingestion import (
    MAX_BODY_BYTES,
    WebhookAuthenticationError,
    WebhookIngestionError,
    WebhookIngestionService,
    WebhookValidationError,
)
from arc.services.webhook_pipeline import (
    WebhookPipelineService,
    WebhookProcessingError,
)

logger = logging.getLogger("arc.api.controllers")


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
    def connector_sync_service(self) -> ConnectorSyncService:
        return self.services.get("connector_sync_service")

    @property
    def connector_credential_service(self) -> ConnectorCredentialService:
        return self.services.get("connector_credential_service")

    @property
    def knowledge_service(self) -> KnowledgeService:
        return self.services.get("knowledge_service")

    @property
    def retrieval_service(self) -> RetrievalService:
        return self.services.get("retrieval_service")

    @property
    def intelligence_service(self) -> UnifiedIntelligenceService:
        return self.services.get("intelligence_service")

    @property
    def skill_service(self) -> SkillService:
        return self.services.get("skill_service")

    @property
    def skill_execution_service(self) -> SkillExecutionService:
        return self.services.get("skill_execution_service")

    @property
    def agent_service(self) -> AgentExecutionService:
        return self.services.get("agent_service")

    @property
    def tool_service(self) -> ToolExecutionService:
        return self.services.get("tool_service")

    @property
    def webhook_ingestion_service(self) -> WebhookIngestionService:
        return self.services.get("webhook_ingestion_service")

    @property
    def webhook_pipeline_service(self) -> WebhookPipelineService:
        return self.services.get("webhook_pipeline_service")

    @property
    def observability_service(self):
        return self.services.get("observability_service")

    @property
    def human_approval_service(self):
        return self.services.get("human_approval_service")


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

    Self-scoped: identity comes exclusively from the validated session or
    JWT ``sub``; no client-supplied user ID or tenant context is accepted.
    The application role is resolved server-side from the explicit X-11
    role assignments, and the role's permission matrix is returned so the
    frontend can render capability-aware UI.

    The returned permissions are INFORMATIONAL (UX hints) only. The backend
    re-checks authentication, tenant membership, and permissions on every
    protected request and remains the authorization authority.
    """
    role = authorization_service.role_for(principal.user_id)
    permissions = sorted(permission.value for permission in ROLE_PERMISSIONS.get(role, frozenset()))
    memberships = await membership_service.get_memberships_for_user(principal.user_id)

    # Fetch the full user profile for email/display_name/avatar_url.
    # Falls back gracefully if user is not in the database (JWT-only flow).
    user = None
    try:
        user = await app_context.user_service.get_user(principal.user_id)
    except NotFoundError:
        pass

    return {
        "user_id": principal.user_id,
        "email": user.email if user else None,
        "display_name": user.display_name if user else None,
        "avatar_url": user.avatar_url if user else None,
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
    principal: AuthenticatedPrincipal = Depends(require_permission(TENANT_CREATE)),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Create a new tenant.

    Protected: requires the global ``tenant:create`` permission
    (PLATFORM_ADMINISTRATOR). No tenant context is required.

    The authenticated creator is automatically assigned OWNER membership
    for the new tenant. The tenant and membership are created atomically.
    """
    tenant = Tenant(
        id=tenant_data.get("id"),
        name=tenant_data.get("name"),
        status=tenant_data.get("status", "active"),
    )
    try:
        created_tenant = await tenant_service.create_tenant_with_owner(tenant, principal.user_id)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant already exists",
        )
    except DatabaseError as e:
        # ForeignKeyViolation (user_id not in users table) surfaces here as
        # DatabaseError. Return 400 so the caller gets an actionable message
        # instead of a opaque 500.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Failed to create tenant: the authenticated user does not exist "
                "in the users table. Create the user first."
            ),
        ) from e
    return {
        "id": created_tenant.id,
        "name": created_tenant.name,
        "status": created_tenant.status,
        "created_at": created_tenant.created_at.isoformat(),
        "updated_at": created_tenant.updated_at.isoformat(),
    }


@api_router.get("/platform/tenants")
async def list_platform_tenants(
    _: AuthenticatedPrincipal = Depends(require_permission(TENANT_LIST)),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> List[Dict[str, Any]]:
    """List all tenants — PLATFORM_ADMINISTRATOR only.

    Protected: requires the global ``tenant:list`` permission
    (PLATFORM_ADMINISTRATOR). Returns all tenants regardless of membership.
    No tenant context is required.
    """
    tenants = await tenant_service.list_all_tenants()
    return [
        {
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "industry": tenant.industry,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat(),
        }
        for tenant in tenants
    ]


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
        "industry": tenant.industry,
        "address": tenant.address,
        "phone": tenant.phone,
        "website": tenant.website,
        "logo_url": tenant.logo_url,
        "created_at": tenant.created_at.isoformat(),
        "updated_at": tenant.updated_at.isoformat(),
    }


@api_router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    tenant_data: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(TENANT_UPDATE)),
    tenant_service: TenantService = Depends(lambda: app_context.tenant_service),
) -> Dict[str, Any]:
    """Update tenant company configuration.

    Protected: requires a trusted X-10 tenant context for the
    authenticated principal and the ``tenant:update`` permission.
    Cross-tenant access and missing membership are denied.
    """
    existing = await tenant_service.get_tenant(tenant_id)
    updated = Tenant(
        id=existing.id,
        name=tenant_data.get("name", existing.name),
        status=existing.status,
        industry=tenant_data.get("industry", existing.industry),
        address=tenant_data.get("address", existing.address),
        phone=tenant_data.get("phone", existing.phone),
        website=tenant_data.get("website", existing.website),
        logo_url=tenant_data.get("logo_url", existing.logo_url),
        created_at=existing.created_at,
        updated_at=datetime.now(timezone.utc),
    )
    result = await tenant_service.update_tenant(updated)
    return {
        "id": result.id,
        "name": result.name,
        "status": result.status,
        "industry": result.industry,
        "address": result.address,
        "phone": result.phone,
        "website": result.website,
        "logo_url": result.logo_url,
        "created_at": result.created_at.isoformat(),
        "updated_at": result.updated_at.isoformat(),
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
    try:
        created_user = await user_service.create_user(user)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )
    return {
        "id": created_user.id,
        "email": created_user.email,
        "username": created_user.username,
        "status": created_user.status,
        "created_at": created_user.created_at.isoformat(),
        "updated_at": created_user.updated_at.isoformat(),
    }


@api_router.get("/platform/users")
async def list_platform_users(
    _: AuthenticatedPrincipal = Depends(require_permission(USER_READ)),
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> List[Dict[str, Any]]:
    """List all provisioned users — PLATFORM_ADMINISTRATOR only.

    Protected: requires the global ``user:read`` permission
    (PLATFORM_ADMINISTRATOR). Returns all users regardless of tenant
    membership. No tenant context is required.
    """
    users = await user_service.list_all_users()
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


@api_router.post("/tenants/{tenant_id}/memberships")
async def create_membership(
    tenant_id: str,
    membership_data: Dict[str, Any],
    _: AuthenticatedPrincipal = Depends(require_permission(MEMBERSHIP_CREATE)),
    user_service: UserService = Depends(lambda: app_context.user_service),
) -> Dict[str, Any]:
    """Create a membership associating a user with a tenant.

    Protected: requires the global ``membership:create`` permission
    (PLATFORM_ADMINISTRATOR). The target ``user_id`` and ``role`` are
    provisioning inputs, not the caller's identity. The caller's identity
    comes from the authenticated principal (JWT ``sub``).
    """
    user_id = membership_data.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_id is required",
        )

    role_str = membership_data.get("role", "member")
    try:
        role = UserRole(role_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role_str}"
        )

    try:
        membership = await user_service.associate_user_with_tenant(
            user_id=user_id, tenant_id=tenant_id, role=role
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "tenant_id": membership.tenant_id,
        "role": membership.role.value,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }


@api_router.delete("/tenants/{tenant_id}/memberships/{user_id}")
async def delete_membership(
    tenant_id: str,
    user_id: str,
    _: AuthenticatedPrincipal = Depends(require_permission(MEMBERSHIP_CREATE)),
    membership_service: MembershipService = Depends(lambda: app_context.membership_service),
) -> Dict[str, Any]:
    """Remove a user's membership from a tenant.

    Protected: requires the global ``membership:create`` permission
    (PLATFORM_ADMINISTRATOR). Only an existing membership can be removed.
    """
    if not await membership_service.membership_exists(user_id, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No membership found for user {user_id} in tenant {tenant_id}",
        )

    await membership_service.remove_membership(user_id, tenant_id)
    return {"detail": "Membership removed"}


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
            "industry": tenant.industry,
            "address": tenant.address,
            "phone": tenant.phone,
            "website": tenant.website,
            "logo_url": tenant.logo_url,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat(),
        }
        for tenant in tenants
    ]


def _skill_response(skill: Skill) -> Dict[str, Any]:
    """Serialize a Skill for the API response envelope."""
    return {
        "id": skill.id,
        "tenant_id": skill.tenant_id,
        "name": skill.name,
        "version": skill.version,
        "purpose": skill.purpose,
        "status": skill.status.value,
        "inputs": skill.inputs,
        "preconditions": skill.preconditions,
        "steps": skill.steps,
        "constraints": skill.constraints,
        "allowed_tools": skill.allowed_tools,
        "approval_required": skill.approval_required,
        "expected_output": skill.expected_output,
        "failure_behavior": skill.failure_behavior,
        "provenance": skill.provenance,
        "risk": skill.risk,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


@api_router.post("/skills")
async def create_skill(
    skill_data: Dict[str, Any],
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(SKILL_CREATE)),
    skill_service: SkillService = Depends(lambda: app_context.skill_service),
) -> Dict[str, Any]:
    """Create a new Skill for the trusted tenant.

    Protected: requires a trusted X-10 tenant context (the client-supplied
    ``tenant_id`` is request input only and is verified against the
    authenticated principal's persisted membership) and the ``skill:create``
    permission. The supplied ``tenant_id`` is explicitly validated for
    consistency against the trusted context (403 on mismatch); the trusted
    context remains authoritative for ownership and persistence. The
    SkillService generates the Skill ID.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        status_value = SkillStatus(skill_data.get("status", "active"))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill status")

    skill = Skill(
        id="unassigned",
        tenant_id=context.tenant_id,
        name=skill_data.get("name"),
        purpose=skill_data.get("purpose"),
        version=skill_data.get("version", "1"),
        inputs=skill_data.get("inputs", []),
        preconditions=skill_data.get("preconditions", []),
        steps=skill_data.get("steps", []),
        constraints=skill_data.get("constraints", []),
        allowed_tools=skill_data.get("allowed_tools", []),
        approval_required=skill_data.get("approval_required", False),
        expected_output=skill_data.get("expected_output"),
        failure_behavior=skill_data.get("failure_behavior"),
        provenance=skill_data.get("provenance"),
        risk=skill_data.get("risk"),
        status=status_value,
    )
    try:
        created_skill = await skill_service.create_skill(context, skill)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill '{skill.name}' version '{skill.version}' already exists in this tenant.",
        )
    return _skill_response(created_skill)


@api_router.get("/skills")
async def list_skills(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(SKILL_READ)),
    skill_service: SkillService = Depends(lambda: app_context.skill_service),
) -> List[Dict[str, Any]]:
    """List all Skills belonging to the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the ``skill:read``
    permission. The supplied ``tenant_id`` is explicitly validated for
    consistency against the trusted context (403 on mismatch). Only Skills
    of the trusted tenant are returned.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    skills = await skill_service.list_skills(context)
    return [_skill_response(skill) for skill in skills]


@api_router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(SKILL_READ)),
    skill_service: SkillService = Depends(lambda: app_context.skill_service),
) -> Dict[str, Any]:
    """Get a Skill belonging to the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the ``skill:read``
    permission. The supplied ``tenant_id`` is explicitly validated for
    consistency against the trusted context (403 on mismatch). A Skill
    outside the trusted tenant is indistinguishable from a missing Skill
    (404): cross-tenant access never reveals existence.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        skill = await skill_service.get_skill(context, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return _skill_response(skill)


@api_router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    skill_data: Dict[str, Any],
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(SKILL_UPDATE)),
    skill_service: SkillService = Depends(lambda: app_context.skill_service),
) -> Dict[str, Any]:
    """Update an existing Skill within the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``skill:update`` permission. The supplied ``tenant_id`` is explicitly
    validated for consistency against the trusted context (403 on
    mismatch). The trusted context remains authoritative for ownership
    and persistence. A Skill outside the trusted tenant is
    indistinguishable from a missing Skill (404): cross-tenant access
    never reveals existence.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        existing = await skill_service.get_skill(context, skill_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")

    try:
        status_value = SkillStatus(skill_data.get("status", existing.status.value))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill status")

    from dataclasses import replace

    updated_skill = replace(
        existing,
        name=skill_data.get("name", existing.name),
        purpose=skill_data.get("purpose", existing.purpose),
        version=skill_data.get("version", existing.version),
        inputs=skill_data.get("inputs", existing.inputs),
        preconditions=skill_data.get("preconditions", existing.preconditions),
        steps=skill_data.get("steps", existing.steps),
        constraints=skill_data.get("constraints", existing.constraints),
        allowed_tools=skill_data.get("allowed_tools", existing.allowed_tools),
        approval_required=skill_data.get("approval_required", existing.approval_required),
        expected_output=skill_data.get("expected_output", existing.expected_output),
        failure_behavior=skill_data.get("failure_behavior", existing.failure_behavior),
        provenance=skill_data.get("provenance", existing.provenance),
        risk=skill_data.get("risk", existing.risk),
        status=status_value,
    )

    try:
        result = await skill_service.update_skill(context, updated_skill)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill '{updated_skill.name}' version '{updated_skill.version}' "
            f"already exists in this tenant.",
        )
    return _skill_response(result)


@api_router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: str,
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(SKILL_DELETE)),
    skill_service: SkillService = Depends(lambda: app_context.skill_service),
) -> None:
    """Delete a Skill belonging to the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``skill:delete`` permission. The supplied ``tenant_id`` is explicitly
    validated for consistency against the trusted context (403 on mismatch).
    Deletion is tenant-scoped: a Skill outside the trusted tenant is not
    deleted and the response is indistinguishable from a successful no-op
    delete.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    await skill_service.delete_skill(context, skill_id)
    return None


def _skill_execution_response(result: SkillExecutionResult) -> Dict[str, Any]:
    """Serialize a SkillExecutionResult for the API response envelope.

    Steps preserve the engine's structured outcomes: successful steps
    carry their tool version and output; failed steps carry only the
    safe ``error_kind``. No raw exceptions or internal details cross
    this boundary.
    """
    response = {
        "id": result.id,
        "tenant_id": result.tenant_id,
        "principal_id": result.principal_id,
        "skill_id": result.skill_id,
        "skill_name": result.skill_name,
        "skill_version": result.skill_version,
        "status": result.status.value,
        "error_kind": result.error_kind,
        "steps": [
            {
                "sequence": step.sequence,
                "tool_name": step.tool_name,
                "status": step.status.value,
                "tool_version": step.tool_version,
                "output": step.output,
                "error_kind": step.error_kind,
            }
            for step in result.steps
        ],
        "created_at": result.created_at.isoformat(),
    }
    if result.approval_id is not None:
        response["approval_id"] = result.approval_id
    return response


@api_router.post("/skills/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    tenant_id: str,
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(require_tenant_permission(SKILL_EXECUTE)),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    execution_service: SkillExecutionService = Depends(lambda: app_context.skill_execution_service),
) -> Dict[str, Any]:
    """Execute a Skill within the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``skill:execute`` permission. The supplied ``tenant_id`` is explicitly
    validated for consistency against the trusted context (403 on
    mismatch). The controller adds NO execution logic of its own: it
    resolves nothing, authorizes no tools, and never touches the tool
    registry or handlers. Proposed tool calls are validated and executed
    exclusively by ``SkillExecutionService``, which delegates every action
    to ``ToolExecutionService`` (platform whitelist, per-tool RBAC,
    execution policy, input validation, tenant-scoped audit).

    Controlled outcomes (denied, failed, blocked, succeeded) are returned
    as structured 200 responses. A Skill outside the trusted tenant is
    indistinguishable from a missing Skill (404); malformed request
    metadata is rejected with 400 before any execution.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be an object"
        )

    try:
        result = await execution_service.execute(
            context,
            principal,
            skill_id,
            body.get("tool_calls"),
            body.get("satisfied_preconditions", []),
            authorization,
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _skill_execution_response(result)


def _agent_run_response(result: AgentExecutionResult) -> Dict[str, Any]:
    """Serialize an AgentExecutionResult for the API response envelope.

    Steps preserve the bounded orchestration outcomes; no raw model
    output, exceptions, or internal details cross this boundary.
    """
    response = {
        "id": result.id,
        "tenant_id": result.tenant_id,
        "principal_id": result.principal_id,
        "goal": result.goal,
        "status": result.status.value,
        "error_kind": result.error_kind,
        "steps": [
            {
                "sequence": step.sequence,
                "skill_id": step.skill_id,
                "skill_name": step.skill_name,
                "status": step.status.value,
                "error_kind": step.error_kind,
            }
            for step in result.steps
        ],
        "created_at": result.created_at.isoformat(),
    }
    if result.approval_id is not None:
        response["approval_id"] = result.approval_id
    return response


async def _require_tenant_permission_from_body(
    body: Optional[Any] = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
) -> TenantContext:
    """Body-aware tenant context + permission check for /agent/runs.

    Reads ``tenant_id`` from the JSON request body instead of query params,
    then delegates to the trusted tenant context service and checks the
    ``AGENT_EXECUTE`` permission.
    """
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be an object"
        )

    tenant_id = body.get("tenant_id")
    if not tenant_id or not isinstance(tenant_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must include a non-empty 'tenant_id' string",
        )

    try:
        context = await app_context.tenant_context_service.create_tenant_context(
            tenant_id=tenant_id,
            user_id=principal.user_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant context"
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to the requested tenant is denied",
        )

    if not authorization.has_permission(principal, AGENT_EXECUTE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return context


@api_router.post("/agent/runs")
async def run_agent(
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(_require_tenant_permission_from_body),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    agent_service: AgentExecutionService = Depends(lambda: app_context.agent_service),
) -> Dict[str, Any]:
    """Run one bounded Agent workflow within the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``agent:execute`` permission. The supplied ``tenant_id`` is explicitly
    validated for consistency against the trusted context (403 on
    mismatch). The controller adds NO orchestration of its own: Skill
    selection is decided by the configured decision-capable LLM provider,
    strictly validated against the trusted tenant's own catalog, and
    executed exclusively through ``SkillExecutionService``. The Agent can
    never touch tools, handlers, or registries directly.

    Canonical request contract::

        POST /agent/runs
        {
            "tenant_id": "<tenant-id>",
            "goal": "<agent goal>"
        }

    Controlled outcomes (succeeded, failed, approval_required,
    max_steps_reached) are returned as structured 200 responses;
    malformed request metadata is rejected with 400.
    """
    tenant_id = body.get("tenant_id")
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        result = await agent_service.run(
            context,
            principal,
            body.get("goal"),
            authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Best-effort agent execution trace persistence (PRD 17 O-6).
    # A telemetry persistence failure must never fail the business response.
    try:
        from arc.domain.models import AgentRunRecord, AgentRunRecordStep

        trace_record = AgentRunRecord(
            id=result.id,
            tenant_id=result.tenant_id,
            principal_id=result.principal_id,
            goal=result.goal,
            status=result.status.value,
            error_kind=result.error_kind,
            steps=[
                AgentRunRecordStep(
                    sequence=step.sequence,
                    skill_id=step.skill_id,
                    skill_name=step.skill_name,
                    status=step.status.value,
                    error_kind=step.error_kind,
                )
                for step in result.steps
            ],
            created_at=result.created_at,
        )
        await app_context.observability_service.record_agent_run(trace_record)
    except Exception:
        logger.warning("agent_run_trace_persistence_failed run_id=%s", result.id)

    return _agent_run_response(result)


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
        "external_id": document.external_id,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _get_credential_service_or_503() -> ConnectorCredentialService:
    """Resolve the credential management service or return 503.

    The credential management service requires CONNECTOR_ENCRYPTION_KEY
    to be configured. When it is absent the service is intentionally
    unavailable: ENV-only credential mode remains active for connector
    sync, but credential management API operations cannot function
    without encryption.  This dependency returns 503 instead of leaking
    an internal KeyError as 500.
    """
    try:
        service = app_context.connector_credential_service
    except KeyError:
        service = None
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Connector credential management requires CONNECTOR_ENCRYPTION_KEY to be configured"
            ),
        )
    return service


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


def _knowledge_match_response(match: KnowledgeMatch) -> Dict[str, Any]:
    """Serialize a retrieval match for API responses.

    Only sanitized content is ever returned; raw content never reaches
    persistence or a response.
    """
    return {
        "chunk_id": match.chunk_id,
        "document_id": match.document_id,
        "tenant_id": match.tenant_id,
        "content": match.content,
        "source": match.source.value,
        "provenance": match.provenance,
        "document_version": match.document_version,
        "sequence": match.sequence,
        "similarity": match.similarity,
    }


@api_router.get("/tenants/{tenant_id}/knowledge/search")
async def search_knowledge(
    tenant_id: str,
    query: str,
    limit: int = 5,
    source_type: Optional[str] = Query(default=None),
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_READ)),
    retrieval_service: RetrievalService = Depends(lambda: app_context.retrieval_service),
):
    """Search sanitized knowledge chunks within a tenant (Secure RAG).

    Requires the same ``knowledge:read`` permission as document reads:
    retrieval is a read of the tenant's own knowledge, not a new
    capability. The trusted X-10 tenant context is the only tenant
    boundary; the path tenant is defensively required to match it (403
    otherwise). Chunks are never exposed across tenants, and only
    already-sanitized content is ever returned.

    The production embedding provider is a deferred decision; the current
    deterministic provider returns results that are correct for
    development and test suites but are NOT semantically meaningful.

    When ``source_type`` is provided, only documents whose source matches
    are included in the candidate set.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    if not query or not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query cannot be empty",
        )
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search limit must be between 1 and 50",
        )

    resolved_source_type: Optional[KnowledgeSource] = None
    if source_type is not None:
        try:
            resolved_source_type = KnowledgeSource(source_type)
        except ValueError:
            valid_values = [s.value for s in KnowledgeSource]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_type. Must be one of: {', '.join(valid_values)}",
            )

    try:
        matches = await retrieval_service.search(
            context, query, limit=limit, source_type=resolved_source_type
        )
    except EmbeddingError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge search failed",
        )
    return [_knowledge_match_response(match) for match in matches]


def _intelligence_answer_response(answer: IntelligenceAnswer) -> Dict[str, Any]:
    """Serialize an IntelligenceAnswer for API responses.

    Only the answer text, citation references, and retrieval metadata are
    exposed. The LLM's raw prompt is never exposed, and no security
    internals (prompt construction, provider identity, error details) are
    included.
    """
    return {
        "request_id": answer.request_id,
        "tenant_id": answer.tenant_id,
        "principal_id": answer.principal_id,
        "query": answer.query,
        "answer": answer.answer,
        "citations": answer.citations,
        "retrieval_method": answer.retrieval_method.value,
        "context_used": answer.context_used,
        "tool_executions": answer.tool_executions,
    }


@api_router.post("/tenants/{tenant_id}/intelligence/query")
async def query_unified_intelligence(
    tenant_id: str,
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_READ)),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    intelligence_service: UnifiedIntelligenceService = Depends(
        lambda: app_context.intelligence_service
    ),
) -> Dict[str, Any]:
    """Reason over the tenant's approved knowledge (Unified Intelligence).

    The first Unified Intelligence slice (PRD 12/26, TRD 8/10/39): a
    tenant-scoped request is authenticated, the tenant boundary comes
    from the trusted X-10 context, retrieval produces an Approved Context
    Contract (``knowledge:read`` is reused: reasoning is a read-class
    operation over the tenant's own knowledge, not a new capability), and
    the LLM provider reasons over ONLY that approved context.

    The LLM never receives raw documents, vectors, authorization state, or
    cross-tenant content. When no approved context matches, the answer is
    ``None`` (the LLM is not invoked and nothing is invented). Fail closed:
    embedding or LLM failures map to a generic 500 with no internals
    leaked.

    The request body is explicitly validated as a JSON object before any
    field access, ``query`` as a string before ``strip()``, and ``limit``
    as a non-boolean integer. Malformed inputs return 400, never 500.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    if body is None or not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object",
        )

    query = body.get("query")
    limit = body.get("limit", 5)

    if not isinstance(query, str) or not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must be a non-empty string",
        )
    # bool is a subclass of int: a boolean limit must be rejected
    # explicitly, never accepted as an integer.
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be an integer between 1 and 50",
        )

    try:
        answer = await intelligence_service.answer_query(
            context,
            query,
            limit=limit,
            principal=principal,
            authorization=authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (EmbeddingError, LlmError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Intelligence query failed",
        )
    return _intelligence_answer_response(answer)


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

    Request body fields:

    - ``source``: required, KnowledgeSource enum value.
    - ``provenance``: required, attribution string.
    - ``content``: required, raw document content (PII-sanitized before
      persistence).
    - ``version``: optional, defaults to 1.
    - ``external_id``: optional, stable writer-supplied identifier for
      logical document identity (ADR-003). When provided, re-ingestion
      of the same ``(tenant_id, source, external_id)`` with identical
      sanitized content is idempotent; changed content bumps the version
      in-place.
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
    external_id = knowledge_data.get("external_id")

    try:
        document = await knowledge_service.ingest_document(
            context=context,
            source=source,
            provenance=provenance,
            content=content,
            version=version,
            external_id=external_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PiiGuardError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge ingestion failed",
        )
    except EmbeddingError:
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


def _tool_definition_payload(tool: ToolDefinition) -> Dict[str, Any]:
    """Serialize an approved tool definition for the catalog API response.

    Only safe metadata is exposed: never the handler or any execution
    detail. The catalog is platform-owned: tenants can read it but can
    never register, modify, or upload tools through it.
    """
    return {
        "name": tool.name,
        "version": tool.version,
        "description": tool.description,
        "risk_level": tool.risk_level.value,
        "required_permissions": sorted(
            permission.value for permission in tool.required_permissions
        ),
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }


def get_tool_service() -> ToolExecutionService:
    """Return the shared AI Tool execution service (platform-owned catalog).

    Exposed as a named dependency so tests can override the catalog
    service; the catalog itself is always platform-owned and code-defined.
    """
    return app_context.tool_service


@api_router.get("/tenants/{tenant_id}/tools")
async def list_tools(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(TOOL_READ)),
    tool_service: ToolExecutionService = Depends(get_tool_service),
) -> List[Dict[str, Any]]:
    """List the platform-owned AI Tool catalog for the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the ``tool:read``
    permission. The path ``tenant_id`` is validated for consistency against
    the trusted context (403 on mismatch). Tenants gain tenant-scoped
    access to the platform-owned catalog; the catalog is identical for
    every tenant and contains only safe metadata. Tenants cannot register,
    upload, or modify tools.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    tools = tool_service.list_tools(context)
    return [_tool_definition_payload(tool) for tool in tools]


@api_router.post("/tenants/{tenant_id}/tools/{name}/execute")
async def execute_tool(
    tenant_id: str,
    name: str,
    body: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(TOOL_EXECUTE)),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    tool_service: ToolExecutionService = Depends(get_tool_service),
) -> Dict[str, Any]:
    """Execute an approved AI Tool within the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``tool:execute`` permission. The path ``tenant_id`` is validated for
    consistency against the trusted context (403 on mismatch) but is
    request input only; the tenant boundary is derived exclusively from
    the trusted context. Per-tool authorization is enforced fail-closed
    inside the service: the caller must also hold every permission
    declared by the tool, otherwise execution is denied (403). Only
    platform-owned, code-defined tools are executable. Errors are generic
    and safe: no internal details are exposed.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    raw_input = body.get("input", {})
    approval_id = body.get("approval_id")

    try:
        result = await tool_service.execute_tool(
            context,
            principal,
            name,
            raw_input,
            authorization,
            approval_id=approval_id,
        )
    except ToolNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    except ToolValidationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tool input")
    except ToolDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tool execution is not permitted",
        )
    except ToolExecutionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tool execution failed",
        )

    return {
        "tool": result.tool_name,
        "version": result.tool_version,
        "output": result.output,
    }


def _connector_payload(config) -> Dict[str, Any]:
    """Serialize a ConnectorConfig without exposing any credential material."""
    return {
        "id": config.id,
        "tenant_id": config.tenant_id,
        "provider": config.provider.value,
        "name": config.name,
        "target": config.target,
        "status": config.status.value,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
    }


@api_router.get("/tenants/{tenant_id}/connectors")
async def list_connectors(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_READ)),
    connector_service: ConnectorService = Depends(lambda: app_context.connector_service),
) -> List[Dict[str, Any]]:
    """List the caller's tenant connector configurations.

    Protected: requires a trusted X-10 tenant context and the
    ``connector:read`` permission. The path ``tenant_id`` is validated for
    consistency against the trusted context (403 on mismatch); the trusted
    context remains authoritative for ownership. No credential material is
    ever returned.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    connectors = await connector_service.list_connectors(context)
    return [_connector_payload(connector) for connector in connectors]


@api_router.post("/tenants/{tenant_id}/connectors")
async def create_connector(
    connector_data: Dict[str, Any],
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_CREATE)),
    connector_service: ConnectorService = Depends(lambda: app_context.connector_service),
) -> Dict[str, Any]:
    """Create a connector configuration for the trusted tenant.

    Protected: requires a trusted X-10 tenant context and the
    ``connector:create`` permission. The provider must be one of the
    code-defined approved providers (GitHub, Slack, Linear per ADR-002).
    The path ``tenant_id`` is validated for consistency against the trusted
    context (403 on mismatch). Credentials are never accepted or returned.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider = ConnectorProvider(connector_data.get("provider"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    name = connector_data.get("name")
    if not isinstance(name, str) or not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connector name cannot be empty",
        )

    target = connector_data.get("target", "")

    try:
        created = await connector_service.create_connector(context, provider, name, target)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector already exists",
        )
    return _connector_payload(created)


@api_router.post("/tenants/{tenant_id}/connectors/{connector_id}/sync")
async def sync_connector(
    connector_id: str,
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_SYNC)),
    connector_sync_service: ConnectorSyncService = Depends(
        lambda: app_context.connector_sync_service
    ),
) -> Dict[str, Any]:
    """Synchronize one tenant-owned connector into Company Brain.

    Protected: requires a trusted X-10 tenant context and the
    ``connector:sync`` permission. The path ``tenant_id`` is validated for
    consistency against the trusted context (403 on mismatch). Fetching
    uses code-defined provider endpoints only; external data passes
    through the PII guard before ingestion. Failures are controlled and
    generic: no provider details, credentials, or internal information are
    exposed, and every attempt produces a tenant-scoped audit record.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        result = await connector_sync_service.sync(context, connector_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    except ConnectorSyncError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connector synchronization failed",
        )

    return {
        "connector_id": result.connector_id,
        "provider": result.provider.value,
        "status": "success",
        "items_fetched": result.items_fetched,
        "items": [
            {"source_id": item.source_id, "title": item.title, "url": item.url}
            for item in result.items
        ],
    }


# ---------------------------------------------------------------------------
# Connector credential management (V2-ADR-015, TRD 20, Issue #137)
# ---------------------------------------------------------------------------


@api_router.get(
    "/tenants/{tenant_id}/connectors/credentials/{provider}",
)
async def get_credential_metadata(
    tenant_id: str,
    provider: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_MANAGE_CREDENTIALS)),
    credential_service: ConnectorCredentialService = Depends(_get_credential_service_or_503),
) -> Dict[str, Any]:
    """Return safe metadata for a connector credential (never the secret).

    Protected: requires ``connector:manage_credentials`` and a trusted
    tenant context. Returns only provider, key_version, and timestamps.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider_enum = ConnectorProvider(provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    metadata = await credential_service.get_credential_metadata(context, provider_enum)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    return metadata


@api_router.post(
    "/tenants/{tenant_id}/connectors/credentials/{provider}",
)
async def create_credential(
    tenant_id: str,
    provider: str,
    body: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_MANAGE_CREDENTIALS)),
    credential_service: ConnectorCredentialService = Depends(_get_credential_service_or_503),
) -> Dict[str, Any]:
    """Create a connector credential for the trusted tenant.

    Protected: requires ``connector:manage_credentials`` and a trusted
    tenant context. The credential is encrypted at rest; the response
    contains only safe metadata.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider_enum = ConnectorProvider(provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    credential_value = body.get("credential")
    if not isinstance(credential_value, str) or not credential_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credential must be a non-empty string",
        )

    try:
        result = await credential_service.create_credential(
            context, provider_enum, credential_value
        )
    except ConnectorCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return result


@api_router.put(
    "/tenants/{tenant_id}/connectors/credentials/{provider}",
)
async def rotate_credential(
    tenant_id: str,
    provider: str,
    body: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_MANAGE_CREDENTIALS)),
    credential_service: ConnectorCredentialService = Depends(_get_credential_service_or_503),
) -> Dict[str, Any]:
    """Rotate a connector credential for the trusted tenant.

    Protected: requires ``connector:manage_credentials`` and a trusted
    tenant context. The old credential is replaced; the response
    contains only safe metadata.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider_enum = ConnectorProvider(provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    credential_value = body.get("credential")
    if not isinstance(credential_value, str) or not credential_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="credential must be a non-empty string",
        )

    try:
        result = await credential_service.rotate_credential(
            context, provider_enum, credential_value
        )
    except ConnectorCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    return result


@api_router.delete(
    "/tenants/{tenant_id}/connectors/credentials/{provider}",
)
async def delete_credential(
    tenant_id: str,
    provider: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_MANAGE_CREDENTIALS)),
    credential_service: ConnectorCredentialService = Depends(_get_credential_service_or_503),
) -> None:
    """Delete a connector credential for the trusted tenant.

    Protected: requires ``connector:manage_credentials`` and a trusted
    tenant context. An audit event is recorded.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider_enum = ConnectorProvider(provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    try:
        await credential_service.delete_credential(context, provider_enum)
    except ConnectorCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@api_router.get(
    "/tenants/{tenant_id}/connectors/credentials/{provider}/audit",
)
async def list_credential_audit(
    tenant_id: str,
    provider: str,
    context: TenantContext = Depends(require_tenant_permission(CONNECTOR_MANAGE_CREDENTIALS)),
    credential_service: ConnectorCredentialService = Depends(_get_credential_service_or_503),
) -> List[Dict[str, Any]]:
    """List credential audit records for a tenant/provider.

    Protected: requires ``connector:manage_credentials`` and a trusted
    tenant context. Audit records contain only safe metadata.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        provider_enum = ConnectorProvider(provider)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connector provider",
        )

    records = await credential_service.list_audit(context, provider_enum)
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "provider": r.provider.value,
            "operation": r.operation,
            "actor_user_id": r.actor_user_id,
            "key_version": r.key_version,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


def _webhook_event_payload(event: WebhookEvent, duplicate: bool) -> Dict[str, Any]:
    """Serialize a WebhookEvent without exposing any payload content."""
    return {
        "id": event.id,
        "tenant_id": event.tenant_id,
        "endpoint_id": event.endpoint_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "status": event.status.value,
        "payload_size_bytes": event.payload_size_bytes,
        "created_at": event.created_at.isoformat(),
        "duplicate": duplicate,
    }


async def _read_capped_body(request: Request, max_bytes: int) -> bytes:
    """Read a request body under a hard cumulative byte cap.

    Production-readiness hardening for webhook ingestion (Bala's approved
    PR #34 review follow-up): the previous ``await request.body()`` buffered
    the complete UNAUTHENTICATED body in memory before any size check.

    Behavior:
    - Content-Length is an EARLY-REJECTION FAST PATH only. It is
      client-controlled, so it never counts as enforcement; when it is
      absent, non-numeric, chunked, or lying, the streaming cap below is
      the actual limit.
    - Otherwise the body is consumed incrementally via ``request.stream()``
      and the read STOPS as soon as cumulative size exceeds ``max_bytes``.
      The remaining stream is intentionally NOT drained (draining would
      defeat the protection). On Uvicorn this is safe by construction:
      socket reads are paused at the protocol's own 64 KB high-water mark,
      and a response returned with an unconsumed body closes the
      connection instead of reusing it.
    - Bodies up to and including the cap are returned EXACTLY as received
      so HMAC verification keeps operating over the precise raw bytes.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook body cannot exceed {max_bytes} bytes",
        )

    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook body cannot exceed {max_bytes} bytes",
            )
    return bytes(buffer)


@api_router.post("/webhooks/{endpoint_id}/events")
async def ingest_webhook_event(
    endpoint_id: str,
    request: Request,
    webhook_ingestion_service: WebhookIngestionService = Depends(
        lambda: app_context.webhook_ingestion_service
    ),
    webhook_pipeline_service: WebhookPipelineService = Depends(
        lambda: app_context.webhook_pipeline_service
    ),
) -> Dict[str, Any]:
    """Receive one inbound webhook delivery and automatically dispatch
    to the downstream Skill pipeline (Issue #138, V2-ADR-017, PRD 17).

    NOT RBAC-gated by design (ADR-001 webhook security boundary):
    external senders hold no Arc identity. Authentication is per-endpoint
    HMAC-SHA256 over ``{timestamp}.{raw_body}`` with the signing secret
    and tenant binding provisioned exclusively through environment
    configuration; request input can never select a tenant.

    All authentication failures are UNIFORM 401s so senders cannot
    enumerate valid endpoints. Duplicate deliveries are idempotent:
    they return the original record with ``duplicate=true`` instead of
    creating a second row. Raw payloads are never persisted or returned.

    After successful ingestion, the event is automatically dispatched
    through the configured Skill pipeline (WebhookPipelineService).
    Pipeline failures are non-blocking: the ingestion returns 201 with
    the event in ``received`` status and the error is logged for manual
    retry via ``POST /tenants/{tenant_id}/webhooks/process``.
    """
    body = await _read_capped_body(request, MAX_BODY_BYTES)
    timestamp_header = request.headers.get("X-Arc-Timestamp", "")
    signature_header = request.headers.get("X-Arc-Signature", "")

    try:
        result = await webhook_ingestion_service.ingest(
            endpoint_id, timestamp_header, signature_header, body
        )
    except WebhookAuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook authentication failed",
        )
    except WebhookValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except WebhookIngestionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook ingestion failed",
        )

    # Automatic dispatch (Issue #138, V2-ADR-017): route non-duplicate
    # events through the Skill pipeline immediately after ingestion.
    # Duplicate deliveries are already recorded; pipeline processing
    # is NOT re-triggered to avoid duplicate downstream execution.
    if not result.duplicate:
        try:
            await webhook_pipeline_service.process(
                result.event.tenant_id, result.event.event_id
            )
            # Refresh the event to reflect processed status.
            result.event = await webhook_ingestion_service._repository.get_by_event_id(
                result.event.event_id, result.event.tenant_id
            )
        except Exception:
            # Pipeline failure is non-blocking: the event remains in
            # ``received`` status for manual retry via the /process
            # endpoint. Ingestion still returns 201.
            logger.warning(
                "Webhook auto-dispatch failed; event remains in 'received' "
                "status for manual retry",
                extra={
                    "endpoint_id": endpoint_id,
                    "event_id": result.event.event_id,
                    "tenant_id": result.event.tenant_id,
                },
                exc_info=True,
            )

    return _webhook_event_payload(result.event, result.duplicate)


@api_router.get("/tenants/{tenant_id}/webhooks/events")
async def list_webhook_events(
    tenant_id: str,
    context: TenantContext = Depends(require_tenant_permission(WEBHOOK_READ)),
    webhook_ingestion_service: WebhookIngestionService = Depends(
        lambda: app_context.webhook_ingestion_service
    ),
) -> List[Dict[str, Any]]:
    """List the caller's tenant webhook event records.

    Protected: requires a trusted X-10 tenant context and the
    ``webhook:read`` permission. The path ``tenant_id`` is validated for
    consistency against the trusted context (403 on mismatch). Only safe
    envelope metadata is returned; payload content was never stored.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    events = await webhook_ingestion_service.list_events(context)
    return [_webhook_event_payload(event, False) for event in events]


@api_router.post("/tenants/{tenant_id}/webhooks/process")
async def process_webhook_event(
    tenant_id: str,
    event_id: str = Query(..., description="Sender-supplied event identifier"),
    context: TenantContext = Depends(require_tenant_permission(WEBHOOK_PROCESS)),
    webhook_pipeline_service: WebhookPipelineService = Depends(
        lambda: app_context.webhook_pipeline_service
    ),
) -> Dict[str, Any]:
    """Process a received webhook event through the downstream pipeline.

    Protected: requires a trusted X-10 tenant context and the
    ``webhook:process`` permission. The path ``tenant_id`` is validated
    for consistency against the trusted context (403 on mismatch).

    Atomically claims the event (received -> processing), resolves the
    configured downstream Skill action, and executes it through the
    existing SkillExecutionService. On success the event transitions
    to ``processed``; on any failure it transitions to ``failed`` with
    a safe error category. At most one caller can claim a given event.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    try:
        result = await webhook_pipeline_service.process(tenant_id, event_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found or not in 'received' status",
        )
    except WebhookProcessingError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed",
        )

    return result


@api_router.get("/tenants/{tenant_id}/observability/usage-summary")
async def get_tenant_usage_summary(
    tenant_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    context: TenantContext = Depends(require_tenant_permission(OBSERVABILITY_READ)),
    observability_service: ObservabilityService = Depends(
        lambda: app_context.observability_service
    ),
) -> Dict[str, Any]:
    """Tenant-scoped usage summary (PRD 17, TRD 17): aggregates ONLY.

    Requires authentication, the trusted tenant context, and
    ``observability:read``; the path tenant must match the trusted
    context (403 otherwise). Responses contain numeric operational
    aggregates from authoritative subsystem records and HTTP telemetry —
    never raw rows, summaries, prompts, answers, payloads, or secrets.
    """
    if tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return await observability_service.get_tenant_usage_summary(context.tenant_id, hours)


@api_router.get("/platform/observability/summary")
async def get_platform_observability_summary(
    hours: int = Query(default=24, ge=1, le=168),
    _: AuthenticatedPrincipal = Depends(require_permission(OBSERVABILITY_PLATFORM_READ)),
    observability_service: ObservabilityService = Depends(
        lambda: app_context.observability_service
    ),
) -> Dict[str, Any]:
    """Platform operational summary — STRICTLY TENANT-AGNOSTIC.

    PLATFORM_ADMINISTRATOR only. Answers "is the ARC platform operating
    correctly?": cross-tenant operational totals without any tenant
    identifiers, per-tenant usage/rankings, or tenant business data.
    Tenant-specific investigation uses the tenant-scoped endpoint.
    """
    return await observability_service.get_platform_summary(hours)


@api_router.get("/observability/health")
async def get_component_health(
    _: AuthenticatedPrincipal = Depends(require_permission(OBSERVABILITY_PLATFORM_READ)),
    observability_service: ObservabilityService = Depends(
        lambda: app_context.observability_service
    ),
) -> Dict[str, Any]:
    """Protected component-health surface.

    ``GET /health`` remains the public liveness probe with its exact
    body. This surface reports real component checks (database, LLM
    provider, embeddings) as status labels only — never settings values
    or configuration material.
    """
    return await observability_service.get_component_health()


@api_router.get("/tenants/{tenant_id}/observability/agent-runs")
async def list_agent_run_traces(
    tenant_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    context: TenantContext = Depends(require_tenant_permission(OBSERVABILITY_READ)),
    observability_service: ObservabilityService = Depends(
        lambda: app_context.observability_service
    ),
) -> list:
    """List persisted agent execution traces (PRD 17 O-6).

    Requires authentication, the trusted tenant context, and
    ``observability:read``; the path tenant must match the trusted
    context (403 otherwise). Returns traces ordered by most recent first.
    """
    if tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    records = await observability_service.list_agent_run_traces(context.tenant_id, hours)
    return [_agent_run_trace_payload(r) for r in records]


@api_router.get("/tenants/{tenant_id}/observability/agent-runs/{record_id}")
async def get_agent_run_trace(
    tenant_id: str,
    record_id: str,
    context: TenantContext = Depends(require_tenant_permission(OBSERVABILITY_READ)),
    observability_service: ObservabilityService = Depends(
        lambda: app_context.observability_service
    ),
) -> Dict[str, Any]:
    """Read one persisted agent execution trace (PRD 17 O-6).

    Requires authentication, the trusted tenant context, and
    ``observability:read``; the path tenant must match the trusted
    context (403 otherwise).
    """
    if tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    try:
        record = await observability_service.get_agent_run_trace(context.tenant_id, record_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _agent_run_trace_payload(record)


def _agent_run_trace_payload(record) -> Dict[str, Any]:
    """Serialize an agent run trace for API responses."""
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "principal_id": record.principal_id,
        "goal": record.goal,
        "status": record.status,
        "error_kind": record.error_kind,
        "steps": [
            {
                "sequence": step.sequence,
                "skill_id": step.skill_id,
                "skill_name": step.skill_name,
                "status": step.status,
                "error_kind": step.error_kind,
            }
            for step in record.steps
        ],
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _approval_payload(approval) -> Dict[str, Any]:
    """Serialize an approval request for decision-making surfaces.

    Exposes the minimum information required to make a decision. NEVER
    includes raw tool arguments, the internal arguments digest, secrets,
    or tenant-external identifiers.
    """
    return {
        "id": approval.id,
        "tool_name": approval.tool_name,
        "tool_version": approval.tool_version,
        "risk_level": approval.risk_level,
        "status": approval.status.value,
        "requester_user_id": approval.requester_user_id,
        "input_summary": approval.input_summary,
        "created_at": approval.created_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "decided_by_user_id": approval.decided_by_user_id,
        "consumed_at": approval.consumed_at.isoformat() if approval.consumed_at else None,
    }


@api_router.get("/tenants/{tenant_id}/approvals")
async def list_approval_requests(
    tenant_id: str,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    context: TenantContext = Depends(require_tenant_permission(APPROVAL_READ)),
    human_approval_service: HumanApprovalService = Depends(
        lambda: app_context.human_approval_service
    ),
) -> List[Dict[str, Any]]:
    """List Human Intervention approval requests for the trusted tenant.

    Requires ``approval:read`` and path-consistent tenant scope. Expired
    pending rows are reported as ``expired`` (lazy derivation). Responses
    contain redacted summaries only -- never raw tool arguments.
    """
    status_value: Optional[ApprovalStatus] = None
    if status_filter is not None:
        try:
            status_value = ApprovalStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter"
            )
    approvals = await human_approval_service.list_requests(context, status_value)
    return [_approval_payload(a) for a in approvals]


@api_router.get("/tenants/{tenant_id}/approvals/{approval_id}")
async def get_approval_request(
    tenant_id: str,
    approval_id: str,
    context: TenantContext = Depends(require_tenant_permission(APPROVAL_READ)),
    human_approval_service: HumanApprovalService = Depends(
        lambda: app_context.human_approval_service
    ),
) -> Dict[str, Any]:
    """Read one approval request within the trusted tenant."""
    try:
        approval = await human_approval_service.get_request(context, approval_id)
    except ApprovalNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    return _approval_payload(approval)


@api_router.post("/tenants/{tenant_id}/approvals/{approval_id}/decisions")
async def decide_approval_request(
    tenant_id: str,
    approval_id: str,
    decision_data: Dict[str, Any],
    context: TenantContext = Depends(require_tenant_permission(APPROVAL_DECIDE)),
    human_approval_service: HumanApprovalService = Depends(
        lambda: app_context.human_approval_service
    ),
) -> Dict[str, Any]:
    """Make the terminal approve/reject decision for one request.

    Requires ``approval:decide`` and path-consistent tenant scope. The
    deciding identity comes exclusively from the authenticated principal.
    Decisions are terminal; expired requests fail with 409 and become
    terminal ``expired``. Execution never happens here: consuming an
    approved request remains an authorized ToolExecutionService flow.
    """
    decision_raw = decision_data.get("decision")
    if decision_raw not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'approve' or 'reject'",
        )
    decision = ApprovalStatus.APPROVED if decision_raw == "approve" else ApprovalStatus.REJECTED
    try:
        approval = await human_approval_service.decide_request(
            context, context.user_id, approval_id, decision
        )
    except ApprovalNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found"
        )
    except ApprovalExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ApprovalSelfDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except (ApprovalStateError, ApprovalConsumedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ApprovalError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Approval decision failed",
        )
    return _approval_payload(approval)


@api_router.post("/skills/{skill_id}/resume")
async def resume_skill_execution(
    skill_id: str,
    tenant_id: str,
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(require_tenant_permission(SKILL_EXECUTE)),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    execution_service: SkillExecutionService = Depends(lambda: app_context.skill_execution_service),
) -> Dict[str, Any]:
    """Resume a Skill execution after human approval.

    Accepts the ``approval_id`` returned by a previous execute/resume
    call, along with the original ``tool_calls`` and the
    ``resume_from_step`` index. The approval is atomically consumed by
    ToolExecutionService before the gated tool handler runs. Steps before
    ``resume_from_step`` are preserved from ``previous_steps`` without
    re-execution.

    Requires ``skill:execute`` and a trusted X-10 tenant context.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be an object"
        )

    approval_id = body.get("approval_id")
    tool_calls = body.get("tool_calls")
    resume_from_step = body.get("resume_from_step")
    previous_steps_raw = body.get("previous_steps", [])

    if not approval_id or not isinstance(approval_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval_id is required",
        )
    if not isinstance(tool_calls, list) or not tool_calls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tool_calls is required and must be a non-empty list",
        )
    if not isinstance(resume_from_step, int) or resume_from_step < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_from_step is required and must be a non-negative integer",
        )

    previous_steps = []
    for raw_step in previous_steps_raw:
        previous_steps.append(
            SkillExecutionStepOutcome(
                sequence=raw_step["sequence"],
                tool_name=raw_step["tool_name"],
                status=ToolExecutionStatus(raw_step["status"]),
                tool_version=raw_step.get("tool_version"),
                output=raw_step.get("output"),
                error_kind=raw_step.get("error_kind"),
            )
        )

    try:
        result = await execution_service.execute(
            context,
            principal,
            skill_id,
            tool_calls,
            body.get("satisfied_preconditions", []),
            authorization,
            approval_id=approval_id,
            resume_from_step=resume_from_step,
            previous_steps=previous_steps,
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _skill_execution_response(result)


@api_router.post("/agent/runs/resume")
async def resume_agent_execution(
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(_require_tenant_permission_from_body),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    authorization: AuthorizationService = Depends(get_authorization_service),
    execution_service: SkillExecutionService = Depends(lambda: app_context.skill_execution_service),
) -> Dict[str, Any]:
    """Resume an Agent execution after human approval.

    Accepts the ``approval_id`` returned by a previous agent run, along
    with the ``skill_id``, ``tool_calls``, and ``resume_from_step`` from
    the original decision. The approval is atomically consumed before the
    gated tool handler runs. The LLM decision step is skipped: the
    original decision is replayed with the approval context.

    Requires ``agent:execute`` and a trusted X-10 tenant context.
    """
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be an object"
        )

    approval_id = body.get("approval_id")
    skill_id = body.get("skill_id")
    tool_calls = body.get("tool_calls")
    resume_from_step = body.get("resume_from_step")
    previous_steps_raw = body.get("previous_steps", [])

    if not approval_id or not isinstance(approval_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval_id is required",
        )
    if not skill_id or not isinstance(skill_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skill_id is required",
        )
    if not isinstance(tool_calls, list) or not tool_calls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tool_calls is required and must be a non-empty list",
        )
    if not isinstance(resume_from_step, int) or resume_from_step < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resume_from_step is required and must be a non-negative integer",
        )

    previous_steps = []
    for raw_step in previous_steps_raw:
        previous_steps.append(
            SkillExecutionStepOutcome(
                sequence=raw_step["sequence"],
                tool_name=raw_step["tool_name"],
                status=ToolExecutionStatus(raw_step["status"]),
                tool_version=raw_step.get("tool_version"),
                output=raw_step.get("output"),
                error_kind=raw_step.get("error_kind"),
            )
        )

    try:
        result = await execution_service.execute(
            context,
            principal,
            skill_id,
            tool_calls,
            body.get("satisfied_preconditions", []),
            authorization,
            approval_id=approval_id,
            resume_from_step=resume_from_step,
            previous_steps=previous_steps,
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _skill_execution_response(result)
