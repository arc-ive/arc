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
- Knowledge permissions (``knowledge:create``, ``knowledge:read``) exist for
  the Company Brain foundation: COMPANY_ADMINISTRATOR manages and reads
  company knowledge; OPERATIONS_USER reads it for operational workflows;
  PLATFORM_ADMINISTRATOR retains global access; EMPLOYEE has none.
- Skill permissions (``skill:create``, ``skill:read``, ``skill:update``,
  ``skill:delete``) exist for the Skills Engine management API:
  PLATFORM_ADMINISTRATOR and COMPANY_ADMINISTRATOR create, update, read, and
  delete Skills; OPERATIONS_USER reads them; EMPLOYEE has none.
- Tool permissions (``tool:read``, ``tool:execute``) exist for the AI
  Tools foundation (PRD 15, TRD 14): PLATFORM_ADMINISTRATOR and
  COMPANY_ADMINISTRATOR read the platform tool catalog and execute
  approved tools; OPERATIONS_USER reads and executes permitted
  operational tools (TRD 7); EMPLOYEE has none.
- ``EMPLOYEE`` intentionally has no matrix permissions; it is allowed only
  self-scoped operations (for example listing the authenticated user's own
  tenants).
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
USER_CREATE = Permission(resource="user", action="create")
MEMBERSHIP_CREATE = Permission(resource="membership", action="create")
TENANT_READ = Permission(resource="tenant", action="read")
KNOWLEDGE_CREATE = Permission(resource="knowledge", action="create")
KNOWLEDGE_READ = Permission(resource="knowledge", action="read")
SKILL_CREATE = Permission(resource="skill", action="create")
SKILL_READ = Permission(resource="skill", action="read")
SKILL_UPDATE = Permission(resource="skill", action="update")
SKILL_DELETE = Permission(resource="skill", action="delete")
TOOL_READ = Permission(resource="tool", action="read")
TOOL_EXECUTE = Permission(resource="tool", action="execute")
CONNECTOR_CREATE = Permission(resource="connector", action="create")
CONNECTOR_READ = Permission(resource="connector", action="read")
CONNECTOR_SYNC = Permission(resource="connector", action="sync")
WEBHOOK_READ = Permission(resource="webhook", action="read")


ROLE_PERMISSIONS: Dict[ApplicationRole, FrozenSet[Permission]] = {
    # Global provisioning permissions; they intentionally require NO tenant context.
    ApplicationRole.PLATFORM_ADMINISTRATOR: frozenset(
        {
            TENANT_CREATE,
            USER_CREATE,
            MEMBERSHIP_CREATE,
            TENANT_READ,
            KNOWLEDGE_CREATE,
            KNOWLEDGE_READ,
            SKILL_CREATE,
            SKILL_READ,
            SKILL_UPDATE,
            SKILL_DELETE,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_CREATE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            WEBHOOK_READ,
        }
    ),
    ApplicationRole.COMPANY_ADMINISTRATOR: frozenset(
        {
            TENANT_READ,
            KNOWLEDGE_CREATE,
            KNOWLEDGE_READ,
            SKILL_CREATE,
            SKILL_READ,
            SKILL_UPDATE,
            SKILL_DELETE,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_CREATE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            WEBHOOK_READ,
        }
    ),
    ApplicationRole.OPERATIONS_USER: frozenset(
        {
            TENANT_READ,
            KNOWLEDGE_READ,
            SKILL_READ,
            TOOL_READ,
            TOOL_EXECUTE,
            CONNECTOR_READ,
            CONNECTOR_SYNC,
            WEBHOOK_READ,
        }
    ),
    # EMPLOYEE has no matrix permissions (self-scoped operations only).
    ApplicationRole.EMPLOYEE: frozenset(),
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
