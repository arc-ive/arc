import client from '../client.js'

/**
 * Bounded Agent orchestration (PRD 09, V2-ADR-006).
 *
 * Starting a run requires `agent:execute`; reading run history is served
 * by the observability aggregate and requires `observability:read`. The
 * backend enforces both independently — these wrappers only shape calls.
 */

export async function runAgent(tenantId, { goal }) {
  const response = await client.post(`/agent/runs`, {
    tenant_id: tenantId,
    goal,
  })
  return response.data
}

export async function listAgentRuns(tenantId, { limit = 20, offset = 0 } = {}) {
  const response = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/observability/agent-runs`,
    { params: { limit, offset } },
  )
  return response.data
}

export async function getAgentRun(tenantId, recordId) {
  const response = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/observability/agent-runs/${encodeURIComponent(recordId)}`,
  )
  return response.data
}
