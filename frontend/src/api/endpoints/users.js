import client from '../client.js'

export async function createUser(payload) {
  const { data } = await client.post('/users', payload)
  return data
}

export async function getTenantUsers(tenantId) {
  const { data } = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/users`,
  )
  return data
}