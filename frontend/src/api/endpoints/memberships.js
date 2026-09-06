import client from '../client.js'

export async function createTenantMembership(tenantId, payload) {
  const { data } = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/memberships`,
    payload,
  )
  return data
}

export async function deleteTenantMembership(tenantId, userId) {
  const { data } = await client.delete(
    `/tenants/${encodeURIComponent(tenantId)}/memberships/${encodeURIComponent(userId)}`,
  )
  return data
}
