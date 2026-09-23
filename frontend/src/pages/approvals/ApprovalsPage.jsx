import { useState } from 'react'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { CheckCircle, XCircle } from 'lucide-react'
import { useCapabilities } from '../../auth/capabilities.js'
import { useAuth } from '../../auth/useAuth.js'
import { listApprovals, decideApproval } from '../../api/endpoints/approvals.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage, toApiError } from '../../api/errors.js'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { Card, CardContent } from '../../components/ui/Card.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { ApprovalTimeline } from './ApprovalTimeline.jsx'
import { toolLabel, formatSummary } from '../../lib/approvals.js'

/**
 * Risk is the reason a decision is being asked for, so it leads.
 */
const RISK_TONE = { high: 'danger', medium: 'warning', low: 'neutral' }

function ApprovalCard({ approval, onDecide, viewerUserId, canDecide, pending }) {
  const isPending = approval.status === 'pending'

  // approvals.py:255 — the requester may NOT decide their own request.
  // Letting them click and collect a 403 is not a decision surface.
  const viewerIsRequester = approval.requester_user_id === viewerUserId
  const blockedByFourEyes = isPending && viewerIsRequester
  const decidable = isPending && canDecide && !viewerIsRequester

  return (
    <Card>
      <CardContent className="py-5">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[15px] font-semibold text-fg">
                {toolLabel(approval.tool_name)}
              </h3>
              <Badge variant={RISK_TONE[approval.risk_level] ?? 'neutral'} size="sm">
                {approval.risk_level} risk
              </Badge>
            </div>

            {approval.input_summary && (
              <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-fg-muted">
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

          <div className="flex shrink-0 flex-col items-stretch gap-2 sm:w-52">
            {decidable && (
              <>
                <Button
                  size="sm"
                  onClick={() => onDecide(approval.id, 'approve')}
                  disabled={pending}
                >
                  <CheckCircle className="mr-1 size-3.5" />
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => onDecide(approval.id, 'reject')}
                  disabled={pending}
                >
                  <XCircle className="mr-1 size-3.5" />
                  Reject
                </Button>
                <p className="text-[11px] leading-relaxed text-fg-muted">
                  Approving authorises this action. It does not run it.
                </p>
              </>
            )}

            {blockedByFourEyes && (
              <div className="rounded-lg border border-line bg-surface-raised px-3 py-2.5">
                <p className="text-[12px] font-medium text-fg">
                  You requested this
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-fg-muted">
                  Someone else has to decide it. Arc does not let a person
                  approve their own request.
                </p>
              </div>
            )}

            {isPending && !canDecide && !viewerIsRequester && (
              <p className="text-[11px] leading-relaxed text-fg-muted">
                You don&apos;t have access to decide approvals.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}


/**
 * Decision failures a reader can act on.
 *
 * The most likely one is the four-eyes rule (approvals.py:255), which the
 * card already prevents — but a stale list can still produce it.
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
      <div className="flex flex-col gap-8">
        <section>
          <PageHeader title="Approvals" />
        </section>
        <Card>
          <CardContent>
            <p className="text-[13px] text-fg-muted">
              You don't have access to approvals in this workspace.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <PageHeader title="Approvals"
          description="High-risk actions waiting on a human decision." />
        </div>
        <div className="flex gap-2">
          {[null, 'pending', 'approved', 'rejected'].map((s) => (
            <button
              key={s ?? 'all'}
              onClick={() => setStatusFilter(s)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                statusFilter === s
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'text-fg-muted hover:text-zinc-300'
              }`}
            >
              {s ?? 'All'}
            </button>
          ))}
        </div>
      </section>

      {isPending && <Spinner />}
      {isError && <ErrorState message={errorMessage(error)} />}

      {!isPending && !isError && approvals?.length === 0 && (
        <EmptyState
          title={
            statusFilter
              ? `No ${statusFilter} approvals`
              : 'No approvals'
          }
          description={
            statusFilter
              ? `No approval requests for this tenant have the status "${statusFilter}".`
              : 'There are no approval requests for this tenant yet.'
          }
        />
      )}

      {!isPending && !isError && approvals?.length > 0 && (
        <div className="flex flex-col gap-3">
          {[...approvals]
            .sort((a, b) => Number(b.status === 'pending') - Number(a.status === 'pending'))
            .map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onDecide={handleDecide}
              viewerUserId={principal?.sub}
              canDecide={canDecide}
              pending={decideMutation.isPending}
            />
            ))}
        </div>
      )}

      {decideMutation.isError && (
        <Card>
          <CardContent>
            <p className="text-[13px] text-danger">
              {decisionErrorMessage(decideMutation.error)}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
