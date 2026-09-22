import { forwardRef, useId } from 'react'
import { cn } from '../../lib/cn.js'

export const Textarea = forwardRef(function Textarea(
  { label, hint, error, required, className, textareaClassName, id, rows = 6, ...props },
  ref,
) {
  const generatedId = useId()
  const textareaId = id ?? generatedId

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label
          htmlFor={textareaId}
          className="text-[13px] font-medium text-zinc-300"
        >
          {label}
          {required && <span className="ml-0.5 text-fg-muted">*</span>}
        </label>
      )}
      <textarea
        ref={ref}
        id={textareaId}
        rows={rows}
        className={cn(
          'w-full resize-y rounded-lg border bg-zinc-900/70 px-3 py-2 text-sm leading-relaxed text-zinc-100',
          'placeholder:text-fg-muted transition-colors duration-150',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
          error
            ? 'border-red-800 focus-visible:outline-red-500'
            : 'border-zinc-800 hover:border-zinc-700',
          textareaClassName,
        )}
        {...props}
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      {hint && !error && <p className="text-xs text-fg-muted">{hint}</p>}
    </div>
  )
})