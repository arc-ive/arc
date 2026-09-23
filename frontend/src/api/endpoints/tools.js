import client from '../client.js'

export async function listTools(tenantId) {
  const response = await client.get(`/tenants/${tenantId}/tools`)
  return response.data.items
}

export async function executeTool(tenantId, toolName, input = {}, approvalId = null) {
  // Resuming an approved call sends the approval alone: the server holds
  // the exact approved arguments and re-checks them against the approval
  // digest. Re-sending arguments from the client would be re-asserting
  // what was approved rather than replaying it.
  const body = approvalId ? { approval_id: approvalId } : { input }
  const response = await client.post(
    `/tenants/${tenantId}/tools/${toolName}/execute`,
    body,
  )
  return response.data
}
