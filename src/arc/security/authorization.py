"""X-11 application authorization.

``AuthorizationService`` is the application-enforced RBAC boundary. It
resolves the authenticated principal's application role from the explicit
development configuration assignments and checks the minimal X-11 permission
matrix.

Design decisions (X-11 implementation decisions, NOT defined by X-10):

- The permission matrix below is the smallest set required to demonstrate
  X-11. Approved product-extension permissions are added through PR
  review: ``knowledge:create``/``knowledge:read`` (Company Brain
  foundation) and ``skill:create``/``skill:read``/``skill:delete``
  (Skills Engine management API).
- Connector permissions (``connector:create``, ``connector:read``,
  ``connector:sync``) exist for the connector provider integrations
  (PRD 22, TRD 33, ADR-002): PLATFORM_ADMINISTRATOR and
  COMPANY_ADMINISTRATOR configure, read, and synchronize connectors;
  OPERATIONS_USER reads and synchronizes connectors for operational
  workflows; EMPLOYEE has none.

  Connector role mapping (explicit matrix):

  - ``connector:read`` (list connector configuration, read connector
    state): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR,
    OPERATIONS_USER; tenant-scoped; denied by default.
  - ``connector:create`` (create connector configuration):
    PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR; tenant-scoped;
    denied by default.
  - ``connector:sync`` (trigger connector synchronization):
    PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER;
    tenant-scoped; denied by default.

  There is no connector-specific authorization system: the connector
  layer consumes this centralized matrix via ``AuthorizationService``.
  An unknown permission is never granted (default DENY).
- Webhook permission (``webhook:read``) exists for the Webhooks
  foundation (PRD 16, TRD 16): PLATFORM_ADMINISTRATOR,
  COMPANY_ADMINISTRATOR, and OPERATIONS_USER read the tenant's ingested
  webhook event records for observability; EMPLOYEE has none. The
  machine-facing INGESTION endpoint is NOT RBAC-gated: external senders
  hold no Arc identity and authenticate exclusively through per-endpoint
  HMAC signatures bound to a configured tenant (ADR-001 webhook
  security boundary). There is deliberately no ``webhook:create``
  permission in this slice: ingestion endpoints are provisioned through
  environment configuration, not API requests.
- ``webhook:process`` exists for webhook downstream processing (Issue
  #102): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, and
  OPERATIONS_USER may trigger processing of received webhook events.
  Processing executes downstream Skill and Tool actions through the
  existing authorization boundary; EMPLOYEE has none.
- Observability permissions (PRD 17, TRD 17) follow the approved split:
  ``observability:read`` grants tenant-scoped usage summaries to
  PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, and OPERATIONS_USER;
  ``observability:platform_read`` grants the tenant-agnostic platform
  operational summary to PLATFORM_ADMINISTRATOR only, and (ADR-010) the
  per-tenant breakdown of request and error COUNTS that makes an
  incident attributable to a customer. Platform visibility still never
  exposes tenant business data: no paths, payloads, prompts, documents
  or user identifiers. EMPLOYEE has none.
- Knowledge permissions (``knowledge:create``, ``knowledge:read``,
  ``knowledge:update``, ``knowledge:delete``) exist for the Company Brain
  foundation: COMPANY_ADMINISTRATOR manages and reads company knowledge;
  OPERATIONS_USER reads it for operational workflows;
  PLATFORM_ADMINISTRATOR retains global access; EMPLOYEE holds
  ``knowledge:read`` for Ask Arc (Unified Intelligence) and Company Brain
  read access per PRD §7.4.
- Skill permissions (``skill:create``, ``skill:read``, ``skill:update``,
  ``skill:delete``) exist for the Skills Engine management API:
  PLATFORM_ADMINISTRATOR and COMPANY_ADMINISTRATOR create, update, read, and
  delete Skills; OPERATIONS_USER reads them; EMPLOYEE has none.
- Tool permissions (``tool:read``, ``tool:execute``) exist for the AI
  Tools foundation (PRD 15, TRD 14): PLATFORM_ADMINISTRATOR and
  COMPANY_ADMINISTRATOR read the platform tool catalog and execute
  approved tools; OPERATIONS_USER reads and executes permitted
  operational tools (TRD 7); EMPLOYEE has none.
- ``skill:execute`` exists for Skill execution (Skills Engine execution
  slice): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, and
  OPERATIONS_USER execute Skills within a trusted tenant context;
  EMPLOYEE has none. Execution authorization for the underlying tools
  remains enforced by the tool layer (``tool:execute`` plus each tool's
  declared required permissions), never by this permission alone.
- ``agent:execute`` exists for the bounded Agent orchestration layer
  (ADR-006): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, and
  OPERATIONS_USER may run the Agent; EMPLOYEE has none. The Agent can do
  nothing beyond what Skill execution already permits: it must pass
  through ``SkillExecutionService``, so this permission never grants
  direct tool access and never bypasses ``Skill.allowed_tools`` or
  per-tool RBAC.
- ``EMPLOYEE`` holds ``knowledge:read`` for Ask Arc (Unified Intelligence)
  and Company Brain read access per PRD §7.4; all other permissions are
  denied. Self-scoped operations (for example listing the authenticated
  user's own tenants) are always available through authenticated endpoints.
- Default behavior is DENY: an unknown user, an unknown role, or an
  unassigned permission is always denied.
- ``ApplicationRole`` is completely independent of the X-10 membership
  ``UserRole`` (OWNER/MEMBER/VIEWER). No mapping exists between them.
"""

from typing import Dict, FrozenSet, Mapping, Optional

from arc.security.models import ApplicationRole, AuthenticatedPrincipal, Permission

# ---------------------------------------------------------------------------
# Minimal X-11 permission matrix
# ---------------------------------------------------------------------------

TENANT_CREATE = Permission(resource="tenant", action="create")
TENANT_UPDATE = Permission(resource="tenant", action="update")
TENANT_LIST = Permission(resource="tenant", action="list")
USER_CREATE = Permission(resource="user", action="create")
USER_READ = Permission(resource="user", action="read")
MEMBERSHIP_CREATE = Permission(resource="membership", action="create")
TENANT_READ = Permission(resource="tenant", action="read")
KNOWLEDGE_CREATE = Permission(resource="knowledge", action="create")
KNOWLEDGE_READ = Permission(resource="knowledge", action="read")
KNOWLEDGE_UPDATE = Permission(resource="knowledge", action="update")
KNOWLEDGE_DELETE = Permission(resource="knowledge", action="delete")
SKILL_CREATE = Permission(resource="skill", action="create")
SKILL_READ = Permission(resource="skill", action="read")
SKILL_UPDATE = Permission(resource="skill", action="update")
SKILL_DELETE = Permission(resource="skill", action="delete")
SKILL_EXECUTE = Permission(resource="skill", action="execute")
TOOL_READ = Permission(resource="tool", action="read")
TOOL_EXECUTE = Permission(resource="tool", action="execute")
CONNECTOR_CREATE = Permission(resource="connector", action="create")
CONNECTOR_READ = Permission(resource="connector", action="read")
CONNECTOR_SYNC = Permission(resource="connector", action="sync")
CONNECTOR_MANAGE_CREDENTIALS = Permission(resource="connector", action="manage_credentials")
WEBHOOK_READ = Permission(resource="webhook", action="read")
WEBHOOK_PROCESS = Permission(resource="webhook", action="process")
OBSERVABILITY_READ = Permission(resource="observability", action="read")
OBSERVABILITY_PLATFORM_READ = Permission(resource="observability", action="platform_read")
AGENT_EXECUTE = Permission(resource="agent", action="execute")
APPROVAL_READ = Permission(resource="approval", action="read")
APPROVAL_DECIDE = Permission(resource="approval", action="decide")
CAPABILITY_MANAGE = Permission(resource="capability", action="manage")


ROLE_PERMISSIONS: Dict[ApplicationRole, FrozenSet[Permission]] = {
    # Global provisioning permissions; they intentionally require NO tenant context.
    ApplicationRole.PLATFORM_ADMINISTRATOR: frozenset(
        {
            AGENT_EXECUTE,
            TENANT_CREATE,
            TENANT_UPDATE,
            TENANT_LIST,
            USER_CREATE,
            USER_READ,
            MEMBERSHIP_CREATE,
            TENANT_READ,
            KNOWLEDGE_CREATE,
            KNOWLEDGE_READ,
            KNOWLEDGE_UPDATE,
            SKILL_CREATE,
            SKILL_READ,
            SKILL_UPDATE,
            SKILL_DELETE,
            SKILL_EXECUTE,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_CREATE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            CONNECTOR_MANAGE_CREDENTIALS,
            WEBHOOK_READ,
            WEBHOOK_PROCESS,
            OBSERVABILITY_READ,
            OBSERVABILITY_PLATFORM_READ,
            APPROVAL_READ,
            APPROVAL_DECIDE,
            CAPABILITY_MANAGE,
            KNOWLEDGE_DELETE,
        }
    ),
    ApplicationRole.COMPANY_ADMINISTRATOR: frozenset(
        {
            AGENT_EXECUTE,
            TENANT_UPDATE,
            TENANT_READ,
            KNOWLEDGE_CREATE,
            KNOWLEDGE_READ,
            KNOWLEDGE_UPDATE,
            KNOWLEDGE_DELETE,
            SKILL_CREATE,
            SKILL_READ,
            SKILL_UPDATE,
            SKILL_DELETE,
            SKILL_EXECUTE,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_CREATE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            CONNECTOR_MANAGE_CREDENTIALS,
            WEBHOOK_READ,
            WEBHOOK_PROCESS,
            OBSERVABILITY_READ,
            APPROVAL_READ,
            APPROVAL_DECIDE,
        }
    ),
    ApplicationRole.OPERATIONS_USER: frozenset(
        {
            AGENT_EXECUTE,
            TENANT_READ,
            KNOWLEDGE_READ,
            SKILL_READ,
            SKILL_EXECUTE,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            WEBHOOK_READ,
            WEBHOOK_PROCESS,
            OBSERVABILITY_READ,
        }
    ),
    # EMPLOYEE holds knowledge:read for Ask Arc (Unified Intelligence) and
    # Company Brain read access per PRD §7.4, plus agent:execute to initiate
    # permitted Agent workflows per V2-ADR-005. Direct skill:execute and
    # tool:execute are NOT granted — employee workflows must go through
    # Agent as the single execution boundary.
    # Self-scoped operations (for example listing the authenticated user's own
    # tenants) are always available through authenticated endpoints.
    ApplicationRole.EMPLOYEE: frozenset({KNOWLEDGE_READ, AGENT_EXECUTE}),
    # WEBHOOK_PROCESSOR is the synthetic system role for webhook-triggered
    # downstream execution. It holds ONLY the permissions required by
    # SkillExecutionService → ToolExecutionService: skill:execute to enter
    # the skill engine, and tool:execute to reach the single tool action
    # boundary. This role does NOT hold webhook:read, webhook:process,
    # tenant:create, or any other platform/tenant operations.
    ApplicationRole.WEBHOOK_PROCESSOR: frozenset({SKILL_EXECUTE, TOOL_EXECUTE}),
}


class AuthorizationService:
    """Application-enforced RBAC authorization.

    Args:
        role_assignments: explicit mapping of user ID to application role.
            Missing users have no role and are denied by default.
    """

    def __init__(self, role_assignments: Optional[Mapping[str, ApplicationRole]] = None):
        self._role_assignments: Dict[str, ApplicationRole] = (
            dict(role_assignments) if role_assignments else {}
        )

    def role_for(self, user_id: str) -> Optional[ApplicationRole]:
        """Return the assigned application role for a user, or None.

        None means the user has no application role and is denied by default.
        """
        return self._role_assignments.get(user_id)

    def has_permission(self, principal: AuthenticatedPrincipal, permission: Permission) -> bool:
        """Check whether the principal's application role grants the permission.

        Fails closed: unknown users, unknown roles, and unlisted permissions
        are always denied.
        """
        role = self.role_for(principal.user_id)
        if role is None:
            return False
        return permission in ROLE_PERMISSIONS.get(role, frozenset())
