import { describe, it, expect } from 'vitest'
import { deliveryStage, retryState, payloadSize } from './webhookEvents.js'

describe('deliveryStage', () => {
  it('does not treat a received event as a success', () => {
    // The page showed a green tick for `received` and a warning for
    // everything else, which inverts the meaning: `received` means Arc has
    // the event and has NOT processed it. An operator scanning for
    // problems was shown ticks against the events still in flight.
    const stage = deliveryStage({ status: 'received' })
    expect(stage.tone).not.toBe('success')
    expect(stage.label).toBe('In flight')
  })

  it('treats processed as the success state', () => {
    expect(deliveryStage({ status: 'processed' })).toMatchObject({
      label: 'Delivered',
      tone: 'success',
    })
  })

  it('treats failed as the only state needing a person', () => {
    expect(deliveryStage({ status: 'failed' }).tone).toBe('danger')
  })

  it('shows an unrecognised status rather than hiding it', () => {
    const stage = deliveryStage({ status: 'some_new_state' })
    expect(stage.label).toBe('Some new state')
    expect(stage.label).not.toContain('_')
  })
})

describe('retryState', () => {
  it('says nothing about a delivered event', () => {
    // A delivered event must render no retry line at all.
    expect(retryState({ status: 'processed', retry_count: 2, max_retries: 5 })).toBeNull()
    expect(retryState(null)).toBeNull()
  })

  it('distinguishes a pending retry from an exhausted one', () => {
    // These are different problems: one needs patience, one needs a
    // person. Collapsing them loses the only thing worth knowing.
    const pending = retryState({ status: 'failed', retry_count: 2, max_retries: 5 })
    const exhausted = retryState({ status: 'failed', retry_count: 5, max_retries: 5 })

    expect(pending.exhausted).toBe(false)
    expect(pending.text).toMatch(/Attempt 3 of 5/)
    expect(exhausted.exhausted).toBe(true)
    expect(exhausted.text).toMatch(/Gave up after 5 attempts/)
  })

  it('includes when the next attempt happens, when known', () => {
    const soon = new Date(Date.now() + 8 * 60_000).toISOString()
    expect(
      retryState({ status: 'failed', retry_count: 1, max_retries: 5, next_retry_at: soon }).text,
    ).toMatch(/retries in 8 minutes/)
  })
})

describe('payloadSize', () => {
  it('reads as a size, not a byte count', () => {
    expect(payloadSize(512)).toBe('512 B')
    expect(payloadSize(2048)).toBe('2.0 KB')
    expect(payloadSize(2 * 1024 * 1024)).toBe('2.0 MB')
  })

  it('returns null rather than a fake zero when absent', () => {
    expect(payloadSize(undefined)).toBeNull()
    expect(payloadSize(-1)).toBeNull()
  })
})
