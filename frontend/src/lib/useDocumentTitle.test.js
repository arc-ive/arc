import { describe, it, expect } from 'vitest'
import { documentTitleFor, APP_NAME } from './useDocumentTitle.js'

describe('documentTitleFor', () => {
  it('names the page before the product', () => {
    // Every route shipped as "Arc" — the same string in the tab, the
    // history menu, every bookmark, and every screen-reader page
    // announcement. The page name leads because that is the part that
    // distinguishes one entry from another in a list of them.
    expect(documentTitleFor('Usage')).toBe(`Usage · ${APP_NAME}`)
  })

  it('does not repeat the product name', () => {
    expect(documentTitleFor('Arc')).toBe('Arc')
  })

  it('falls back to the product name alone', () => {
    expect(documentTitleFor('')).toBe(APP_NAME)
    expect(documentTitleFor(undefined)).toBe(APP_NAME)
    expect(documentTitleFor('   ')).toBe(APP_NAME)
  })
})
