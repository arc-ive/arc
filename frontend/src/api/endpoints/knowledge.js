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

/**
 * Ingest a document file into the Company Brain.
 *
 * The client sets a JSON content type for every other call; multipart
 * needs the browser to set it instead, because only the browser knows
 * the boundary it generated. Passing `undefined` removes the default
 * rather than overriding it with a value that would be wrong.
 */
export async function uploadKnowledge(tenantId, { file, source, provenance }) {
  const body = new FormData()
  body.append('file', file)
  body.append('source', source)
  if (provenance) body.append('provenance', provenance)

  const { data } = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge/upload`,
    body,
    { headers: { 'Content-Type': undefined } },
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

export async function updateKnowledge(tenantId, documentId, payload) {
  const { data } = await client.put(
    `/tenants/${encodeURIComponent(tenantId)}/knowledge/${encodeURIComponent(documentId)}`,
    payload,
  )
  return data
}