import client from '../client.js'

export async function runAgent(tenantId, { goal }) {
  const response = await client.post(
    `/agent/runs`,
    { goal },
    { params: { tenant_id: tenantId } },
  )
  return response.data
}
