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

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import (
    ConnectorProvider,
    IntelligenceAnswer,
    KnowledgeDocument,
    KnowledgeMatch,
    KnowledgeSource,
    Skill,
    SkillStatus,
    Tenant,
    TenantContext,
    User,
    WebhookEvent,
)
from arc.security.authorization import (
    CONNECTOR_CREATE,
    CONNECTOR_READ,
    CONNECTOR_SYNC,
    KNOWLEDGE_CREATE,
    KNOWLEDGE_READ,
    OBSERVABILITY_PLATFORM_READ,
    OBSERVABILITY_READ,
    SKILL_CREATE,
    SKILL_DELETE,
    SKILL_READ,
    TENANT_CREATE,
    TENANT_READ,
    TOOL_EXECUTE,
    TOOL_READ,
    USER_CREATE,
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
    WebhookAuthenticationError,
    WebhookIngestionError,
    WebhookIngestionService,
    WebhookValidationError,
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
    def connector_sync_service(self) -> ConnectorSyncService:
        return self.services.get("connector_sync_service")

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
    def tool_service(self) -> ToolExecutionService:
        return self.services.get("tool_service")

    @property
    def webhook_ingestion_service(self) -> WebhookIngestionService:
        return self.services.get("webhook_ingestion_service")

    @property
    def observability_service(self):
        return self.services.get("observability_service")


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

    try:
        matches = await retrieval_service.search(context, query, limit=limit)
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
    }


@api_router.post("/tenants/{tenant_id}/intelligence/query")
async def query_unified_intelligence(
    tenant_id: str,
    body: Optional[Any] = Body(default=None),
    context: TenantContext = Depends(require_tenant_permission(KNOWLEDGE_READ)),
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
        answer = await intelligence_service.answer_query(context, query, limit=limit)
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

    try:
        created = await connector_service.create_connector(context, provider, name)
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


@api_router.post("/webhooks/{endpoint_id}/events")
async def ingest_webhook_event(
    endpoint_id: str,
    request: Request,
    webhook_ingestion_service: WebhookIngestionService = Depends(
        lambda: app_context.webhook_ingestion_service
    ),
) -> Dict[str, Any]:
    """Receive one inbound webhook delivery (machine-to-machine).

    NOT RBAC-gated by design (ADR-001 webhook security boundary):
    external senders hold no Arc identity. Authentication is per-endpoint
    HMAC-SHA256 over ``{timestamp}.{raw_body}`` with the signing secret
    and tenant binding provisioned exclusively through environment
    configuration; request input can never select a tenant.

    All authentication failures are UNIFORM 401s so senders cannot
    enumerate valid endpoints. Duplicate deliveries are idempotent:
    they return the original record with ``duplicate=true`` instead of
    creating a second row. Raw payloads are never persisted or returned.
    """
    body = await request.body()
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
