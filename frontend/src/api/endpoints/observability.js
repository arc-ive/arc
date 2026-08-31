import client from '../client.js'

export async function getTenantUsageSummary(tenantId, { hours = 24 } = {}) {
  const response = await client.get(`/tenants/${tenantId}/observability/usage-summary`, {
    params: { hours },
  })
  return response.data
}

export async function getPlatformObservabilitySummary() {
  const response = await client.get('/platform/observability/summary')
  return response.data
}

export async function getComponentHealth() {
  const response = await client.get('/observability/health')
  return response.data
}
