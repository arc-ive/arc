import axios from 'axios'

export const SESSION_EXPIRED_EVENT = 'arc:session-expired'

/**
 * CSRF protection: With HttpOnly cookie-based sessions, the browser
 * automatically attaches cookies to same-origin requests. The CSRF
 * token is stored in a non-HttpOnly cookie and sent in a custom header
 * for state-changing requests. Bearer token clients are exempt.
 */

function getCsrfToken() {
  // Read the CSRF token from the non-HttpOnly cookie
  const cookies = document.cookie.split(';')
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=')
    if (name === 'arc_csrf_token') {
      return value
    }
  }
  return null
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // Important: sends cookies with requests
})

// Add CSRF token header for state-changing requests
client.interceptors.request.use((config) => {
  if (['post', 'put', 'patch', 'delete'].includes(config.method)) {
    const csrfToken = getCsrfToken()
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
    }
    return Promise.reject(error)
  },
)

export default client
