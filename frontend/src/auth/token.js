/**
 * Client-side auth state.
 *
 * Sessions are server-side, in an HttpOnly cookie the browser sets and
 * JavaScript cannot read. The client therefore holds no credential of its
 * own; this module exists only to clear the small amount of local state the
 * app keeps alongside a session.
 */

/**
 * Clear all client-side auth state.
 *
 * The server-side session is invalidated separately via POST /auth/logout.
 */
export function clearAuthState() {
  // Nothing is persisted client-side today. Kept as the single call site
  // for sign-out so future local state has one place to be cleared.
}
