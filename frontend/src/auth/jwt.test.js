import { describe, it, expect } from 'vitest'
import { decodeJwt, isJwtExpired } from './jwt.js'

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
    const encoded = btoa(JSON.stringify(payload))
    const token = `header.${encoded}.signature`
    expect(decodeJwt(token)).toEqual(payload)
  })

  it('returns null if sub claim is missing', () => {
    const payload = { exp: 9999999999 }
    const encoded = btoa(JSON.stringify(payload))
    const token = `header.${encoded}.signature`
    expect(decodeJwt(token)).toBeNull()
  })

  it('handles numeric sub claim', () => {
    const payload = { sub: 12345, exp: 9999999999 }
    const encoded = btoa(JSON.stringify(payload))
    const token = `header.${encoded}.signature`
    expect(decodeJwt(token)).toEqual(payload)
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
