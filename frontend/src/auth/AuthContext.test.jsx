import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { AuthProvider } from './AuthContext.jsx'
import { useAuth } from './useAuth.js'

vi.mock('../api/client.js', () => ({
  default: { get: vi.fn().mockRejectedValue(new Error('no session')), post: vi.fn().mockResolvedValue({}) },
  SESSION_EXPIRED_EVENT: 'arc:session-expired',
}))

describe('AuthProvider sign-out', () => {
  let href

  beforeEach(() => {
    sessionStorage.clear()
    // signOut navigates; jsdom cannot, so stand in for the assignment.
    href = ''
    delete window.location
    window.location = { get href() { return href }, set href(v) { href = v } }
  })

  afterEach(() => vi.clearAllMocks())

  it('forgets that the entrance has played', async () => {
    // sessionStorage is per-tab and survives the navigation signOut
    // performs. Left set, the next person to sign in on a shared or demo
    // machine gets no entrance — the flag would outlive its session.
    sessionStorage.setItem('arc.intro.seen', '1')

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => {
      await result.current.signOut()
    })

    expect(sessionStorage.getItem('arc.intro.seen')).toBeNull()
    expect(href).toBe('/login')
  })
})
