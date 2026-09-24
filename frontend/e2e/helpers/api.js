// API helpers for E2E specs: authenticated JSON calls with CSRF.
export async function csrfHeaders(context) {
  const cookies = await context.cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'arc_csrf_token')
  return csrf ? { 'X-CSRF-Token': csrf.value } : {}
}

export function apiUrl() {
  return process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'
}
