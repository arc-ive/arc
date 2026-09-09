import { describe, it, expect, beforeEach } from 'vitest'
import { isDemoMode, enterDemoMode, exitDemoMode, clearAuthState } from './token.js'

describe('token storage', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('returns false when no demo mode is set', () => {
    expect(isDemoMode()).toBe(false)
  })

  it('enters demo mode', () => {
    enterDemoMode()
    expect(isDemoMode()).toBe(true)
  })

  it('exits demo mode', () => {
    enterDemoMode()
    exitDemoMode()
    expect(isDemoMode()).toBe(false)
  })

  it('clearAuthState removes demo mode', () => {
    enterDemoMode()
    clearAuthState()
    expect(isDemoMode()).toBe(false)
  })
})
