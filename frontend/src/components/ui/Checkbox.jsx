import { forwardRef, useId } from 'react'
import { cn } from '../../lib/cn.js'

/**
 * A checkbox with its label and hint wired up.
 *
 * The forms had been hand-rolling these. The label was associated via a
 * hardcoded `id`, which meant the same id shipped twice on any page
 * rendering both the create and the edit form — at which point clicking
 * one label focuses the other control. `useId` makes each instance unique.
 *
 * The hint slot exists because the checkbox that needed it most —
 * "approval required" — sits beside the risk select, and V2-ADR-011 turns
 * on those two being separate gates.
 */
export const Checkbox = forwardRef(function Checkbox(
  { label, hint, className, id, ...props },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const hintId = hint ? `${inputId}-hint` : undefined

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-start gap-2.5">
        <input
          ref={ref}
          id={inputId}
          type="checkbox"
          aria-describedby={hintId}
          className={cn(
            'mt-0.5 size-4 shrink-0 rounded border-line bg-surface accent-primary',
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
          )}
          {...props}
        />
        {label && (
          <label htmlFor={inputId} className="text-[13px] leading-snug text-fg">
            {label}
          </label>
        )}
      </div>
      {hint && (
        <p id={hintId} className="pl-[26px] text-xs leading-relaxed text-fg-muted">
          {hint}
        </p>
      )}
    </div>
  )
})
