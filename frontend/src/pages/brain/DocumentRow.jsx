import { Link } from 'react-router-dom'
import { sourceLabels } from '../../lib/sources.js'
import {
  documentTitle,
  documentOrigin,
  originRepeatsTitle,
  splitOnQuery,
} from '../../lib/knowledge.js'
import { relativeTime } from '../../lib/format.js'
import { cn } from '../../lib/cn.js'

/**
 * One knowledge document, in browse or in search results.
 *
 * Replaces two diverging card layouts with one row, because a document is
 * the same object whether you found it by browsing or by searching — only
 * the reason you are looking at it differs.
 *
 * Three changes of substance:
 *
 *  - A REAL LINK. The previous cards were `div role="link"` with an
 *    Enter-only key handler: no href, so no middle-click, no open-in-new-
 *    tab, no context menu, and nothing for a screen reader to announce as
 *    a destination.
 *
 *  - TITLE AND ORIGIN ARE DIFFERENT THINGS. `provenance` was rendered as
 *    the headline, which reads correctly only while the seed data holds
 *    human strings. Title is derived; provenance appears below as what it
 *    is — where this came from.
 *
 *  - THE MATCHING PASSAGE REPLACES THE SCORE. `Similarity: 87.3%` was a
 *    retrieval internal (ARC_UX_SPEC.md §2) that currently renders "0.0%"
 *    for every result under the local embedding provider. Showing the text
 *    that matched, with the query terms marked, answers "why is this
 *    relevant?" in a way a reader can actually judge.
 *
 * Hierarchy is carried by size and weight rather than colour: the muted
 * token is the contrast floor, so it cannot be darkened to signal "less
 * important" (see the token layer in PR-0).
 */
export function DocumentRow({ document, to, query = '', passageCount = 0 }) {
  const title = documentTitle(document)
  const origin = originRepeatsTitle(document) ? null : documentOrigin(document)
  const passage = document.passage ?? ''
  const updatedAt = document.updated_at

  return (
    <Link
      to={to}
      className={cn(
        'group relative grid grid-cols-1 gap-x-8 gap-y-2 border-b border-line py-6',
        'transition-colors duration-150 hover:bg-surface-sunk/60',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
        'md:grid-cols-[minmax(0,1fr)_14rem]',
      )}
    >
      <div className="min-w-0">
        {/* The document title is content, so it is set in the display
            serif. Everything around it is chrome and stays in the
            grotesque — which is the whole hierarchy, for free. */}
        <h2 className="type-display text-[1.375rem] leading-snug text-fg">
          {title}
        </h2>

        {passage && (
          <p className="measure mt-2 line-clamp-2 text-[14px] leading-relaxed text-fg-subtle">
            {splitOnQuery(passage, query).map((seg, i) =>
              seg.match ? (
                <mark
                  key={i}
                  className="bg-accent/12 px-0.5 font-medium text-fg"
                >
                  {seg.text}
                </mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )}
          </p>
        )}

        {origin && (
          <p className="mt-2 truncate type-data text-fg-muted">{origin}</p>
        )}
      </div>

      {/* Metadata is a margin column, not a row of chips under the title.
          It aligns down the index so a reader can scan one attribute
          without reading every entry. */}
      <dl className="flex flex-row flex-wrap items-start gap-x-6 gap-y-1 md:flex-col md:gap-y-2 md:pt-2">
        <div className="flex items-baseline gap-2 md:flex-col md:gap-0.5">
          <dt className="type-label text-fg-muted">Kind</dt>
          <dd className="text-[13px] text-fg-subtle">
            {sourceLabels[document.source] ?? document.source}
          </dd>
        </div>
        {updatedAt && (
          <div className="flex items-baseline gap-2 md:flex-col md:gap-0.5">
            <dt className="type-label text-fg-muted">Updated</dt>
            <dd className="text-[13px] text-fg-subtle">{relativeTime(updatedAt)}</dd>
          </div>
        )}
        {document.version != null && (
          <div className="flex items-baseline gap-2 md:flex-col md:gap-0.5">
            <dt className="type-label text-fg-muted">Version</dt>
            <dd className="type-data text-fg-subtle">{document.version}</dd>
          </div>
        )}
        {passageCount > 1 && (
          <div className="flex items-baseline gap-2 md:flex-col md:gap-0.5">
            <dt className="type-label text-fg-muted">Matches</dt>
            <dd className="text-[13px] text-fg-subtle">{passageCount} passages</dd>
          </div>
        )}
      </dl>
    </Link>
  )
}
