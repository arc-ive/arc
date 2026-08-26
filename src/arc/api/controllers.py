"""API controllers for Arc Skills Engine / AI Tools / Agent slices.

Security-sensitive operations are protected by X-11 authentication and
application RBAC:

- Tenant and user provisioning require a global permission
  (PLATFORM_ADMINISTRATOR only).
- Tenant-scoped reads require a trusted X-10 tenant context and the
  ``tenant:read`` permission.
- Identity-scoped listing is self-only: the requested ``user_id`` must
  equal the authenticated principal's user ID (JWT ``sub``).
- Skills are tenant-scoped: management requires ``skill:create/read/delete``
  and execution requires ``skill:execute`` inside a trusted X-10 tenant
  context. Execution delegates exclusively to ``SkillExecutionService``.
- The AI Tool catalog is platform-owned: reading requires ``tool:read``
  and execution requires ``tool:execute`` plus each tool's declared
  permissions, enforced inside ``ToolExecutionService``.
- The Agent endpoint requires ``agent:execute``; it orchestrates Skills
  only and never touches tool registries or handlers directly.

Privileged and identity-sensitive development endpoints (membership
provisioning) are isolated in ``arc.api.dev_controllers``.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status

from arc.db.connection import NotFoundError
from arc.domain.models import (
    AgentExecutionResult,
    Skill,
    SkillExecutionResult,
    SkillStatus,
    Tenant,
    TenantContext,
    User,
)
from arc.security.authorization import (
    AGENT_EXECUTE,
    SKILL_CREATE,
    SKILL_DELETE,
    SKILL_EXECUTE,
    SKILL_READ,
    TENANT_CREATE,
    TENANT_READ,
    TOOL_EXECUTE,
    TOOL_READ,
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
from arc.services.agent import AgentExecutionService
from arc.services.connectors import ConnectorService
from arc.services.domain import (
    MembershipService,
    TenantContextService,
    TenantService,
    UserService,
)
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
        status=status_value,
    )
    created_skill = await skill_service.create_skill(context, skill)
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
    return {
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
    return {
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


@api_router.post("/agent/runs")
async def run_agent(
    tenant_id: str,
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(require_tenant_permission(AGENT_EXECUTE)),
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

    Controlled outcomes (succeeded, failed, approval_required,
    max_steps_reached) are returned as structured 200 responses;
    malformed request metadata is rejected with 400.
    """
    _require_path_tenant_matches_context(tenant_id, context)

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be an object"
        )

    try:
        result = await agent_service.run(
            context,
            principal,
            body.get("goal"),
            authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return _agent_run_response(result)


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

    try:
        result = await tool_service.execute_tool(context, principal, name, raw_input, authorization)
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
        "status": config.status.value,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
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
