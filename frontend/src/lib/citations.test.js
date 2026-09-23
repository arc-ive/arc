import { describe, it, expect } from 'vitest'
import { parseCitation, parseCitations, groundingSummary } from './citations.js'

const TENANT = 'ref-acme-technologies'

describe('parseCitation', () => {
  it('separates the document from the chunk index', () => {
    // The contract returns `{document_id}#c{chunk_index}`. The chunk index
    // is a retrieval detail that changes whenever a document is re-chunked
    // — ARC_UX_SPEC.md §2 rules it out of the UI.
    const c = parseCitation(`${TENANT}-employee-handbook#c0`, TENANT)
    expect(c.documentId).toBe(`${TENANT}-employee-handbook`)
    expect(c.chunkIndex).toBe(0)
  })

  it('never puts a chunk id in the label', () => {
    const c = parseCitation(`${TENANT}-employee-handbook#c3`, TENANT)
    expect(c.label).not.toContain('#c')
    expect(c.label).toBe('Employee handbook')
  })

  it('strips the tenant prefix from the label', () => {
    // Repeating the workspace name inside every source, on a page that
    // already names the workspace in the sidebar, is noise.
    expect(parseCitation(`${TENANT}-it-service-guide#c0`, TENANT).label).toBe(
      'It service guide',
    )
  })

  it('keeps an unparseable citation rather than dropping it', () => {
    // Losing a source silently is worse than showing an ugly one.
    const c = parseCitation('something-odd', TENANT)
    expect(c.documentId).toBe('something-odd')
    expect(c.chunkIndex).toBeNull()
  })

  it('returns null for empty input', () => {
    expect(parseCitation('')).toBeNull()
    expect(parseCitation(undefined)).toBeNull()
  })
})

describe('parseCitations', () => {
  it('collapses several chunks of one document into one source', () => {
    // A reader following sources wants the documents, not the slices.
    const sources = parseCitations(
      [`${TENANT}-handbook#c0`, `${TENANT}-handbook#c3`, `${TENANT}-guide#c1`],
      TENANT,
    )
    expect(sources).toHaveLength(2)
    expect(sources[0].chunkCount).toBe(2)
  })

  it('preserves citation order', () => {
    const sources = parseCitations([`${TENANT}-z#c0`, `${TENANT}-a#c0`], TENANT)
    expect(sources.map((s) => s.label)).toEqual(['Z', 'A'])
  })

  it('handles no citations', () => {
    expect(parseCitations([], TENANT)).toEqual([])
    expect(parseCitations(undefined, TENANT)).toEqual([])
  })
})

describe('groundingSummary', () => {
  it('states how many documents grounded the answer', () => {
    expect(
      groundingSummary(
        { context_used: true, citations: [`${TENANT}-a#c0`, `${TENANT}-b#c0`] },
        TENANT,
      ),
    ).toBe('Answered from 2 documents in your Company Brain.')
  })

  it('uses the singular for one document', () => {
    expect(
      groundingSummary({ context_used: true, citations: [`${TENANT}-a#c0`] }, TENANT),
    ).toBe('Answered from 1 document in your Company Brain.')
  })

  it('says so plainly when nothing matched', () => {
    expect(groundingSummary({ context_used: false, citations: [] }, TENANT)).toContain(
      'no matching documents',
    )
  })

  it('never mentions the retrieval algorithm', () => {
    // It replaced a definition list reading `Retrieval method: hybrid_rrf`,
    // `Context used: Yes`, `Principal: <the reader's own id>`.
    const summary = groundingSummary(
      { context_used: true, citations: [`${TENANT}-a#c0`], retrieval_method: 'hybrid_rrf' },
      TENANT,
    )
    expect(summary).not.toContain('hybrid')
    expect(summary).not.toContain('rrf')
    expect(summary).not.toContain('Context used')
  })
})
