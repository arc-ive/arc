import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { BarChart3 } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
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

function StatCard({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-panel p-4 shadow-card">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </p>
      <div className="mt-2 text-2xl font-semibold text-zinc-100">
        {value ?? '—'}
      </div>
      {hint && (
        <p className="mt-1 text-[13px] text-zinc-500">
          {hint}
        </p>
      )}
    </div>
  )
}

export function TenantUsagePage() {
  const { tenantId } = useParams()
  const { isDemo } = useAuth()
  const [hours, setHours] = useState(24)

  const usage = useQuery({
    queryKey: queryKeys.observabilityTenant(tenantId, hours),
    queryFn: () => getTenantUsageSummary(tenantId, { hours }),
    enabled: !isDemo && Boolean(tenantId),
  })

  const data = usage.data

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <BarChart3 className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Usage
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Tenant-scoped metrics for AI and platform usage.
            </p>
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
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {period.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {isDemo && (
        <Card>
          <p className="text-sm text-zinc-500">
            Usage metrics are only available with a live backend session.
          </p>
        </Card>
      )}

      {usage.isError && !isDemo && (
        <Card>
          <ErrorState
            title="Could not load usage metrics"
            message={errorMessage(usage.error)}
            onRetry={() => usage.refetch()}
          />
        </Card>
      )}

      {usage.isPending && !isDemo && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-zinc-800/80 bg-panel p-4 shadow-card">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="mt-2 h-7 w-12" />
            </div>
          ))}
        </div>
      )}

      {data && !isDemo && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="API Requests"
              value={data.api_requests ?? 0}
              hint="Total API calls"
            />
            <StatCard
              label="AI Requests"
              value={data.ai_requests ?? 0}
              hint="Intelligence queries"
            />
            <StatCard
              label="Tokens"
              value={data.tokens ?? 0}
              hint="Total tokens consumed"
            />
            <StatCard
              label="Agent Runs"
              value={data.agent_runs ?? 0}
              hint="Automated agent executions"
            />
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Tool Calls"
              value={data.tool_calls ?? 0}
              hint="External tool invocations"
            />
            <StatCard
              label="Webhook Events"
              value={data.webhook_events ?? 0}
              hint="Inbound webhook deliveries"
            />
            <StatCard
              label="Successful"
              value={data.successful_executions ?? 0}
              hint="Completed without error"
            />
            <StatCard
              label="Failed"
              value={data.failed_executions ?? 0}
              hint="Encountered an error"
            />
          </section>

          <section className="grid gap-4 sm:grid-cols-2">
            <StatCard
              label="Avg Latency"
              value={data.avg_latency_ms != null ? `${Math.round(data.avg_latency_ms)}ms` : '—'}
              hint="Mean response time"
            />
            <StatCard
              label="Error Rate"
              value={data.error_rate != null ? `${(data.error_rate * 100).toFixed(1)}%` : '—'}
              hint="Failed / total executions"
            />
          </section>

          {data.period_hours && (
            <p className="text-xs text-zinc-600">
              Metrics cover the last {data.period_hours} hours.
            </p>
          )}
        </>
      )}

      {!data && !usage.isPending && !usage.isError && !isDemo && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <BarChart3 className="size-8 text-zinc-700" />
            <p className="text-sm text-zinc-500">No usage data available for this period.</p>
          </div>
        </Card>
      )}
    </div>
  )
}
