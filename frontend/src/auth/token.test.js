import { describe, it, expect, beforeEach } from 'vitest'
import { getToken, setToken, clearToken } from './token.js'

describe('token storage', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('returns null when no token is stored', () => {
    expect(getToken()).toBeNull()
  })

  it('stores and retrieves a token', () => {
    setToken('test-jwt-token')
    expect(getToken()).toBe('test-jwt-token')
  })

  it('clears the stored token', () => {
    setToken('test-jwt-token')
    clearToken()
    expect(getToken()).toBeNull()
  })

  it('overwrites an existing token', () => {
    setToken('token-1')
    setToken('token-2')
    expect(getToken()).toBe('token-2')
  })
})
