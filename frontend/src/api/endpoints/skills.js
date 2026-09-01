import client from '../client.js'

export async function listSkills(tenantId) {
  const response = await client.get('/skills', {
    params: { tenant_id: tenantId },
  })
  return response.data
}

export async function getSkill(tenantId, skillId) {
  const response = await client.get(`/skills/${skillId}`, {
    params: { tenant_id: tenantId },
  })
  return response.data
}

export async function createSkill(tenantId, skill) {
  const response = await client.post('/skills', skill, {
    params: { tenant_id: tenantId },
  })
  return response.data
}

export async function deleteSkill(tenantId, skillId) {
  await client.delete(`/skills/${skillId}`, {
    params: { tenant_id: tenantId },
  })
}
