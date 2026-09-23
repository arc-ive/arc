import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
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
export function DocumentRow({ document, to, query = '', passageCount = 0, index }) {
  const title = documentTitle(document)
  const origin = originRepeatsTitle(document) ? null : documentOrigin(document)
  const passage = document.passage ?? ''
  const updatedAt = document.updated_at

  return (
    <Link
      to={to}
      className={cn(
        'group relative flex items-baseline gap-5 border-b border-line py-5 sm:gap-7',
        'transition-colors duration-200 hover:bg-surface-sunk/70',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
      )}
    >
      {/* The index number is the editorial device that makes this a
          catalogue rather than a list of links — and it is honest, because
          the order is the ranking the backend returned. */}
      {index != null && (
        <span className="type-data shrink-0 pt-1 text-fg-muted tabular-nums">
          {String(index + 1).padStart(2, '0')}
        </span>
      )}

      <span className="min-w-0 flex-1">
        <span className="type-display block text-[1.375rem] leading-snug text-fg">
          {title}
        </span>

        {/* Kind and date sit on one quiet line under the title — the
            metadata column they used to occupy competed with the titles
            down the page. */}
        <span className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-fg-muted">
          <span>{sourceLabels[document.source] ?? document.source}</span>
          {updatedAt && (
            <>
              <span aria-hidden>·</span>
              <span>Updated {relativeTime(updatedAt)}</span>
            </>
          )}
          {document.version != null && (
            <>
              <span aria-hidden>·</span>
              <span className="type-data">v{document.version}</span>
            </>
          )}
          {passageCount > 1 && (
            <>
              <span aria-hidden>·</span>
              <span>{passageCount} matching passages</span>
            </>
          )}
        </span>

        {passage && (
          <span className="measure mt-2 block line-clamp-2 text-[14px] leading-relaxed text-fg-subtle">
            {splitOnQuery(passage, query).map((seg, i) =>
              seg.match ? (
                <mark key={i} className="bg-accent/12 px-0.5 font-medium text-fg">
                  {seg.text}
                </mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )}
          </span>
        )}

        {origin && (
          <span className="type-data mt-1.5 block truncate text-fg-muted">
            {origin}
          </span>
        )}
      </span>

      {/* Revealed on approach rather than drawn on every row. Twelve
          static arrows down a page is twelve pieces of furniture; one that
          appears where the pointer is, is a response. */}
      <ArrowUpRight
        aria-hidden
        className={cn(
          'mt-1 size-4 shrink-0 text-fg-muted',
          'translate-x-[-4px] opacity-0 transition-all duration-200',
          'group-hover:translate-x-0 group-hover:opacity-100 group-hover:text-fg',
          'group-focus-visible:translate-x-0 group-focus-visible:opacity-100',
        )}
      />
    </Link>
  )
}
