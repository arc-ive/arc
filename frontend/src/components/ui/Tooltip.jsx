import { useId } from 'react'
import { cn } from '../../lib/cn.js'

export function Tooltip({ label, children, className, side = 'top' }) {
  const id = useId()
  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
  }

  return (
    <span className={cn('group/tooltip relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        id={id}
        className={cn(
          'pointer-events-none absolute z-40 whitespace-nowrap rounded-md border border-line bg-surface-overlay px-2 py-1 text-xs text-fg-subtle shadow-overlay',
          'opacity-0 transition-opacity duration-150 group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100',
          'motion-reduce:transition-none',
          positions[side],
        )}
      >
        {label}
      </span>
    </span>
  )
}