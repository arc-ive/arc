import client from '../client.js'

export async function createUser(payload) {
  const { data } = await client.post('/users', payload)
  return data
}

export async function listPlatformUsers() {
  const { data } = await client.get('/platform/users')
  return data.items
}

export async function getTenantUsers(tenantId) {
  const { data } = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/users`,
  )
  return data.items
}