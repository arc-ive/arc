import client from '../client.js'

export const KNOWLEDGE_SOURCES = [
  'policy',
  'procedure',
  'incident_report',
  'troubleshooting',
  'internal_knowledge',
  'solution',
]

export async function getKnowledge(tenantId) {
  const { data } = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge`,
  )
  return data.items
}

export async function getKnowledgeDocument(tenantId, documentId) {
  const { data } = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge/${encodeURIComponent(documentId)}`,
  )
  return data
}

export async function createKnowledge(tenantId, payload) {
  const { data } = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge`,
    payload,
  )
  return data
}

export async function searchKnowledge(tenantId, query, limit = 5) {
  const { data } = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge/search`,
    { params: { query, limit } },
  )
  return data
}