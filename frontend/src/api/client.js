import axios from 'axios'
import { getToken, clearToken } from '../auth/token.js'

export const SESSION_EXPIRED_EVENT = 'arc:session-expired'

/**
 * CSRF note: Bearer tokens are NOT automatically attached by the browser
 * to cross-origin requests. CSRF relies on automatic credential attachment
 * (cookies). The Authorization header must be explicitly set by JavaScript,
 * making CSRF inapplicable to the current authentication model.
 */

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken()
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
    }
    return Promise.reject(error)
  },
)

export default client