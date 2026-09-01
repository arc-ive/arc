import client from '../client.js'

export async function getMe() {
  const { data } = await client.get('/auth/me')
  return data
}