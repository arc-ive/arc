export const queryKeys = {
  health: ['health'],
  me: (userId) => ['auth', 'me', userId],
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
}

export default queryKeys