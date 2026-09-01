/**
 * JWT bearer-token storage.
 *
 * Storage: sessionStorage — cleared when the browser tab closes, not
 * persisted across sessions. Accessible to JavaScript (XSS risk), but
 * the backend remains the authentication and authorization authority on
 * every request. This token is a session credential only.
 *
 * Alternative: HttpOnly cookies would prevent JS access but introduce
 * CSRF surface and require SameSite/CSRF-token infrastructure not
 * present in the current bearer-token architecture.
 */
const TOKEN_KEY = 'arc.accessToken'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY)
}