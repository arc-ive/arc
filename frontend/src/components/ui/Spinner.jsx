import { cn } from '../../lib/cn.js'

export function Spinner({ className, ...props }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block size-4 animate-spin rounded-full border-2 border-current border-t-transparent',
        'motion-reduce:animate-none',
        className,
      )}
      {...props}
    />
  )
}