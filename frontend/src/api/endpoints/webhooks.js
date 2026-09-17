import client from '../client.js'

export async function listWebhookEvents(tenantId) {
  const response = await client.get(`/tenants/${tenantId}/webhooks/events`)
  return response.data.items
}
