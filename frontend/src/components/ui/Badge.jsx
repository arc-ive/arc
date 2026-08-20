import { cn } from '../../lib/cn.js'

const variants = {
  neutral: 'bg-zinc-800/80 text-zinc-300 border-zinc-700/60',
  indigo: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30',
  cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
  green: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  red: 'bg-red-500/10 text-red-300 border-red-500/30',
}

const sizes = {
  sm: 'px-1.5 py-px text-[11px]',
  md: 'px-2 py-0.5 text-xs',
}

export function Badge({
  variant = 'neutral',
  size = 'md',
  dot = false,
  className,
  children,
  ...props
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium tracking-wide',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {dot && (
        <span
          aria-hidden
          className={cn(
            'size-1.5 rounded-full',
            variant === 'green' && 'bg-emerald-400',
            variant === 'cyan' && 'bg-cyan-400',
            variant === 'indigo' && 'bg-indigo-400',
            variant === 'amber' && 'bg-amber-400',
            variant === 'red' && 'bg-red-400',
            variant === 'neutral' && 'bg-zinc-400',
          )}
        />
      )}
      {children}
    </span>
  )
}