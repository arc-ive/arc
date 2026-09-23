import { Link } from 'react-router-dom'
import { Badge } from '../../components/ui/Badge.jsx'
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
        'group flex flex-col gap-2 rounded-xl border border-line bg-surface p-4',
        'transition-colors duration-150 hover:border-line-strong hover:bg-surface-raised',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 flex-1 text-[15px] font-semibold leading-snug text-fg">
          {title}
        </h3>
        <Badge variant="neutral" size="sm">
          {sourceLabels[document.source] ?? document.source}
        </Badge>
      </div>

      {origin && (
        <p className="truncate text-xs text-fg-muted">
          <span className="text-fg-muted/80">Source</span> · {origin}
        </p>
      )}

      {passage && (
        <p className="line-clamp-2 text-[13px] leading-relaxed text-fg-muted">
          {splitOnQuery(passage, query).map((seg, i) =>
            seg.match ? (
              <mark
                key={i}
                className="rounded-sm bg-primary/20 px-0.5 text-fg [font-weight:500]"
              >
                {seg.text}
              </mark>
            ) : (
              <span key={i}>{seg.text}</span>
            ),
          )}
        </p>
      )}

      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
        {passageCount > 1 && (
          <span>
            {passageCount} matching passages
          </span>
        )}
        {updatedAt && <span>Updated {relativeTime(updatedAt)}</span>}
        {document.version != null && <span>Version {document.version}</span>}
      </div>
    </Link>
  )
}
