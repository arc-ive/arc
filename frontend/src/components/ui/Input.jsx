import { forwardRef, useId } from 'react'
import { cn } from '../../lib/cn.js'

export const Input = forwardRef(function Input(
  {
    label,
    hint,
    error,
    required,
    className,
    inputClassName,
    id,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label
          htmlFor={inputId}
          className="text-[13px] font-medium text-zinc-300"
        >
          {label}
          {required && <span className="ml-0.5 text-fg-muted">*</span>}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        className={cn(
          'h-9 w-full rounded-lg border bg-zinc-900/70 px-3 text-sm text-zinc-100',
          'placeholder:text-fg-muted transition-colors duration-150',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
          error
            ? 'border-red-800 focus-visible:outline-red-500'
            : 'border-zinc-800 hover:border-zinc-700',
          inputClassName,
        )}
        {...props}
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      {hint && !error && <p className="text-xs text-fg-muted">{hint}</p>}
    </div>
  )
})