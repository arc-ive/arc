import { cn } from '../../lib/cn.js'

export function Skeleton({ className, ...props }) {
  return (
    <div
      aria-hidden
      className={cn(
        'animate-pulse rounded-md bg-surface-selected motion-reduce:animate-none',
        className,
      )}
      {...props}
    />
  )
}

export function SkeletonText({ lines = 3, className, lineClassName }) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton
          key={i}
          className={cn('h-3.5', i === lines - 1 ? 'w-2/3' : 'w-full', lineClassName)}
        />
      ))}
    </div>
  )
}

export function SkeletonCard({ className }) {
  return (
    <div
      className={cn(
        'rounded-xl border border-line/80 bg-panel p-5 shadow-card',
        className,
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-16" />
      </div>
      <SkeletonText lines={2} className="mt-4" />
    </div>
  )
}