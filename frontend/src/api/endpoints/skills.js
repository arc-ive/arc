import client from '../client.js'

export async function listSkills(tenantId) {
  const response = await client.get(`/tenants/${encodeURIComponent(tenantId)}/skills`)
  return response.data.items
}

export async function getSkill(tenantId, skillId) {
  const response = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/skills/${encodeURIComponent(skillId)}`,
  )
  return response.data
}

export async function createSkill(tenantId, skill) {
  const response = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/skills`,
    skill,
  )
  return response.data
}

export async function updateSkill(tenantId, skillId, data) {
  const response = await client.put(
    `/tenants/${encodeURIComponent(tenantId)}/skills/${encodeURIComponent(skillId)}`,
    data,
  )
  return response.data
}

export async function deleteSkill(tenantId, skillId) {
  await client.delete(
    `/tenants/${encodeURIComponent(tenantId)}/skills/${encodeURIComponent(skillId)}`,
  )
}

export async function executeSkill(tenantId, skillId, body) {
  const response = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/skills/${encodeURIComponent(skillId)}/execute`,
    body,
  )
  return response.data
}
