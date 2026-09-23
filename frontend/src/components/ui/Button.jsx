import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'
import { Spinner } from './Spinner.jsx'

const variants = {
  primary:
    'bg-action text-on-action hover:bg-white active:bg-action/90 border border-transparent',
  secondary:
    'bg-transparent text-fg border border-line hover:bg-surface-overlay hover:border-line-strong',
  ghost: 'bg-transparent text-fg-muted hover:text-fg hover:bg-surface-overlay',
  // Matches how Badge renders danger. The variant had been using red-400
  // while the system's danger token is red-300 — lighter, and chosen for
  // contrast on Arc's surfaces, so this reads better as well as matching.
  danger:
    'bg-transparent text-danger border border-line hover:bg-danger/10 hover:border-danger/40',
  accent:
    'bg-primary text-on-action hover:bg-primary/90 active:bg-primary/80 border border-transparent',
}

const sizes = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-10 px-5 text-sm gap-2',
}

export const Button = forwardRef(function Button(
  {
    variant = 'primary',
    size = 'md',
    isLoading = false,
    loadingText,
    disabled,
    className,
    children,
    type = 'button',
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || isLoading}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium',
        'transition-colors duration-150 select-none whitespace-nowrap',
        'disabled:opacity-50 disabled:pointer-events-none',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {isLoading && <Spinner className="size-3.5" />}
      {isLoading && loadingText ? loadingText : children}
    </button>
  )
})