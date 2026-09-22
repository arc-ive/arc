import { AlertTriangle, FileQuestion, ShieldX, WifiOff } from 'lucide-react'
import { cn } from '../../lib/cn.js'
import { Button } from './Button.jsx'
import { toApiError } from '../../api/errors.js'

export function ErrorState({
  title,
  message,
  onRetry,
  className,
  error,
}) {
  const apiError = error ? toApiError(error) : null

  let Icon = AlertTriangle
  if (apiError) {
    if (apiError.isForbidden) Icon = ShieldX
    if (apiError.isNetwork) Icon = WifiOff
    // Issue #225: a 404 is a distinct outcome, not a generic failure.
    if (apiError.isNotFound) Icon = FileQuestion
  }

  let defaultTitle = 'Something went wrong'
  if (apiError?.isForbidden) defaultTitle = 'Permission denied'
  if (apiError?.isNotFound) defaultTitle = 'Not found'
  const displayTitle = title ?? defaultTitle
  const displayMessage = message ?? apiError?.message ?? 'An unexpected error occurred.'

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 py-16 text-center',
        className,
      )}
    >
      <div className="mb-1 flex size-11 items-center justify-center rounded-xl border border-red-900/60 bg-red-950/30 text-red-400">
        <Icon className="size-5" />
      </div>
      <h3 className="text-sm font-semibold text-zinc-200">{displayTitle}</h3>
      <p className="max-w-sm text-[13px] leading-relaxed text-zinc-500">
        {displayMessage}
      </p>
      {onRetry && (
        <div className="mt-2">
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  )
}

export function ForbiddenState({ message, className }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 py-16 text-center',
        className,
      )}
    >
      <div className="mb-1 flex size-11 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-500">
        <ShieldX className="size-5" />
      </div>
      <h3 className="text-sm font-semibold text-zinc-200">
        Permission denied
      </h3>
      <p className="max-w-sm text-[13px] leading-relaxed text-zinc-500">
        {message ??
          'Your role does not grant access to this resource. Contact a platform administrator if you believe this is a mistake.'}
      </p>
    </div>
  )
}