import client from '../client.js'

export async function listApprovals(tenantId, { status } = {}) {
  const params = {}
  if (status) params.status = status
  const response = await client.get(`/tenants/${encodeURIComponent(tenantId)}/approvals`, {
    params,
  })
  return response.data.items
}

export async function getApproval(tenantId, approvalId) {
  const response = await client.get(
    `/tenants/${encodeURIComponent(tenantId)}/approvals/${encodeURIComponent(approvalId)}`,
  )
  return response.data
}

export async function decideApproval(tenantId, approvalId, decision) {
  const response = await client.post(
    `/tenants/${encodeURIComponent(tenantId)}/approvals/${encodeURIComponent(approvalId)}/decisions`,
    { decision },
  )
  return response.data
}
