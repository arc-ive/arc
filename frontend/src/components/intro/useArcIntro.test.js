import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useArcIntro, clearArcIntroSeen } from './useArcIntro.js'

function mockReducedMotion(reduced) {
  window.matchMedia = vi.fn().mockImplementation((q) => ({
    matches: reduced && q.includes('reduce'),
    media: q,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

describe('useArcIntro', () => {
  beforeEach(() => {
    sessionStorage.clear()
    mockReducedMotion(false)
  })

  it('plays after a sign-in', () => {
    const { result } = renderHook(() => useArcIntro(true))
    expect(result.current.showIntro).toBe(true)
  })

  it('never plays before authentication', () => {
    // It is a curtain, not a gate. Showing it to an unauthenticated
    // visitor would put an animation in front of the login form.
    const { result } = renderHook(() => useArcIntro(false))
    expect(result.current.showIntro).toBe(false)
  })

  it('plays once per session, not on every navigation', () => {
    const first = renderHook(() => useArcIntro(true))
    expect(first.result.current.showIntro).toBe(true)
    act(() => first.result.current.onIntroDone())
    expect(first.result.current.showIntro).toBe(false)

    const second = renderHook(() => useArcIntro(true))
    expect(second.result.current.showIntro).toBe(false)
  })

  it('does not play under prefers-reduced-motion', () => {
    // Skipped outright, not slowed: a warp toward the viewer is exactly
    // the motion that setting exists to prevent.
    mockReducedMotion(true)
    const { result } = renderHook(() => useArcIntro(true))
    expect(result.current.showIntro).toBe(false)
  })

  it('fails closed when session storage is unavailable', () => {
    // Private mode and blocked site data make the accessor THROW, not
    // return null. A decoration that cannot check whether it already
    // played should not play.
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage')
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get() {
        throw new Error('blocked')
      },
    })

    const { result } = renderHook(() => useArcIntro(true))
    expect(result.current.showIntro).toBe(false)
    // And finishing must not throw either.
    expect(() => act(() => result.current.onIntroDone())).not.toThrow()

    Object.defineProperty(window, 'sessionStorage', original)
  })

  it('can be reset so a later sign-in plays again', () => {
    const { result } = renderHook(() => useArcIntro(true))
    act(() => result.current.onIntroDone())
    clearArcIntroSeen()
    expect(renderHook(() => useArcIntro(true)).result.current.showIntro).toBe(true)
  })
})
