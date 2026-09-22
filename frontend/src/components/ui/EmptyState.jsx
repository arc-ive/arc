import { cn } from '../../lib/cn.js'

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact = false,
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 py-8' : 'gap-3 py-16',
        className,
      )}
    >
      {Icon && (
        <div className="mb-1 flex size-11 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-fg-muted">
          <Icon className="size-5" />
        </div>
      )}
      <h3 className="text-sm font-semibold text-zinc-200">{title}</h3>
      {description && (
        <p className="max-w-sm text-[13px] leading-relaxed text-fg-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}