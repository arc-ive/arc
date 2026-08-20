import { forwardRef } from 'react'
import { cn } from '../../lib/cn.js'
import { Spinner } from './Spinner.jsx'

const variants = {
  primary:
    'bg-zinc-50 text-zinc-950 hover:bg-white active:bg-zinc-200 border border-transparent',
  secondary:
    'bg-transparent text-zinc-200 border border-zinc-800 hover:bg-zinc-900 hover:border-zinc-700',
  ghost: 'bg-transparent text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900',
  danger:
    'bg-transparent text-red-400 border border-zinc-800 hover:bg-red-950/40 hover:border-red-900',
  accent:
    'bg-indigo-500 text-white hover:bg-indigo-400 active:bg-indigo-600 border border-transparent',
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