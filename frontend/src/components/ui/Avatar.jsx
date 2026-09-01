import { cn } from '../../lib/cn.js'
import { initials } from '../../lib/format.js'

const sizes = {
  xs: 'size-6 text-[10px]',
  sm: 'size-7 text-[11px]',
  md: 'size-8 text-xs',
  lg: 'size-10 text-sm',
}

export function Avatar({ name, size = 'md', className, ...props }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center rounded-full',
        'border border-zinc-700/60 bg-zinc-800 font-semibold text-zinc-300',
        sizes[size],
        className,
      )}
      {...props}
    >
      {initials(name)}
    </span>
  )
}