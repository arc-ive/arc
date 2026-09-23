import { useState } from 'react'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { BarChart3 } from 'lucide-react'
import { getTenantUsageSummary } from '../../api/endpoints/observability.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { cn } from '../../lib/cn.js'
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

function formatMs(value) {
  return isMeasured(value) ? `${Math.round(value)}ms` : null
}

/**
 * A named group of related metrics.
 *
 * The page previously ran three ungrouped rows of four tiles. The grouping
 * existed in the markup — three sibling `<section>`s — but nothing on
 * screen said so, and the reader met thirteen figures of identical weight.
 * A heading per group is the cheapest thing that makes the page scannable,
 * and it gives assistive technology a landmark to jump between.
 */
function MetricGroup({ title, children, columns = 4 }) {
  return (
    <section aria-labelledby={`usage-${slug(title)}`}>
      <h2
        id={`usage-${slug(title)}`}
        className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
      >
        {title}
      </h2>
      <div
        className={cn(
          'grid gap-3 sm:grid-cols-2',
          columns === 4 ? 'lg:grid-cols-4' : 'lg:grid-cols-2',
        )}
      >
        {children}
      </div>
    </section>
  )
}

function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-')
}

/** A tile whose value comes from the backend summary. */
function MetricCard({
  label,
  value,
  hint,
  unavailableHint = 'Not reported for this window',
  size = 'lg',
}) {
  const measured = value !== null && value !== undefined
  return (
    <StatCard
      label={label}
      value={measured ? value : UNAVAILABLE}
      hint={measured ? hint : unavailableHint}
      measured={measured}
      size={size}
    />
  )
}

function StatCard({ label, value, hint, measured = true, size = 'lg' }) {
  return (
    <div className="flex flex-col rounded-xl border border-line bg-panel p-4 shadow-card">
      <p className="text-[11px] font-medium uppercase tracking-wider text-fg-muted">
        {label}
      </p>
      <div
        className={cn(
          'mt-1.5 font-semibold tabular-nums',
          // An unreported metric is not a measurement, so it does not get a
          // measurement's typographic weight. "Unavailable" was rendering
          // at the same 2xl as a real figure and shouting louder than the
          // numbers around it.
          measured
            ? size === 'lg'
              ? 'text-2xl text-fg'
              : 'text-xl text-fg'
            : 'text-sm font-normal text-fg-muted',
        )}
      >
        {value ?? '—'}
      </div>
      {hint && <p className="mt-1 text-[12px] leading-snug text-fg-muted">{hint}</p>}
    </div>
  )
}

/**
 * Tool executions, shown as the breakdown they actually are.
 *
 * `successful` and `failed` are components of `total_executions` — with the
 * reference workspace they read 5, 2 and 7. All three were rendered as peer
 * tiles in a row that also held Webhook Events, so the one fact worth
 * knowing (that two in seven failed) had to be worked out by the reader
 * doing arithmetic across three cards.
 */
function ToolExecutionCard({ tools }) {
  const total = tools?.total_executions
  const successful = tools?.successful
  const failed = tools?.failed
  const haveSplit = isMeasured(successful) && isMeasured(failed)
  const denominator = isMeasured(total) && total > 0 ? total : null

  return (
    <div className="flex flex-col rounded-xl border border-line bg-panel p-4 shadow-card sm:col-span-2">
      <p className="text-[11px] font-medium uppercase tracking-wider text-fg-muted">
        Tool Calls
      </p>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span
          className={cn(
            'font-semibold tabular-nums',
            isMeasured(total) ? 'text-2xl text-fg' : 'text-sm font-normal text-fg-muted',
          )}
        >
          {formatCount(total) ?? UNAVAILABLE}
        </span>
        {isMeasured(total) && (
          <span className="text-[12px] text-fg-muted">external tool invocations</span>
        )}
      </div>

      {haveSplit && denominator ? (
        <>
          <div
            className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-raised"
            aria-hidden
          >
            <span
              className="bg-success"
              style={{ width: `${(successful / denominator) * 100}%` }}
            />
            <span
              className="bg-danger"
              style={{ width: `${(failed / denominator) * 100}%` }}
            />
          </div>
          <dl className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1">
            <div className="flex items-center gap-1.5">
              <span aria-hidden className="size-1.5 rounded-full bg-success" />
              <dt className="text-[12px] text-fg-muted">Successful</dt>
              <dd className="text-[13px] font-medium tabular-nums text-fg">
                {formatCount(successful)}
              </dd>
            </div>
            <div className="flex items-center gap-1.5">
              <span aria-hidden className="size-1.5 rounded-full bg-danger" />
              <dt className="text-[12px] text-fg-muted">Failed</dt>
              <dd className="text-[13px] font-medium tabular-nums text-fg">
                {formatCount(failed)}
              </dd>
            </div>
          </dl>
        </>
      ) : (
        <dl className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1">
          <div className="flex items-center gap-1.5">
            <dt className="text-[12px] text-fg-muted">Successful</dt>
            <dd className="text-[13px] font-medium tabular-nums text-fg">
              {formatCount(successful) ?? UNAVAILABLE}
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-[12px] text-fg-muted">Failed</dt>
            <dd className="text-[13px] font-medium tabular-nums text-fg">
              {formatCount(failed) ?? UNAVAILABLE}
            </dd>
          </div>
        </dl>
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
            <PageHeader
              title="Usage"
              description="AI and platform usage for this workspace."
            />
          </div>
          <div
            role="group"
            aria-label="Reporting period"
            className="flex gap-1 rounded-lg border border-line bg-surface p-0.5"
          >
            {PERIODS.map((period) => (
              <button
                key={period.hours}
                type="button"
                onClick={() => setHours(period.hours)}
                aria-pressed={hours === period.hours}
                className={cn(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
                  hours === period.hours
                    ? 'bg-surface-elevated text-fg'
                    : 'text-fg-muted hover:text-fg',
                )}
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
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-line bg-panel p-4 shadow-card">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="mt-2 h-7 w-12" />
            </div>
          ))}
        </div>
      )}

      {data && (
        <>
          <MetricGroup title="Activity">
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
              label="Agent Runs"
              value={formatCount(data.agent_runs?.total_runs)}
              hint="Bounded agent executions"
            />
            <MetricCard
              label="Webhook Events"
              value={formatCount(data.webhooks?.total_events)}
              hint="Inbound webhook deliveries"
            />
          </MetricGroup>

          <MetricGroup title="Tool executions" columns={2}>
            <ToolExecutionCard tools={data.tools} />
          </MetricGroup>

          <MetricGroup title="Response times">
            <MetricCard
              size="sm"
              label="Avg Latency"
              value={formatMs(data.http?.avg_duration_ms)}
              hint="Mean response time"
            />
            {/* Carried over from the Observability page, which was a second
                view of this same endpoint. P95 was the only figure it showed
                that this page did not, so folding the two together must not
                lose it. */}
            <MetricCard
              size="sm"
              label="P95 Latency"
              value={formatMs(data.http?.p95_duration_ms)}
              hint="Slowest 5% of requests"
            />
            <MetricCard
              size="sm"
              label="Error Rate"
              value={
                isMeasured(data.http?.error_rate)
                  ? `${(data.http.error_rate * 100).toFixed(1)}%`
                  : null
              }
              hint="Failed / total requests"
            />
            <MetricCard
              size="sm"
              label="AI Latency"
              value={formatMs(data.llm?.avg_latency_ms)}
              hint="Mean LLM call duration"
            />
          </MetricGroup>

          <MetricGroup title="AI consumption" columns={2}>
            <MetricCard
              label="Tokens"
              value={formatCount(data.llm?.total_tokens)}
              hint="Input and output tokens"
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
          </MetricGroup>

          {data.window_hours && (
            <p className="text-xs text-fg-muted">
              Metrics cover the last {data.window_hours} hours.
            </p>
          )}
        </>
      )}

      {!data && !usage.isPending && !usage.isError && (
        <Card>
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <BarChart3 className="size-8 text-fg-muted" />
            <p className="text-sm text-fg-muted">
              No usage data available for this period.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}
