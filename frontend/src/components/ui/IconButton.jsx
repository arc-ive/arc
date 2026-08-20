import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'

const variants = {
  ghost:
    'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 active:bg-zinc-800/80',
  solid:
    'text-zinc-200 border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-800 hover:text-zinc-100',
  danger: 'text-zinc-400 hover:text-red-400 hover:bg-red-950/40',
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