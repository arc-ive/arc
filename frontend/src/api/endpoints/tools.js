import client from '../client.js'

export async function listTools(tenantId) {
  const response = await client.get(`/tenants/${tenantId}/tools`)
  return response.data
}

export async function executeTool(tenantId, toolName, input = {}) {
  const response = await client.post(`/tenants/${tenantId}/tools/${toolName}/execute`, {
    input,
  })
  return response.data
}
