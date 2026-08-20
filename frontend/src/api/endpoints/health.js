import client from '../client.js'

export async function getHealth() {
  const { data } = await client.get('/health')
  return data
}