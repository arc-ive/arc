import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { ArcIntro } from './ArcIntro.jsx'

describe('ArcIntro', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('assembles the name a letter at a time', () => {
    render(<ArcIntro onDone={vi.fn()} />)
    // Nothing on the first frame: the name arrives, it is not already there.
    expect(screen.queryByText('ARC')).not.toBeInTheDocument()

    act(() => vi.advanceTimersByTime(130))
    expect(screen.getByText('A')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(130))
    expect(screen.getByText('AR')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(130))
    expect(screen.getByText('ARC')).toBeInTheDocument()
  })

  it('finishes on its own inside three seconds', () => {
    // The brief asks for 2-4s. An entrance a person waits through twice
    // is an obstacle, however good it looks.
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)

    act(() => vi.advanceTimersByTime(2_000))
    expect(onDone).not.toHaveBeenCalled()

    act(() => vi.advanceTimersByTime(1_000))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('can be skipped with Escape', () => {
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)
    act(() => vi.advanceTimersByTime(200))

    fireEvent.keyDown(window, { key: 'Escape' })
    act(() => vi.advanceTimersByTime(400))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('can be skipped with a click', () => {
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)
    act(() => vi.advanceTimersByTime(200))

    fireEvent.pointerDown(window)
    act(() => vi.advanceTimersByTime(400))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('ignores keys that are not Escape', () => {
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)
    fireEvent.keyDown(window, { key: 'a' })
    act(() => vi.advanceTimersByTime(400))
    expect(onDone).not.toHaveBeenCalled()
  })

  it('calls onDone exactly once when skipped and then completing', () => {
    // Skip and natural completion race each other; a double call would
    // unmount a curtain that is already gone.
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    act(() => vi.advanceTimersByTime(5_000))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('is hidden from assistive technology', () => {
    // It carries no information. A screen reader should meet the
    // application, not a decorative curtain.
    const { container } = render(<ArcIntro onDone={vi.fn()} />)
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true')
  })

  it('still completes when the canvas has no 2D context', () => {
    // jsdom returns null, and a browser can too — an exhausted context
    // budget, canvas disabled. The field is decoration; the sequence must
    // not depend on it.
    const onDone = vi.fn()
    render(<ArcIntro onDone={onDone} />)
    act(() => vi.advanceTimersByTime(3_000))
    expect(onDone).toHaveBeenCalledTimes(1)
  })
})
