import client from '../client.js'

export async function getUserTenants(userId) {
  const { data } = await client.get(`/users/${encodeURIComponent(userId)}/tenants`)
  return data
}

export async function getTenant(tenantId) {
  const { data } = await client.get(`/tenants/${encodeURIComponent(tenantId)}`)
  return data
}

export async function createTenant(payload) {
  const { data } = await client.post('/tenants', payload)
  return data
}

export async function updateTenant(tenantId, payload) {
  const { data } = await client.put(`/tenants/${encodeURIComponent(tenantId)}`, payload)
  return data
}