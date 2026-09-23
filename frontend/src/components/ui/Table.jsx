import { cn } from '../../lib/cn.js'

export function Table({ className, children, ...props }) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn('w-full border-collapse text-sm', className)}
        {...props}
      >
        {children}
      </table>
    </div>
  )
}

export function TableHeader({ className, children, ...props }) {
  return (
    <thead className={className} {...props}>
      {children}
    </thead>
  )
}

export function TableBody({ className, children, ...props }) {
  return (
    <tbody className={cn('divide-y divide-line/60', className)} {...props}>
      {children}
    </tbody>
  )
}

export function TableRow({ className, clickable = false, ...props }) {
  return (
    <tr
      className={cn(
        clickable &&
          'cursor-pointer transition-colors duration-150 hover:bg-surface-raised',
        className,
      )}
      {...props}
    />
  )
}

export function TableHead({ className, children, ...props }) {
  return (
    <th
      className={cn(
        'border-b border-line/80 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-fg-muted whitespace-nowrap',
        className,
      )}
      {...props}
    >
      {children}
    </th>
  )
}

export function TableCell({ className, children, ...props }) {
  return (
    <td
      className={cn('px-4 py-3 align-middle text-fg-subtle', className)}
      {...props}
    >
      {children}
    </td>
  )
}