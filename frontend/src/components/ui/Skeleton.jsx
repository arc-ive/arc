import { cn } from '../../lib/cn.js'

/**
 * A placeholder for a value that has not arrived.
 *
 * A `span`, not a `div`. Skeletons stand in for content, and content lives
 * inside headings, paragraphs and table cells — a block element in an
 * `<h1>` or a `<p>` is invalid HTML and React says so at runtime. As an
 * inline-block span it is valid wherever the real value would be.
 */
export function Skeleton({ className, ...props }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block animate-pulse rounded-md bg-surface-selected align-middle',
        'motion-reduce:animate-none',
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
        'rounded-lg border border-line p-5',
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