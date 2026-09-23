import { cn } from '../../lib/cn.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * The subject of a page.
 *
 * Renamed in intent if not in export: this is no longer a "header" block
 * stamped identically on every route. The title is the page's *subject*, set
 * in the display serif, because on an Arc page the subject is content — it
 * names a workspace, a document, a capability, a decision — and content is
 * set in the serif while chrome is not. That one rule does most of the
 * hierarchy work in the app and costs nothing.
 *
 * Retained decisions from the previous version:
 *
 *  - No icon tile. It restated the nav item the user had just clicked, at
 *    four times the size. ARC_DESIGN_SYSTEM.md §6: no icons as decoration.
 *  - The description is capped at a reading measure. Several were running
 *    the full width of a 1440px viewport, roughly twice a comfortable line.
 *  - It sets `document.title`, so the tab and the <h1> cannot disagree.
 *
 * What changed: the rule underneath. A page subject now sits above a hairline
 * that runs the full field, which separates the page from its content without
 * putting either in a box — the move that replaces most of Arc's cards.
 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
  rule = true,
  children,
}) {
  useDocumentTitle(typeof title === 'string' ? title : undefined)

  return (
    <header
      className={cn(
        'flex flex-col gap-5',
        rule && 'border-b border-line pb-6',
        className,
      )}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="type-display-lg min-w-0 text-fg">{title}</h1>
            {meta}
          </div>
          {description && (
            <p className="measure mt-3 text-[15px] leading-relaxed text-fg-muted">
              {description}
            </p>
          )}
        </div>

        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 pt-1.5">{actions}</div>
        )}
      </div>

      {children}
    </header>
  )
}
