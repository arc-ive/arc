export const queryKeys = {
  health: ['health'],
  me: (userId) => ['auth', 'me', userId],
  platformUsers: () => ['platform', 'users'],
  platformTenants: () => ['platform', 'tenants'],
  userTenants: (userId) => ['users', userId, 'tenants'],
  tenant: (tenantId) => ['tenants', tenantId],
  tenantUsers: (tenantId) => ['tenants', tenantId, 'users'],
  knowledge: (tenantId) => ['tenants', tenantId, 'knowledge'],
  knowledgeDocument: (tenantId, documentId) => [
    'tenants',
    tenantId,
    'knowledge',
    documentId,
  ],
  knowledgeSearch: (tenantId, query, limit) => [
    'tenants',
    tenantId,
    'knowledge',
    'search',
    query,
    limit,
  ],
  intelligenceQuery: (tenantId, query, limit) => [
    'tenants',
    tenantId,
    'intelligence',
    'query',
    query,
    limit,
  ],
  skills: (tenantId) => ['tenants', tenantId, 'skills'],
  skill: (tenantId, skillId) => ['tenants', tenantId, 'skills', skillId],
  tools: (tenantId) => ['tenants', tenantId, 'tools'],
  connectors: (tenantId) => ['tenants', tenantId, 'connectors'],
  webhookEvents: (tenantId) => ['tenants', tenantId, 'webhooks', 'events'],
  observabilityTenant: (tenantId, hours) => [
    'tenants',
    tenantId,
    'observability',
    'usage-summary',
    hours,
  ],
  observabilityPlatform: () => ['observability', 'platform', 'summary'],
  healthComponents: () => ['observability', 'health'],
  approvals: (tenantId) => ['tenants', tenantId, 'approvals'],
  // The status filter is part of the key: the server filters, so two
  // filters are two different results and must not share a cache entry.
  // Keeping the prefix above unchanged means invalidating `approvals`
  // still refreshes every status variant after a decision.
  approvalsList: (tenantId, status) => [
    'tenants',
    tenantId,
    'approvals',
    'list',
    status ?? 'all',
  ],
  approval: (tenantId, approvalId) => [
    'tenants',
    tenantId,
    'approvals',
    approvalId,
  ],
}

export default queryKeys
