import { forwardRef, useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/cn.js'

export const Select = forwardRef(function Select(
  { label, hint, error, required, className, id, children, ...props },
  ref,
) {
  const generatedId = useId()
  const selectId = id ?? generatedId

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label
          htmlFor={selectId}
          className="text-[13px] font-medium text-fg-subtle"
        >
          {label}
          {required && <span className="ml-0.5 text-fg-muted">*</span>}
        </label>
      )}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          className={cn(
            'h-9 w-full appearance-none rounded-lg border bg-surface-raised pl-3 pr-9 text-sm text-fg',
            'transition-colors duration-150',
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
            error
              ? 'border-red-800 focus-visible:outline-red-500'
              : 'border-line hover:border-line-strong',
          )}
          {...props}
        >
          {children}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-fg-muted"
          aria-hidden
        />
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      {hint && !error && <p className="text-xs text-fg-muted">{hint}</p>}
    </div>
  )
})