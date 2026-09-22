import { AlertCircle } from 'lucide-react'
import { cn } from '../../lib/cn.js'

/**
 * An error attached to a specific action, not to the page.
 *
 * Arc has two error semantics and only had a component for one of them:
 *
 *   ErrorState  — a query failed, so there is nothing to show. Full-width,
 *                 centred, icon, retry. Owns the whole region.
 *   InlineError — a specific action failed: a mutation was rejected, a
 *                 form did not validate. The surrounding content is still
 *                 valid and must stay on screen.
 *
 * Twelve call sites hand-rolled the second shape, in three different
 * paddings (`px-3 py-2.5`, `px-3.5 py-3`, and one with `mb-4` baked in),
 * which is the duplication ARC_DESIGN_SYSTEM.md §19 warns about. Routing
 * them through `ErrorState` instead would have been worse, not better — a
 * centred full-region failure state is the wrong shape for "this one save
 * did not go through".
 *
 * `role="alert"` matters here: a mutation failure happens after the user
 * acts, so it has to be announced. Without it the message appears silently
 * for anyone not looking at that part of the screen.
 */
export function InlineError({ children, className, icon = true }) {
  if (!children) return null

  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10',
        'px-3.5 py-3 text-[13px] leading-relaxed text-danger',
        className,
      )}
    >
      {icon && <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <span className="min-w-0">{children}</span>
    </div>
  )
}
