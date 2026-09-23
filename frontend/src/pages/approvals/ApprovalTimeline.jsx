import { Check, Clock, X, CircleDashed, AlertTriangle } from 'lucide-react'
import { cn } from '../../lib/cn.js'
import { relativeTime } from '../../lib/format.js'

/**
 * An approval as a decision timeline rather than a status word.
 *
 * ARC_UX_SPEC.md §4 asks an approval surface to show what action is
 * requested, who requested it, why approval is required, what happens if
 * approved, and the current status — and warns: "Never imply that approval
 * itself grants authorization." V2-ADR-012 is titled exactly that.
 *
 * The previous page showed a status badge and two buttons. A reader could
 * see THAT something was approved but not what it meant, and the one thing
 * the ADR insists on — that approving is not running — was nowhere on the
 * screen.
 *
 * The third step is the important one. It is deliberately never "done" from
 * the approver's side: approving authorises the action, and the requester
 * still has to run it. `consumed_at` is what says it ran.
 */

const TERMINAL = new Set(['rejected', 'expired'])

export function ApprovalTimeline({ approval, viewerIsRequester }) {
  const { status, created_at: createdAt, decided_at: decidedAt } = approval
  const decidedBy = approval.decided_by_user_id
  const consumedAt = approval.consumed_at

  const steps = [
    {
      key: 'requested',
      state: 'done',
      label: 'Requested',
      detail: `by ${viewerIsRequester ? 'you' : shortUser(approval.requester_user_id)}`,
      at: createdAt,
    },
    {
      key: 'decision',
      state: decisionState(status),
      label: decisionLabel(status),
      detail: decidedBy ? `by ${shortUser(decidedBy)}` : pendingDetail(approval),
      at: decidedAt,
    },
    {
      key: 'run',
      state: runState(status, consumedAt),
      label: consumedAt ? 'Run' : 'Not run yet',
      // The ADR-012 point, stated where the reader is looking for it.
      detail: consumedAt
        ? 'the requester ran the action'
        : TERMINAL.has(status)
          ? 'the action will not run'
          : 'approving authorises the action — the requester still runs it',
      at: consumedAt,
    },
  ]

  return (
    <ol className="flex flex-col">
      {steps.map((step, index) => (
        <li key={step.key} className="flex gap-3">
          <div className="flex flex-col items-center">
            <StepMark state={step.state} status={status} />
            {index < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  'w-px flex-1',
                  step.state === 'done' ? 'bg-line-strong' : 'bg-line',
                )}
              />
            )}
          </div>
          <div className={cn('min-w-0 pb-4', index === steps.length - 1 && 'pb-0')}>
            <p
              className={cn(
                'text-[13px] font-medium leading-tight',
                step.state === 'pending' ? 'text-fg' : 'text-fg',
                step.state === 'future' && 'text-fg-muted',
              )}
            >
              {step.label}
              {step.at && (
                <span className="ml-2 font-normal text-fg-muted">
                  {relativeTime(step.at)}
                </span>
              )}
            </p>
            {step.detail && (
              <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">
                {step.detail}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

function StepMark({ state, status }) {
  const base = 'flex size-5 shrink-0 items-center justify-center rounded-full border'

  if (state === 'done') {
    const rejected = status === 'rejected'
    const expired = status === 'expired'
    const Icon = rejected ? X : expired ? AlertTriangle : Check
    return (
      <span
        aria-hidden
        className={cn(
          base,
          rejected || expired
            ? 'border-danger/40 bg-danger/10 text-danger'
            : 'border-success/40 bg-success/10 text-success',
        )}
      >
        <Icon className="size-3" />
      </span>
    )
  }

  if (state === 'pending') {
    return (
      <span aria-hidden className={cn(base, 'border-warning/40 bg-warning/10 text-warning')}>
        <Clock className="size-3" />
      </span>
    )
  }

  return (
    <span aria-hidden className={cn(base, 'border-line bg-surface text-fg-muted')}>
      <CircleDashed className="size-3" />
    </span>
  )
}

function decisionState(status) {
  if (status === 'pending') return 'pending'
  return 'done'
}

function decisionLabel(status) {
  switch (status) {
    case 'pending':
      return 'Awaiting decision'
    case 'rejected':
      return 'Rejected'
    case 'expired':
      return 'Expired without a decision'
    default:
      return 'Approved'
  }
}

function runState(status, consumedAt) {
  if (consumedAt) return 'done'
  if (TERMINAL.has(status)) return 'done'
  return 'future'
}

/** Pending detail carries the expiry, which is the only clock that matters. */
function pendingDetail(approval) {
  if (approval.status !== 'pending' || !approval.expires_at) return null
  const remaining = new Date(approval.expires_at).getTime() - Date.now()
  if (remaining <= 0) return 'the window has closed'
  const hours = Math.round(remaining / 3_600_000)
  return hours <= 1 ? 'expires within the hour' : `expires in about ${hours} hours`
}

/**
 * User ids are long and tenant-prefixed. The tail is what distinguishes
 * one person from another.
 */
function shortUser(userId) {
  if (!userId) return 'someone'
  const parts = String(userId).split('-')
  return parts.length > 2 ? parts.slice(-2).join(' ') : userId
}
