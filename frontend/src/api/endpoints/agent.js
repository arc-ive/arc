import client from '../client.js'

export async function runAgent(tenantId, { goal }) {
  const response = await client.post(`/agent/runs`, {
    tenant_id: tenantId,
    goal,
  })
  return response.data
}
