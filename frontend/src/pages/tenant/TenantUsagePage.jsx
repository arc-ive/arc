import { useState } from 'react'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { BarChart3 } from 'lucide-react'
import { getTenantUsageSummary } from '../../api/endpoints/observability.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card } from '../../components/ui/Card.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

const PERIODS = [
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
]

// Issue #223: a metric the backend reports as 0 is a real measurement and
// must read as 0. Only a value the backend did not supply is unavailable,
// and it says so explicitly rather than claiming the metric is "not
// tracked" when the platform does in fact track it.
const UNAVAILABLE = 'Unavailable'

function isMeasured(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function formatCount(value) {
  return isMeasured(value) ? value.toLocaleString() : null
}

function formatUsd(value) {
  return typeof value === 'number' && Number.isFinite(value)
    ? `$${value.toFixed(value < 1 ? 4 : 2)}`
    : null
}

/** A tile whose value comes from the backend summary. */
function MetricCard({ label, value, hint, unavailableHint = 'Not reported for this window' }) {
  const measured = value !== null && value !== undefined
  return (
    <StatCard
      label={label}
      value={measured ? value : UNAVAILABLE}
      hint={measured ? hint : unavailableHint}
    />
  )
}

function StatCard({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-panel p-4 shadow-card">
      <p className="text-xs font-medium uppercase tracking-wide text-fg-muted">
        {label}
      </p>
      <div className="mt-2 text-2xl font-semibold text-zinc-100">
        {value ?? '—'}
      </div>
      {hint && (
        <p className="mt-1 text-[13px] text-fg-muted">
          {hint}
        </p>
      )}
    </div>
  )
}

export function TenantUsagePage() {
  const { tenantId } = useParams()
  const [hours, setHours] = useState(24)

  const usage = useQuery({
    queryKey: queryKeys.observabilityTenant(tenantId, hours),
    queryFn: () => getTenantUsageSummary(tenantId, { hours }),
    enabled: Boolean(tenantId),
  })

  const data = usage.data

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title="Usage"
          description="AI and platform usage for this workspace." />
          </div>
          <div className="flex gap-1 rounded-lg border border-zinc-800 bg-zinc-900/60 p-0.5">
            {PERIODS.map((period) => (
              <button
                key={period.hours}
                type="button"
                onClick={() => setHours(period.hours)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  hours === period.hours
                    ? 'bg-zinc-700 text-zinc-100'
                    : 'text-fg-muted hover:text-zinc-300'
                }`}
              >
                {period.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {usage.isError && (
        <Card>
          <ErrorState
            title="Could not load usage metrics"
            message={errorMessage(usage.error)}
            onRetry={() => usage.refetch()}
          />
        </Card>
      )}

      {usage.isPending && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-zinc-800/80 bg-panel p-4 shadow-card">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="mt-2 h-7 w-12" />
            </div>
          ))}
        </div>
      )}

      {data && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="API Requests"
              value={formatCount(data.http?.total_requests)}
              hint="Total API calls"
            />
            <MetricCard
              label="AI Requests"
              value={formatCount(data.llm?.total_calls)}
              hint="LLM calls in this window"
            />
            <MetricCard
              label="Tokens"
              value={formatCount(data.llm?.total_tokens)}
              hint="Input and output tokens"
            />
            <MetricCard
              label="Agent Runs"
              value={formatCount(data.agent_runs?.total_runs)}
              hint="Bounded agent executions"
            />
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Tool Calls"
              value={formatCount(data.tools?.total_executions)}
              hint="External tool invocations"
            />
            <MetricCard
              label="Webhook Events"
              value={formatCount(data.webhooks?.total_events)}
              hint="Inbound webhook deliveries"
            />
            <MetricCard
              label="Successful"
              value={formatCount(data.tools?.successful)}
              hint="Completed without error"
            />
            <MetricCard
              label="Failed"
              value={formatCount(data.tools?.failed)}
              hint="Encountered an error"
            />
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Avg Latency"
              value={isMeasured(data.http?.avg_duration_ms) ? `${Math.round(data.http.avg_duration_ms)}ms` : null}
              hint="Mean response time"
            />
            {/* Carried over from the Observability page, which was a second
                view of this same endpoint. P95 was the only figure it showed
                that this page did not, so folding the two together must not
                lose it. */}
            <MetricCard
              label="P95 Latency"
              value={isMeasured(data.http?.p95_duration_ms) ? `${Math.round(data.http.p95_duration_ms)}ms` : null}
              hint="Slowest 5% of requests"
            />
            <MetricCard
              label="Error Rate"
              value={isMeasured(data.http?.error_rate) ? `${(data.http.error_rate * 100).toFixed(1)}%` : null}
              hint="Failed / total requests"
            />
            <MetricCard
              label="AI Latency"
              value={isMeasured(data.llm?.avg_latency_ms) ? `${Math.round(data.llm.avg_latency_ms)}ms` : null}
              hint="Mean LLM call duration"
            />
            <MetricCard
              label="AI Cost"
              value={formatUsd(data.llm?.total_cost_usd)}
              hint={
                data.llm?.cost_coverage === 'partial'
                  ? `Partial: ${formatCount(data.llm?.unknown_cost_records)} call(s) without pricing`
                  : 'Cost across all LLM calls'
              }
              unavailableHint={
                data.llm?.cost_coverage === 'none' && data.llm?.total_calls === 0
                  ? 'No LLM calls in this window'
                  : 'Pricing unavailable for these calls'
              }
            />
          </section>

          {data.window_hours && (
            <p className="text-xs text-fg-muted">
              Metrics cover the last {data.window_hours} hours.
            </p>
          )}
        </>
      )}

      {!data && !usage.isPending && !usage.isError  && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <BarChart3 className="size-8 text-zinc-700" />
            <p className="text-sm text-fg-muted">No usage data available for this period.</p>
          </div>
        </Card>
      )}
    </div>
  )
}
