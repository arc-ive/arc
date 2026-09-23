import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'

/**
 * A block that is genuinely a discrete object.
 *
 * Substantially quieter than it was. A card used to be a rounded box with
 * a border, a panel fill and a shadow — and because it was Arc's default
 * container, every block on every page carried all three. When everything
 * is lifted, nothing is.
 *
 * It is now a hairline-ruled block on the page's own ground. The fill and
 * the shadow are opt-in via `raised`, for the small number of things that
 * really do float: dialogs, popovers, and the one panel on a page that has
 * to win. Most former call sites read better without either, which is why
 * the default changed rather than every call site.
 */
export const Card = forwardRef(function Card(
  { className, hover = false, raised = false, as: Component = 'div', ...props },
  ref,
) {
  return (
    <Component
      ref={ref}
      className={cn(
        'rounded-lg border border-line',
        raised ? 'bg-surface shadow-raised' : 'bg-transparent',
        hover &&
          'transition-colors duration-150 hover:border-line-strong hover:bg-surface-sunk/60',
        className,
      )}
      {...props}
    />
  )
})

export function CardHeader({ className, title, description, action, ...props }) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-4 border-b border-line px-5 py-4',
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        {title && <h2 className="type-label text-fg-muted">{title}</h2>}
        {description && (
          <p className="measure mt-1.5 text-[13.5px] leading-relaxed text-fg-muted">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  )
}

export function CardContent({ className, ...props }) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}

export function CardFooter({ className, ...props }) {
  return (
    <div
      className={cn(
        'border-t border-line px-5 py-3',
        className,
      )}
      {...props}
    />
  )
}