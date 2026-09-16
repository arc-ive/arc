import client from '../client.js'

export async function listConnectors(tenantId) {
  const response = await client.get(`/tenants/${tenantId}/connectors`)
  return response.data.items
}

export async function createConnector(tenantId, { provider, name, target }) {
  const response = await client.post(`/tenants/${tenantId}/connectors`, {
    provider,
    name,
    target,
  })
  return response.data
}

export async function syncConnector(tenantId, connectorId) {
  const response = await client.post(`/tenants/${tenantId}/connectors/${connectorId}/sync`)
  return response.data
}
