import { useState } from 'react'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { CheckCircle2, Clock, ShieldAlert, XCircle } from 'lucide-react'
import { useCapabilities } from '../../auth/capabilities.js'
import { getAgentRun, listAgentRuns, runAgent } from '../../api/endpoints/agent.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

const RUN_LIMIT = 20

/**
 * Bounded Agent runs (PRD 09).
 *
 * Starting a run posts to the real `POST /agent/runs`; history is read
 * from the observability aggregate. The two require different
 * permissions — `agent:execute` and `observability:read` — so they are
 * gated independently: an employee may start a run without being able to
 * read the tenant's run history.
 */

const STATUS_STYLE = {
  succeeded: { variant: 'emerald', icon: CheckCircle2, label: 'Succeeded' },
  failed: { variant: 'red', icon: XCircle, label: 'Failed' },
  approval_required: { variant: 'amber', icon: ShieldAlert, label: 'Approval required' },
  max_steps_reached: { variant: 'zinc', icon: Clock, label: 'Max steps reached' },
}

function StatusBadge({ status }) {
  const style = STATUS_STYLE[status] ?? { variant: 'zinc', icon: Clock, label: status ?? 'Unknown' }
  const Icon = style.icon
  return (
    <Badge variant={style.variant}>
      <span className="flex items-center gap-1">
        <Icon className="size-3" />
        {style.label}
      </span>
    </Badge>
  )
}

function RunSteps({ steps }) {
  if (!steps || steps.length === 0) {
    return (
      <p className="mt-2 text-[13px] text-fg-muted">
        No steps were executed for this run.
      </p>
    )
  }
  return (
    <ol className="mt-3 flex flex-col gap-2">
      {steps.map((step, index) => (
        <li
          key={step.id ?? `${step.skill_id ?? 'step'}-${index}`}
          className="rounded-lg border border-line/80 bg-surface p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-fg-muted">Step {index + 1}</span>
            {step.skill_id && (
              <span className="text-[13px] text-fg">{step.skill_id}</span>
            )}
            {step.status && <StatusBadge status={step.status} />}
          </div>
          {step.error_kind && (
            <p className="mt-1 text-[13px] text-red-400">{step.error_kind}</p>
          )}
        </li>
      ))}
    </ol>
  )
}

function RunCard({ run, tenantId, canReadHistory }) {
  const [expanded, setExpanded] = useState(false)

  // Detail is only fetched when the operator opens the run, and only when
  // they may read run history at all.
  const detail = useQuery({
    queryKey: queryKeys.agentRun(tenantId, run.id),
    queryFn: () => getAgentRun(tenantId, run.id),
    enabled: expanded && canReadHistory && Boolean(tenantId && run.id),
  })

  const shown = detail.data ?? run

  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-fg">{run.goal}</p>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-muted">
              <span>By: {run.principal_id}</span>
              <span>Started: {new Date(run.created_at).toLocaleString()}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}
            >
              {expanded ? 'Hide trace' : 'View trace'}
            </Button>
          </div>
        </div>

        {run.error_kind && (
          <p className="mt-2 text-[13px] text-red-400">Reason: {run.error_kind}</p>
        )}

        {expanded && (
          <div className="mt-2 border-t border-line/80 pt-3">
            {detail.isError ? (
              <ErrorState
                title="Could not load this trace"
                message={errorMessage(detail.error)}
                onRetry={() => detail.refetch()}
                error={detail.error}
              />
            ) : detail.isPending && detail.fetchStatus === 'fetching' ? (
              <Spinner />
            ) : (
              <RunSteps steps={shown.steps} />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function AgentRunsPage() {
  const { tenantId } = useParams()
  const { can } = useCapabilities()
  const queryClient = useQueryClient()
  const [goal, setGoal] = useState('')

  const canExecute = can('agent:execute')
  const canReadHistory = can('observability:read')

  const runsQuery = useQuery({
    queryKey: queryKeys.agentRuns(tenantId, RUN_LIMIT),
    queryFn: () => listAgentRuns(tenantId, { limit: RUN_LIMIT }),
    enabled: canReadHistory && Boolean(tenantId),
  })

  const startMutation = useMutation({
    mutationFn: () => runAgent(tenantId, { goal: goal.trim() }),
    onSuccess: () => {
      setGoal('')
      queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(tenantId, RUN_LIMIT) })
    },
  })

  const runs = runsQuery.data?.items ?? []
  const canSubmit = goal.trim().length > 0 && !startMutation.isPending

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!canSubmit) return
    startMutation.mutate()
  }

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <PageHeader title="Agents"
          description="Start a bounded agent run and review its trace." />
        </div>
      </section>

      {canExecute && (
        <Card>
          <CardContent>
            <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
              <label className="text-xs font-medium uppercase tracking-wide text-fg-muted" htmlFor="agent-goal">
                Goal
              </label>
              <Textarea
                id="agent-goal"
                rows={3}
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                placeholder="Describe what the agent should accomplish"
                disabled={startMutation.isPending}
              />
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={!canSubmit}>
                  {startMutation.isPending ? 'Starting…' : 'Start agent run'}
                </Button>
                {startMutation.isPending && <Spinner />}
              </div>
            </form>

            {startMutation.isError && (
              <div className="mt-3">
                <ErrorState
                  title="Could not start the agent run"
                  message={errorMessage(startMutation.error)}
                  error={startMutation.error}
                />
              </div>
            )}

            {startMutation.isSuccess && startMutation.data && (
              <div className="mt-3 rounded-lg border border-line/80 bg-surface p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] text-fg-subtle">Run started</span>
                  <StatusBadge status={startMutation.data.status} />
                </div>
                {startMutation.data.error_kind && (
                  <p className="mt-1 text-[13px] text-red-400">
                    Reason: {startMutation.data.error_kind}
                  </p>
                )}
                <RunSteps steps={startMutation.data.steps} />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!canExecute && (
        <Card>
          <CardContent>
            <p className="text-[13px] text-fg-muted">
              You don't have access to start agent runs in this workspace.
            </p>
          </CardContent>
        </Card>
      )}

      {!canReadHistory && (
        <Card>
          <CardContent>
            <p className="text-[13px] text-fg-muted">
              You don't have access to run history for this workspace.
            </p>
          </CardContent>
        </Card>
      )}

      {canReadHistory && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-fg">Recent runs</h2>

          {runsQuery.isPending && runsQuery.fetchStatus === 'fetching' && <Spinner />}

          {runsQuery.isError && (
            <Card>
              <ErrorState
                title="Could not load agent runs"
                message={errorMessage(runsQuery.error)}
                onRetry={() => runsQuery.refetch()}
                error={runsQuery.error}
              />
            </Card>
          )}

          {!runsQuery.isPending && !runsQuery.isError && runs.length === 0 && (
            <EmptyState
              title="No agent runs"
              description="Runs started for this tenant will appear here."
            />
          )}

          {!runsQuery.isError && runs.length > 0 && (
            <div className="flex flex-col gap-3">
              {runs.map((run) => (
                <RunCard
                  key={run.id}
                  run={run}
                  tenantId={tenantId}
                  canReadHistory={canReadHistory}
                />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
