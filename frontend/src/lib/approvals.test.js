import { describe, it, expect } from 'vitest'
import { toolLabel, formatSummary } from './approvals.js'

describe('toolLabel', () => {
  it('turns a registry key into something a person would read', () => {
    // The card heading was rendering `grant_temporary_access` verbatim.
    // ARC_UX_SPEC.md §2 rules implementation identifiers out of the UI.
    expect(toolLabel('grant_temporary_access')).toBe('Grant temporary access')
  })

  it('capitalises only the first word', () => {
    // These read as actions. Title-casing every word turns a sentence into
    // a product name.
    expect(toolLabel('check_service_health')).toBe('Check service health')
  })

  it('handles hyphens and dots the same way', () => {
    expect(toolLabel('rotate-signing.key')).toBe('Rotate signing key')
  })

  it('never returns an empty heading', () => {
    // A card with no heading is worse than a card with a dull one.
    expect(toolLabel('')).toBe('Unnamed action')
    expect(toolLabel(undefined)).toBe('Unnamed action')
    expect(toolLabel('___')).toBe('Unnamed action')
  })
})

describe('formatSummary', () => {
  it('shows what the requester wrote, not the field it was written into', () => {
    expect(formatSummary('{"justification": "Rotate the expired signing key"}')).toBe(
      'Rotate the expired signing key',
    )
  })

  it('accepts an already-parsed object', () => {
    expect(formatSummary({ justification: 'Restore the nightly backup job' })).toBe(
      'Restore the nightly backup job',
    )
  })

  it('joins several arguments readably', () => {
    expect(formatSummary({ reason: 'Incident triage', scope: 'read-only' })).toBe(
      'Incident triage · read-only',
    )
  })

  it('keeps a plain sentence that is not JSON', () => {
    expect(formatSummary('Needed for the migration')).toBe('Needed for the migration')
  })

  it('handles a missing summary', () => {
    expect(formatSummary(null)).toBe('')
    expect(formatSummary(undefined)).toBe('')
  })
})
