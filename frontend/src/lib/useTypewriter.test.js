import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTypewriter } from './useTypewriter.js'

const PHRASES = ['How do I request production access?', 'What changed?']

function mockReducedMotion(reduced) {
  window.matchMedia = vi.fn().mockImplementation((q) => ({
    matches: reduced && q.includes('reduce'),
    media: q,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

describe('useTypewriter', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockReducedMotion(false)
  })
  afterEach(() => vi.useRealTimers())

  it('types a phrase one character at a time', () => {
    const { result } = renderHook(() => useTypewriter(PHRASES, true))
    expect(result.current.text).toBe('')
    act(() => vi.advanceTimersByTime(420 + 26 * 4))
    expect(PHRASES[0].startsWith(result.current.text)).toBe(true)
    expect(result.current.text.length).toBeGreaterThan(0)
    expect(result.current.text.length).toBeLessThan(PHRASES[0].length)
  })

  it('stops dead when the field is touched', () => {
    // The failure mode of this pattern is a caret racing the user's own
    // typing. `active` goes false on focus and the hook must not keep
    // writing after that.
    const { result, rerender } = renderHook(
      ({ active }) => useTypewriter(PHRASES, active),
      { initialProps: { active: true } },
    )
    act(() => vi.advanceTimersByTime(420 + 26 * 6))
    rerender({ active: false })
    act(() => vi.advanceTimersByTime(5000))
    expect(result.current.text).toBe('')
  })

  it('does not animate at all under reduced motion', () => {
    // Not a slower animation — none. The whole first question, no caret.
    mockReducedMotion(true)
    const { result } = renderHook(() => useTypewriter(PHRASES, true))
    expect(result.current.text).toBe(PHRASES[0])
    expect(result.current.done).toBe(true)
    act(() => vi.advanceTimersByTime(5000))
    expect(result.current.text).toBe(PHRASES[0])
  })

  it('handles an empty phrase list without throwing', () => {
    const { result } = renderHook(() => useTypewriter([], true))
    expect(result.current.text).toBe('')
  })
})
