/**
 * Permission identifiers, mirroring the backend authorization model.
 *
 * These are the exact strings `GET /auth/me` returns in `permissions`, which
 * the backend derives from `ROLE_PERMISSIONS` in
 * `src/arc/security/authorization.py`. They exist so route guards and
 * navigation can name a permission once instead of repeating a string
 * literal at every call site.
 *
 * This is NOT a frontend authorization model. Nothing here grants anything:
 * the backend re-checks authentication, tenant membership and permission on
 * every request, and these values only decide what the UI offers.
 */
export const PERMISSIONS = {
  KNOWLEDGE_READ: 'knowledge:read',
  KNOWLEDGE_CREATE: 'knowledge:create',
  KNOWLEDGE_UPDATE: 'knowledge:update',
  KNOWLEDGE_DELETE: 'knowledge:delete',

  SKILL_READ: 'skill:read',
  SKILL_CREATE: 'skill:create',
  SKILL_UPDATE: 'skill:update',
  SKILL_DELETE: 'skill:delete',
  SKILL_EXECUTE: 'skill:execute',

  TOOL_READ: 'tool:read',
  TOOL_EXECUTE: 'tool:execute',

  AGENT_EXECUTE: 'agent:execute',

  APPROVAL_READ: 'approval:read',
  APPROVAL_DECIDE: 'approval:decide',

  OBSERVABILITY_READ: 'observability:read',
  OBSERVABILITY_PLATFORM_READ: 'observability:platform_read',

  CONNECTOR_READ: 'connector:read',
  CONNECTOR_CREATE: 'connector:create',
  CONNECTOR_SYNC: 'connector:sync',
  CONNECTOR_MANAGE_CREDENTIALS: 'connector:manage_credentials',

  WEBHOOK_READ: 'webhook:read',
  WEBHOOK_PROCESS: 'webhook:process',

  TENANT_READ: 'tenant:read',
  TENANT_UPDATE: 'tenant:update',
  TENANT_CREATE: 'tenant:create',
  TENANT_LIST: 'tenant:list',

  USER_READ: 'user:read',
  USER_CREATE: 'user:create',
  MEMBERSHIP_CREATE: 'membership:create',
  CAPABILITY_MANAGE: 'capability:manage',
}
