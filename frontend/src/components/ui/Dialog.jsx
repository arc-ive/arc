import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn.js'
import { IconButton } from './IconButton.jsx'

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  className,
}) {
  const dialogRef = useRef(null)
  const previouslyFocused = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    previouslyFocused.current = document.activeElement
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    document.body.style.overflow = 'hidden'
    window.setTimeout(() => dialogRef.current?.focus(), 0)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
      previouslyFocused.current?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  const sizes = {
    sm: 'max-w-sm',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8"
      role="presentation"
    >
      <div
        className="fixed inset-0 bg-black/70 backdrop-blur-[2px] animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'dialog-title' : undefined}
        aria-describedby={description ? 'dialog-description' : undefined}
        tabIndex={-1}
        className={cn(
          'relative z-10 my-auto w-full rounded-xl border border-line bg-raised shadow-overlay animate-scale-in',
          sizes[size],
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line/70 px-5 py-4">
          <div>
            {title && (
              <h2
                id="dialog-title"
                className="text-sm font-semibold text-fg"
              >
                {title}
              </h2>
            )}
            {description && (
              <p
                id="dialog-description"
                className="mt-0.5 text-[13px] text-fg-muted"
              >
                {description}
              </p>
            )}
          </div>
          <IconButton label="Close dialog" onClick={onClose} size="sm">
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-line/70 px-5 py-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}