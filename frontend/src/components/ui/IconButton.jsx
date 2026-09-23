import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'

const variants = {
  ghost:
    'text-fg-muted hover:text-fg hover:bg-surface-overlay active:bg-surface-selected',
  solid:
    'text-fg border border-line bg-surface-raised hover:bg-surface-selected hover:text-fg',
  danger: 'text-fg-muted hover:text-red-400 hover:bg-red-950/40',
}

const sizes = {
  sm: 'size-7',
  md: 'size-8',
  lg: 'size-9',
}

export const IconButton = forwardRef(function IconButton(
  { variant = 'ghost', size = 'md', label, className, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-md',
        'transition-colors duration-150',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
})