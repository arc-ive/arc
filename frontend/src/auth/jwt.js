/**
 * Allowed JWT algorithms for frontend decoding.
 * Defense-in-depth only — the backend independently verifies signatures.
 */
const ALLOWED_ALGORITHMS = new Set(['HS256'])

function decodeSegment(segment) {
  const base64 = segment.replace(/-/g, '+').replace(/_/g, '/')
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
  const decoded = atob(padded)
  const bytes = new Uint8Array(decoded.length)
  for (let i = 0; i < decoded.length; i += 1) {
    bytes[i] = decoded.charCodeAt(i)
  }
  return new TextDecoder().decode(bytes)
}

/**
 * Decodes a JWT payload without verifying the signature.
 * The backend remains authoritative — this is only used for
 * client-side identity (sub) and session expiry (exp) awareness.
 */
export function decodeJwt(token) {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    const header = JSON.parse(decodeSegment(parts[0]))
    if (header?.alg && !ALLOWED_ALGORITHMS.has(header.alg)) return null

    const payload = JSON.parse(decodeSegment(parts[1]))
    if (typeof payload?.sub !== 'string' && typeof payload?.sub !== 'number') {
      return null
    }
    return payload
  } catch {
    return null
  }
}

export function isJwtExpired(payload) {
  if (!payload?.exp) return false
  return Date.now() >= payload.exp * 1000
}