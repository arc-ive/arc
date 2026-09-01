import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'

export const Card = forwardRef(function Card(
  { className, hover = false, as: Component = 'div', ...props },
  ref,
) {
  return (
    <Component
      ref={ref}
      className={cn(
        'rounded-xl border border-zinc-800/80 bg-panel shadow-card',
        hover &&
          'transition-colors duration-150 hover:border-zinc-700 hover:bg-elevated',
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
        'flex items-start justify-between gap-4 border-b border-zinc-800/70 px-5 py-4',
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        {title && (
          <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
        )}
        {description && (
          <p className="mt-0.5 text-[13px] text-zinc-500">{description}</p>
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
        'border-t border-zinc-800/70 px-5 py-3',
        className,
      )}
      {...props}
    />
  )
}