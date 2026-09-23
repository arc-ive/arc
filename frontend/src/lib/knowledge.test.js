import { describe, it, expect } from 'vitest'
import {
  documentTitle,
  documentOrigin,
  originRepeatsTitle,
  groupChunksByDocument,
  splitOnQuery,
  bestPassage,
} from './knowledge.js'

describe('documentTitle', () => {
  it('uses provenance when a person wrote it', () => {
    expect(
      documentTitle({ id: 'acme-handbook', provenance: 'Acme Employee Handbook v2.1' }),
    ).toBe('Acme Employee Handbook v2.1')
  })

  it('does NOT use a connector path as a title', () => {
    // The latent bug this exists for. connector_sync.py:171 writes
    //   provenance = f"connector:{provider}:{source_id}"
    // and the page rendered provenance as the headline, so the first real
    // sync would have turned every card title into a connector path. No
    // demo with seeded data would have shown it.
    const title = documentTitle({
      id: 'ref-acme-readme',
      provenance: 'connector:github:arc-ive/arc/docs/README.md',
    })
    expect(title).not.toContain('connector:')
    // Original filename casing is preserved — "README" is how the file is
    // actually named, and lowercasing it would be less faithful, not more
    // human.
    expect(title).toBe('README')
  })

  it('falls back to a de-slugged document id when provenance is missing', () => {
    expect(documentTitle({ id: 'ref-acme-technologies-it-service-guide' })).toBe(
      'Ref-acme-technologies-it-service-guide'.replace(/-/g, ' ').trim()
        .replace(/^./, (c) => c.toUpperCase()),
    )
  })

  it('accepts a search chunk, which names the id document_id', () => {
    expect(documentTitle({ document_id: 'my-doc', provenance: 'Runbook' })).toBe('Runbook')
  })

  it('never returns an empty label', () => {
    expect(documentTitle({})).toBe('Untitled document')
    expect(documentTitle()).toBe('Untitled document')
  })
})

describe('documentOrigin', () => {
  it('renders a connector path as provider and reference', () => {
    expect(
      documentOrigin({ provenance: 'connector:github:arc-ive/arc/docs/README.md' }),
    ).toBe('Github · arc-ive/arc/docs/README.md')
  })

  it('passes a human provenance through', () => {
    expect(documentOrigin({ provenance: 'Acme Handbook' })).toBe('Acme Handbook')
  })

  it('is null when there is no provenance', () => {
    expect(documentOrigin({})).toBeNull()
  })

  it('detects when the origin would merely repeat the title', () => {
    // Showing the headline again directly underneath itself is noise.
    const doc = { id: 'x', provenance: 'Acme Handbook' }
    expect(originRepeatsTitle(doc)).toBe(true)
    expect(originRepeatsTitle({ id: 'x', provenance: 'connector:slack:C123' })).toBe(false)
  })
})

describe('groupChunksByDocument', () => {
  it('collapses several chunks of one document into a single result', () => {
    // The search endpoint returns CHUNKS, so a document matching in three
    // places came back as three cards competing with each other. Users
    // search for documents.
    const grouped = groupChunksByDocument([
      { document_id: 'a', content: 'first', source: 'policy', document_version: 6 },
      { document_id: 'a', content: 'second', source: 'policy', document_version: 6 },
      { document_id: 'b', content: 'other', source: 'procedure', document_version: 2 },
    ])
    expect(grouped).toHaveLength(2)
    expect(grouped[0].passages).toEqual(['first', 'second'])
    expect(grouped[1].documentId).toBe('b')
  })

  it("preserves the backend's ranking order", () => {
    const grouped = groupChunksByDocument([
      { document_id: 'z', content: '1' },
      { document_id: 'a', content: '2' },
    ])
    expect(grouped.map((g) => g.documentId)).toEqual(['z', 'a'])
  })

  it('handles an empty result set', () => {
    expect(groupChunksByDocument([])).toEqual([])
    expect(groupChunksByDocument()).toEqual([])
  })
})

describe('splitOnQuery', () => {
  it('marks the query terms inside a passage', () => {
    const segments = splitOnQuery('review the handbook during onboarding', 'handbook')
    expect(segments.filter((s) => s.match).map((s) => s.text)).toEqual(['handbook'])
  })

  it('is case-insensitive', () => {
    const segments = splitOnQuery('The Handbook', 'handbook')
    expect(segments.some((s) => s.match)).toBe(true)
  })

  it('ignores very short terms so the passage is not confetti', () => {
    // Terms of 1-2 characters are dropped. This is a length rule, not a
    // stopword list: "the" is 3 characters and will still match, which is
    // an accepted limitation rather than an oversight.
    const segments = splitOnQuery('a leave policy of an item', 'a of an')
    expect(segments.some((s) => s.match)).toBe(false)
  })

  it('returns the text intact when there is no query', () => {
    expect(splitOnQuery('hello', '')).toEqual([{ text: 'hello', match: false }])
  })
})

describe('bestPassage', () => {
  it('prefers a passage that actually contains a query term', () => {
    // Showing a non-matching opening paragraph makes a good result look
    // irrelevant.
    expect(
      bestPassage(['intro with nothing', 'the leave policy is annual'], 'leave'),
    ).toBe('the leave policy is annual')
  })

  it('falls back to the first passage when nothing matches', () => {
    expect(bestPassage(['only one'], 'absent')).toBe('only one')
  })

  it('handles no passages', () => {
    expect(bestPassage([], 'x')).toBe('')
  })
})
