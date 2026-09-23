/**
 * Presentation helpers for Company Brain.
 *
 * Knowledge documents have no `title` field — the schema is id, tenant_id,
 * source, provenance, version, status, content, external_id, created_at,
 * updated_at. The UI had been rendering `provenance` as the headline, which
 * looks right only because the seed data happens to put human strings
 * there. Connector ingestion writes
 *
 *     provenance = f"connector:{provider}:{source_id}"
 *
 * (connector_sync.py:171), so the first real sync would turn every card
 * title into `connector:github:arc-ive/arc/docs/README.md`. Latent: no demo
 * with seeded data shows it.
 *
 * Per decision D3 the frontend derives an honest label rather than waiting
 * on a backend `title` field, and keeps provenance visible as what it
 * actually is — where the document came from.
 */

/** Provenance strings that are machine identity, not a human title. */
const MACHINE_PROVENANCE = /^(connector|webhook|import|sync):/i

/**
 * A human label for a document.
 *
 * Prefers provenance when a person wrote it; falls back to de-slugging the
 * document id when provenance is a connector path or missing. Never returns
 * an empty string — an untitled document still needs something to click.
 */
export function documentTitle({ provenance, document_id: chunkDocId, id } = {}) {
  const documentId = id ?? chunkDocId
  const raw = provenance?.trim() ?? ''

  // A person wrote it — use it as-is.
  if (raw && !MACHINE_PROVENANCE.test(raw)) return raw

  // A connector wrote it. The path's last segment is the closest thing to
  // a human name that exists: "connector:github:arc-ive/arc/docs/README.md"
  // yields "Readme", which beats the generated document id.
  if (raw) {
    const label = deslug(stripExtension(raw))
    if (label !== 'Untitled document') return label
  }

  if (!documentId) return 'Untitled document'
  return deslug(documentId)
}

/** Drop a trailing file extension so "README.md" reads as "Readme". */
function stripExtension(value) {
  return String(value).replace(/\.[a-z0-9]{1,6}$/i, '')
}

/**
 * Where a document came from, as a person would say it.
 *
 * Returns null when provenance adds nothing beyond the title — repeating
 * the headline underneath itself is noise.
 */
export function documentOrigin({ provenance } = {}) {
  if (!provenance) return null
  const match = provenance.match(/^connector:([^:]+):(.+)$/i)
  if (match) {
    const [, provider, ref] = match
    return `${capitalise(provider)} · ${ref}`
  }
  if (MACHINE_PROVENANCE.test(provenance)) return provenance
  return provenance
}

/** True when the origin line would just repeat the title. */
export function originRepeatsTitle(doc) {
  const origin = documentOrigin(doc)
  return Boolean(origin) && origin === documentTitle(doc)
}

/**
 * Collapse chunk-level search hits into one entry per document.
 *
 * The search endpoint returns CHUNKS, so a document that matches in three
 * places came back as three cards — the same title three times, competing
 * with each other. Users search for documents, not for chunks.
 *
 * Order is preserved from the backend's ranking; the first hit for a
 * document decides its position. Matching passages are kept so the result
 * can show WHY it matched instead of asserting a score.
 */
export function groupChunksByDocument(chunks = []) {
  const byDocument = new Map()

  for (const chunk of chunks) {
    const key = chunk.document_id
    const existing = byDocument.get(key)
    if (existing) {
      existing.passages.push(chunk.content)
      continue
    }
    byDocument.set(key, {
      documentId: key,
      source: chunk.source,
      provenance: chunk.provenance,
      version: chunk.document_version,
      passages: [chunk.content],
    })
  }

  return [...byDocument.values()]
}

/**
 * Split text around the query terms so a result can show what matched.
 *
 * This is the honest answer to "why is this relevant?". The page used to
 * answer it with `Similarity: 87.3%` — a retrieval internal that
 * ARC_UX_SPEC.md §2 prohibits, and which currently reads "0.0%" on every
 * result because the local embedding provider is deterministic. A reader
 * can judge a passage; nobody can act on a percentage.
 *
 * Returns segments of `{ text, match }` for the caller to render.
 */
export function splitOnQuery(text = '', query = '') {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter((t) => t.length > 2)

  if (terms.length === 0 || !text) return [{ text, match: false }]

  // `split` on a capturing group returns the text and the captures
  // alternately, so a part is a match exactly when it is one of the terms.
  //
  // This deliberately does NOT re-test the part against `pattern`. That
  // test was redundant — `terms` is the authority — and it was wrong: a
  // /g regex carries `lastIndex` between `.test()` calls, so when two
  // matched terms landed next to each other in the split output the
  // second was tested from a stale offset and came back false. "escalate
  // incident" over "escalateincident now" highlighted "escalate" and left
  // "incident" plain.
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'gi')
  return text
    .split(pattern)
    .filter((part) => part !== '')
    .map((part) => ({ text: part, match: terms.includes(part.toLowerCase()) }))
}

/**
 * The passage most worth showing for a result.
 *
 * Prefers a passage that actually contains a query term over simply the
 * first chunk the backend returned — showing a non-matching opening
 * paragraph makes a good result look irrelevant.
 */
export function bestPassage(passages = [], query = '') {
  if (passages.length === 0) return ''
  const terms = query.toLowerCase().split(/\s+/).filter((t) => t.length > 2)
  if (terms.length === 0) return passages[0]
  return (
    passages.find((p) => terms.some((t) => p.toLowerCase().includes(t))) ?? passages[0]
  )
}

function deslug(value) {
  const tail = String(value).split(/[/:]/).pop() ?? String(value)
  const words = tail.replace(/[-_]+/g, ' ').trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Untitled document'
}

function capitalise(value) {
  return String(value).charAt(0).toUpperCase() + String(value).slice(1)
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
