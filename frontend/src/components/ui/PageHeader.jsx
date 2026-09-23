import { cn } from '../../lib/cn.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * The page header every workspace and platform surface uses.
 *
 * Replaces 22 hand-rolled header blocks. ARC_DESIGN_SYSTEM.md §19 names
 * page headers specifically in its list of things that must not have
 * multiple visually different versions, and they had drifted: some carried
 * a 40px icon tile, some didn't; some right-aligned an action, some stacked
 * it; one page rendered its header twice with different spacing in its
 * loading and loaded branches.
 *
 * Two deliberate decisions:
 *
 *  - No icon tile. It restated the sidebar icon the user had just clicked,
 *    at four times the size, carrying no information the title didn't
 *    already carry. §6: "Do not use icons as decoration." Dropping it
 *    reclaims the vertical space and lets the title lead.
 *
 *  - The description is capped at ~72ch. Several were running the full
 *    width of a 1440px viewport, which is roughly 160 characters — about
 *    twice a comfortable measure.
 *
 * Hierarchy here is carried by size and weight, not colour: `--color-fg-muted`
 * is the floor that still clears AA on every Arc surface, so it cannot be
 * darkened further to signal "less important".
 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
  children,
}) {
  // Every page already tells PageHeader its name, so the document title
  // comes free and cannot drift from the <h1>. Previously every route in
  // the app was titled "Arc".
  useDocumentTitle(typeof title === 'string' ? title : undefined)

  return (
    <header className={cn('flex flex-col gap-4', className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">
              {title}
            </h1>
            {meta}
          </div>
          {description && (
            <p className="mt-1.5 max-w-[72ch] text-sm leading-relaxed text-fg-muted">
              {description}
            </p>
          )}
        </div>

        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>

      {children}
    </header>
  )
}
