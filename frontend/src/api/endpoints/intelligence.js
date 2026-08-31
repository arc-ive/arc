import client from '../client.js'

export async function queryIntelligence(tenantId, payload) {
  const { data } = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/intelligence/query`,
    payload,
  )
  return data
}