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

export async function updateSkill(tenantId, skillId, data) {
  const response = await client.put(`/skills/${skillId}`, data, {
    params: { tenant_id: tenantId },
  })
  return response.data
}

export async function deleteSkill(tenantId, skillId) {
  await client.delete(`/skills/${skillId}`, {
    params: { tenant_id: tenantId },
  })
}

export async function executeSkill(tenantId, skillId, body) {
  const response = await client.post(`/skills/${skillId}/execute`, body, {
    params: { tenant_id: tenantId },
  })
  return response.data
}
