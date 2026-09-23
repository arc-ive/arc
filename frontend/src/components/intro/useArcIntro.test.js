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

  describe('the real sign-in lifecycle', () => {
    // RequireAuth renders BEFORE the session check resolves, so every real
    // sign-in reaches this hook as false-then-true. Reading the flag once
    // in a useState initializer latched "skip" forever and the entrance
    // never ran in the product — passing tests that only ever mounted with
    // a fixed value. These start where the app starts.
    function renderTransitioning(initial = false) {
      return renderHook(({ authed }) => useArcIntro(authed), {
        initialProps: { authed: initial },
      })
    }

    it('plays when authentication resolves after the first render', () => {
      const { result, rerender } = renderTransitioning()
      expect(result.current.showIntro).toBe(false)

      rerender({ authed: true })
      expect(result.current.showIntro).toBe(true)
    })

    it('does not replay for a session that has already seen it', () => {
      sessionStorage.setItem('arc.intro.seen', '1')
      const { result, rerender } = renderTransitioning()
      rerender({ authed: true })
      expect(result.current.showIntro).toBe(false)
    })

    it('still honours prefers-reduced-motion across the transition', () => {
      mockReducedMotion(true)
      const { result, rerender } = renderTransitioning()
      rerender({ authed: true })
      expect(result.current.showIntro).toBe(false)
    })

    it('still fails closed across the transition when storage throws', () => {
      const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage')
      Object.defineProperty(window, 'sessionStorage', {
        configurable: true,
        get() {
          throw new Error('blocked')
        },
      })

      const { result, rerender } = renderTransitioning()
      rerender({ authed: true })
      expect(result.current.showIntro).toBe(false)

      Object.defineProperty(window, 'sessionStorage', original)
    })

    it('marks the session seen, so a later remount does not replay', () => {
      const { result, rerender } = renderTransitioning()
      rerender({ authed: true })
      act(() => result.current.onIntroDone())
      expect(result.current.showIntro).toBe(false)

      // A route change remounts RequireAuth's subtree; the entrance must
      // not come back with it.
      expect(renderHook(() => useArcIntro(true)).result.current.showIntro).toBe(false)
    })

    it('does not open the curtain when a session is lost mid-visit', () => {
      // Expiry drives isAuthenticated back to false. That is a falling
      // edge, and the answer to it is the login page, not an animation.
      const { result, rerender } = renderTransitioning(true)
      act(() => result.current.onIntroDone())

      rerender({ authed: false })
      expect(result.current.showIntro).toBe(false)
      rerender({ authed: true })
      expect(result.current.showIntro).toBe(false)
    })
  })
})
