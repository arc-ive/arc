/**
 * Session management for Google OIDC authentication.
 *
 * Server-side sessions are managed via HttpOnly cookies. This module
 * provides helper functions for session state management on the client.
 * The actual session cookie is set by the server and is not accessible
 * to JavaScript (HttpOnly).
 *
 * Previous JWT-in-sessionStorage architecture has been removed in favor
 * of secure server-side sessions.
 */

const DEMO_KEY = 'arc.demoMode'

export function isDemoMode() {
  return import.meta.env.DEV && sessionStorage.getItem(DEMO_KEY) === '1'
}

export function enterDemoMode() {
  if (!import.meta.env.DEV) return
  sessionStorage.setItem(DEMO_KEY, '1')
}

export function exitDemoMode() {
  sessionStorage.removeItem(DEMO_KEY)
}

/**
 * Clear all client-side auth state.
 * The server-side session is invalidated separately via POST /auth/logout.
 */
export function clearAuthState() {
  sessionStorage.removeItem(DEMO_KEY)
}
