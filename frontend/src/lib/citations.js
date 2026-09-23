import { documentTitle } from './knowledge.js'

/**
 * Citation strings from the Unified Intelligence answer.
 *
 * `POST ~/intelligence/query` returns citations as raw strings shaped
 * `{document_id}#c{chunk_index}`:
 *
 *     ref-acme-technologies-employee-handbook#c0
 *
 * The page rendered them verbatim, in monospace, under a heading reading
 * "Sources & Provenance". ARC_UX_SPEC.md §2 prohibits exactly this:
 * "Avoid exposing chunk IDs, embedding details, repository names or other
 * implementation concepts."
 *
 * The chunk index is a retrieval detail with no meaning to a reader — it
 * says which slice of a document matched, which changes every time the
 * document is re-chunked. The document is the part worth showing, and it
 * is something the reader can open: employees hold `knowledge:read` and
 * `GET ~/knowledge/{document_id}` returns 200 for them.
 */

/**
 * Parse one citation into something presentable.
 *
 * Returns `{ documentId, chunkIndex, label }`. Unparseable citations keep
 * their raw value as the label rather than being dropped — losing a source
 * silently would be worse than showing an ugly one.
 */
export function parseCitation(citation, tenantId) {
  const raw = String(citation ?? '').trim()
  if (!raw) return null

  const match = raw.match(/^(.+?)#c(\d+)$/)
  const documentId = match ? match[1] : raw
  const chunkIndex = match ? Number(match[2]) : null

  return {
    documentId,
    chunkIndex,
    // Document ids are tenant-prefixed ("ref-acme-technologies-employee-
    // handbook"). Repeating the workspace name inside every source label,
    // on a page that already names the workspace in the sidebar, is noise.
    label: documentTitle({ id: stripTenantPrefix(documentId, tenantId) }),
    raw,
  }
}

function stripTenantPrefix(documentId, tenantId) {
  if (!tenantId) return documentId
  const prefix = `${tenantId}-`
  return documentId.startsWith(prefix) ? documentId.slice(prefix.length) : documentId
}

/**
 * Parse and de-duplicate an answer's citations.
 *
 * Several chunks of one document cite as separate strings
 * (`…handbook#c0`, `…handbook#c3`). A reader following sources wants the
 * list of documents, not the list of slices, so repeats collapse and the
 * numbering counts documents.
 */
export function parseCitations(citations = [], tenantId) {
  const seen = new Map()

  for (const citation of citations) {
    const parsed = parseCitation(citation, tenantId)
    if (!parsed) continue
    const existing = seen.get(parsed.documentId)
    if (existing) {
      existing.chunkCount += 1
      continue
    }
    seen.set(parsed.documentId, { ...parsed, chunkCount: 1 })
  }

  return [...seen.values()]
}

/**
 * How the answer was grounded, in a sentence.
 *
 * Replaces a definition list that read:
 *
 *     Retrieval method   hybrid_rrf
 *     Context used       Yes
 *     Principal          ref-acme-technologies-employee-1
 *
 * `hybrid_rrf` is the retrieval algorithm (V2-ADR-007); `context_used` is
 * a boolean field name; `principal_id` is the reader's own identity echoed
 * back at them. None of it is a fact the reader needs, and the first is
 * explicitly the kind of internal §2 rules out.
 */
export function groundingSummary({ context_used: contextUsed, citations } = {}, tenantId) {
  const count = parseCitations(citations, tenantId).length

  if (!contextUsed) {
    return 'Answered without company knowledge — no matching documents were found.'
  }
  if (count === 0) return 'Answered from your Company Brain.'
  if (count === 1) return 'Answered from 1 document in your Company Brain.'
  return `Answered from ${count} documents in your Company Brain.`
}
