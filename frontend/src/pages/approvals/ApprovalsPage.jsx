import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { useCapabilities } from '../../auth/capabilities.js'
import { useAuth } from '../../auth/useAuth.js'
import { listApprovals, decideApproval } from '../../api/endpoints/approvals.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage, toApiError } from '../../api/errors.js'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { ApprovalTimeline } from './ApprovalTimeline.jsx'
import { toolLabel, formatSummary } from '../../lib/approvals.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * The decision queue.
 *
 * Recomposed as a queue rather than a stack of cards. Every request was
 * previously the same bordered box at the same weight, so a high-risk
 * action waiting on you looked exactly like one that was settled last
 * week — on a page whose entire purpose is "what needs me".
 *
 * Now the page opens by saying how many are waiting for you specifically
 * (four-eyes excluded), what is waiting sits at full weight with its
 * decision in reach, and what is settled recedes to a rule and a date.
 *
 * Risk leads within a row, because risk is the reason a decision is being
 * asked for at all.
 */

const RISK_TONE = { high: 'danger', medium: 'warning', low: 'neutral' }

const FILTERS = [
  { value: null, label: 'All' },
  { value: 'pending', label: 'pending' },
  { value: 'approved', label: 'approved' },
  { value: 'rejected', label: 'rejected' },
]

function ApprovalRow({ approval, onDecide, viewerUserId, canDecide, pending }) {
  const isPending = approval.status === 'pending'

  // approvals.py:255 — the requester may NOT decide their own request.
  // Letting them click and collect a 403 is not a decision surface.
  const viewerIsRequester = approval.requester_user_id === viewerUserId
  const blockedByFourEyes = isPending && viewerIsRequester
  const decidable = isPending && canDecide && !viewerIsRequester

  return (
    <li className="border-b border-line py-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between lg:gap-10">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h2
              className={
                isPending
                  ? 'text-[16px] font-medium text-fg'
                  : 'text-[15px] text-fg-subtle'
              }
            >
              {toolLabel(approval.tool_name)}
            </h2>
            <Badge
              variant={RISK_TONE[approval.risk_level] ?? 'neutral'}
              size="sm"
            >
              {approval.risk_level} risk
            </Badge>
            {!isPending && (
              <Badge
                variant={approval.status === 'approved' ? 'success' : 'neutral'}
                size="sm"
                dot
              >
                {approval.status}
              </Badge>
            )}
          </div>

          {approval.input_summary && (
            <p className="measure mt-2.5 text-[13.5px] leading-relaxed text-fg-muted">
              {formatSummary(approval.input_summary)}
            </p>
          )}

          <div className="mt-4">
            <ApprovalTimeline
              approval={approval}
              viewerIsRequester={viewerIsRequester}
            />
          </div>
        </div>

        {/* Only a request that is actually waiting gets a decision column.
            A settled one is a record, and a record with two greyed-out
            buttons beside it reads as something you failed to do. */}
        {isPending && (
          <div className="flex shrink-0 flex-col items-stretch gap-2 lg:w-56">
            {decidable && (
              <>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={() => onDecide(approval.id, 'approve')}
                    disabled={pending}
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    className="flex-1"
                    onClick={() => onDecide(approval.id, 'reject')}
                    disabled={pending}
                  >
                    Reject
                  </Button>
                </div>
                <p className="text-[11.5px] leading-relaxed text-fg-muted">
                  Approving authorises this action. It does not run it.
                </p>
              </>
            )}

            {blockedByFourEyes && (
              <div className="border-l-2 border-line-strong pl-3">
                <p className="text-[12.5px] font-medium text-fg">
                  You requested this
                </p>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-fg-muted">
                  Someone else has to decide it. Arc does not let a person
                  approve their own request.
                </p>
              </div>
            )}

            {!canDecide && !viewerIsRequester && (
              <p className="text-[11.5px] leading-relaxed text-fg-muted">
                You don&apos;t have access to decide approvals.
              </p>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

/**
 * Decision failures a reader can act on.
 *
 * The most likely one is the four-eyes rule (approvals.py:255), which the
 * row already prevents — but a stale list can still produce it.
 */
function decisionErrorMessage(error) {
  const api = toApiError(error)
  if (api.isForbidden) {
    return "That decision wasn't allowed. A request can't be decided by the person who made it."
  }
  if (api.isNetwork) return "Can't reach Arc. Check your connection and try again."
  return 'The decision could not be recorded. Try again.'
}

export function ApprovalsPage() {
  useDocumentTitle('Approvals')
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { can } = useCapabilities()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState(null)

  const canRead = can('approval:read')
  const canDecide = can('approval:decide')

  const { data: approvals, isPending, isError, error } = useQuery({
    queryKey: queryKeys.approvalsList(tenantId, statusFilter),
    queryFn: () => listApprovals(tenantId, { status: statusFilter }),
    enabled: Boolean(tenantId) && canRead,
  })

  const decideMutation = useMutation({
    mutationFn: ({ approvalId, decision }) =>
      decideApproval(tenantId, approvalId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.approvals(tenantId) })
    },
  })

  const handleDecide = (approvalId, decision) => {
    decideMutation.mutate({ approvalId, decision })
  }

  if (!canRead) {
    return (
      <div className="flex flex-col">
        <h1 className="type-display-lg text-fg">Approvals</h1>
        <p className="measure mt-4 type-prose text-fg-subtle">
          You don&apos;t have access to approvals in this workspace.
        </p>
      </div>
    )
  }

  const rows = approvals ?? []
  const waiting = rows.filter((a) => a.status === 'pending')
  // What is waiting on the reader is not the same as what is waiting:
  // their own requests are someone else's to decide.
  const waitingOnYou = waiting.filter(
    (a) => canDecide && a.requester_user_id !== principal?.sub,
  )

  return (
    <div className="flex flex-col">
      <header>
        <h1 className="type-display-lg text-fg">Approvals</h1>
        {!isPending && !isError && (
          <p className="measure mt-2 text-[14px] text-fg-muted">
            {waiting.length === 0
              ? 'Nothing is waiting on a decision.'
              : waitingOnYou.length === waiting.length
                ? `${waiting.length} waiting on you.`
                : `${waiting.length} waiting · ${waitingOnYou.length} you can decide.`}
          </p>
        )}
      </header>

      <div className="mt-8 flex flex-wrap gap-1 border-b border-line pb-3">
        {FILTERS.map((f) => (
          <button
            key={f.value ?? 'all'}
            onClick={() => setStatusFilter(f.value)}
            aria-pressed={statusFilter === f.value}
            className={`rounded px-2.5 py-1 text-[13px] transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 ${
              statusFilter === f.value
                ? 'text-fg underline decoration-fg-muted decoration-1 underline-offset-[6px]'
                : 'text-fg-muted hover:text-fg-subtle'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isPending && (
        <div className="mt-8 flex flex-col gap-7">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="flex flex-col gap-2.5">
              <Skeleton className="h-5 w-56" />
              <Skeleton className="h-4 w-full max-w-lg" />
              <Skeleton className="h-3 w-40" />
            </div>
          ))}
        </div>
      )}

      {isError && (
        <div className="mt-8">
          <ErrorState message={errorMessage(error)} />
        </div>
      )}

      {decideMutation.isError && (
        <p
          role="alert"
          className="measure mt-6 border-l-2 border-danger pl-3 text-[13.5px] leading-relaxed text-danger"
        >
          {decisionErrorMessage(decideMutation.error)}
        </p>
      )}

      {!isPending && !isError && rows.length === 0 && (
        <p className="measure mt-8 type-prose text-fg-subtle">
          {statusFilter
            ? `No ${statusFilter} approvals`
            : 'No approval requests have been raised in this workspace yet. Arc asks for one when a skill reaches a tool classified high risk.'}
        </p>
      )}

      {!isPending && !isError && rows.length > 0 && (
        <ul className="stagger mt-2 border-t border-line">
          {[...rows]
            .sort(
              (a, b) =>
                Number(b.status === 'pending') - Number(a.status === 'pending'),
            )
            .map((approval) => (
              <ApprovalRow
                key={approval.id}
                approval={approval}
                onDecide={handleDecide}
                viewerUserId={principal?.sub}
                canDecide={canDecide}
                pending={decideMutation.isPending}
              />
            ))}
        </ul>
      )}
    </div>
  )
}
