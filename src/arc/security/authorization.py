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
- No Connector or Operations permissions are defined.
- Knowledge permissions (``knowledge:create``, ``knowledge:read``) exist for
  the Company Brain foundation: COMPANY_ADMINISTRATOR manages and reads
  company knowledge; OPERATIONS_USER reads it for operational workflows;
  PLATFORM_ADMINISTRATOR retains global access; EMPLOYEE has none.
- Skill permissions (``skill:create``, ``skill:read``, ``skill:delete``)
  exist for the Skills Engine management API: PLATFORM_ADMINISTRATOR and
  COMPANY_ADMINISTRATOR create, read, and delete Skills; OPERATIONS_USER
  reads them; EMPLOYEE has none.
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
SKILL_DELETE = Permission(resource="skill", action="delete")
TOOL_READ = Permission(resource="tool", action="read")
TOOL_EXECUTE = Permission(resource="tool", action="execute")


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
            SKILL_DELETE,
            TOOL_READ,
            TOOL_EXECUTE,
        }
    ),
    ApplicationRole.COMPANY_ADMINISTRATOR: frozenset(
        {
            TENANT_READ,
            KNOWLEDGE_CREATE,
            KNOWLEDGE_READ,
            SKILL_CREATE,
            SKILL_READ,
            SKILL_DELETE,
            TOOL_READ,
            TOOL_EXECUTE,
        }
    ),
    ApplicationRole.OPERATIONS_USER: frozenset(
        {TENANT_READ, KNOWLEDGE_READ, SKILL_READ, TOOL_READ, TOOL_EXECUTE}
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
