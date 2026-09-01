import { describe, it, expect } from 'vitest'
import { decodeJwt, isJwtExpired } from './jwt.js'

const HS256_HEADER = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload))
  return `${HS256_HEADER}.${encoded}.signature`
}

describe('decodeJwt', () => {
  it('returns null for non-string input', () => {
    expect(decodeJwt(null)).toBeNull()
    expect(decodeJwt(undefined)).toBeNull()
    expect(decodeJwt(123)).toBeNull()
  })

  it('returns null for malformed tokens', () => {
    expect(decodeJwt('')).toBeNull()
    expect(decodeJwt('not-a-jwt')).toBeNull()
    expect(decodeJwt('only.two')).toBeNull()
  })

  it('decodes a valid JWT payload', () => {
    const payload = { sub: 'user-1', exp: 9999999999 }
    expect(decodeJwt(makeToken(payload))).toEqual(payload)
  })

  it('returns null if sub claim is missing', () => {
    const payload = { exp: 9999999999 }
    expect(decodeJwt(makeToken(payload))).toBeNull()
  })

  it('handles numeric sub claim', () => {
    const payload = { sub: 12345, exp: 9999999999 }
    expect(decodeJwt(makeToken(payload))).toEqual(payload)
  })

  it('rejects tokens with unknown algorithm', () => {
    const badHeader = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }))
    const payload = { sub: 'user-1', exp: 9999999999 }
    const encoded = btoa(JSON.stringify(payload))
    expect(decodeJwt(`${badHeader}.${encoded}.signature`)).toBeNull()
  })

  it('rejects tokens with RSA algorithm', () => {
    const rsaHeader = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = { sub: 'user-1', exp: 9999999999 }
    const encoded = btoa(JSON.stringify(payload))
    expect(decodeJwt(`${rsaHeader}.${encoded}.signature`)).toBeNull()
  })
})

describe('isJwtExpired', () => {
  it('returns false if no exp claim', () => {
    expect(isJwtExpired({})).toBe(false)
    expect(isJwtExpired({ sub: 'user-1' })).toBe(false)
  })

  it('returns true if token is expired', () => {
    const pastExp = Math.floor(Date.now() / 1000) - 1000
    expect(isJwtExpired({ exp: pastExp })).toBe(true)
  })

  it('returns false if token is not yet expired', () => {
    const futureExp = Math.floor(Date.now() / 1000) + 3600
    expect(isJwtExpired({ exp: futureExp })).toBe(false)
  })
})
