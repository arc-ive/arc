import { useState } from 'react'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Clock, CheckCircle, XCircle, AlertTriangle } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { listApprovals, decideApproval } from '../../api/endpoints/approvals.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { Card, CardContent } from '../../components/ui/Card.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

const STATUS_STYLES = {
  pending: { color: 'text-amber-400', icon: Clock, label: 'Pending' },
  approved: { color: 'text-emerald-400', icon: CheckCircle, label: 'Approved' },
  rejected: { color: 'text-red-400', icon: XCircle, label: 'Rejected' },
  expired: { color: 'text-fg-muted', icon: AlertTriangle, label: 'Expired' },
  consumed: { color: 'text-blue-400', icon: CheckCircle, label: 'Consumed' },
}

function ApprovalCard({ approval, onDecide }) {
  const style = STATUS_STYLES[approval.status] || STATUS_STYLES.pending
  const Icon = style.icon
  const canDecide = approval.status === 'pending'

  return (
    <Card>
      <CardContent>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-zinc-100">
                {approval.tool_name}
              </h3>
              <Badge variant="neutral">{approval.tool_version}</Badge>
              <span className={`flex items-center gap-1 text-xs ${style.color}`}>
                <Icon className="size-3" />
                {style.label}
              </span>
            </div>
            {approval.input_summary && (
              <p className="mt-1 text-xs text-fg-muted line-clamp-2">
                {approval.input_summary}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-muted">
              <span>Risk: {approval.risk_level}</span>
              <span>By: {approval.requester_user_id}</span>
              <span>Created: {new Date(approval.created_at).toLocaleString()}</span>
              {approval.expires_at && (
                <span>Expires: {new Date(approval.expires_at).toLocaleString()}</span>
              )}
            </div>
          </div>
          {canDecide && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onDecide(approval.id, 'approve')}
              >
                <CheckCircle className="mr-1 size-3" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => onDecide(approval.id, 'reject')}
              >
                <XCircle className="mr-1 size-3" />
                Reject
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function ApprovalsPage() {
  const { tenantId } = useParams()
  const { isDemo } = useAuth()
  const { can } = useCapabilities()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState(null)

  const canRead = can('approval:read')
  const canDecide = can('approval:decide')

  const { data: approvals, isPending, isError, error } = useQuery({
    queryKey: queryKeys.approvalsList(tenantId, statusFilter),
    queryFn: () => listApprovals(tenantId, { status: statusFilter }),
    enabled: !isDemo && Boolean(tenantId) && canRead,
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

  if (isDemo) {
    return (
      <div className="flex flex-col gap-8">
        <section>
          <PageHeader title="Approvals"
          description="Human Intervention approval requests." />
        </section>
        <Card>
          <CardContent>
            <p className="text-[13px] text-fg-muted">
              Demo Mode — approval data requires a backend session.
              Sign in with a real JWT to view approvals.
            </p>
          </CardContent>
        </Card>
      </div>
    )
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
          description="Human Intervention approval requests for this tenant." />
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
              ? `No ${STATUS_STYLES[statusFilter]?.label.toLowerCase() ?? statusFilter} approvals`
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
          {approvals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              onDecide={canDecide ? handleDecide : undefined}
            />
          ))}
        </div>
      )}

      {decideMutation.isError && (
        <Card>
          <CardContent>
            <p className="text-[13px] text-red-400">
              Decision failed: {errorMessage(decideMutation.error)}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
