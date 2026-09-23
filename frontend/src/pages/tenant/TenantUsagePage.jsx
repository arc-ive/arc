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
 * A dense block of figures.
 *
 * Thirteen bordered tiles in a grid was the wrong shape for this page.
 * Observability is the one surface in Arc that should be information-dense
 * — an operator scans it, comparing numbers against each other and against
 * yesterday — and a box around each figure puts 16px of padding and a rule
 * between every pair being compared.
 *
 * So: a table of figures. Label left, value right, grouped by a heading
 * and separated by hairlines. Same information, roughly a third of the
 * height, and a column of values that actually lines up.
 */
function FigureGroup({ title, children }) {
  return (
    <section className="min-w-0">
      <h2 className="type-label border-b border-line pb-2 text-fg-muted">{title}</h2>
      <dl className="mt-1">{children}</dl>
    </section>
  )
}

/**
 * One figure on a rule.
 *
 * An unreported metric does not get a measurement's typographic weight —
 * Issue #223's distinction, carried by type rather than only by wording.
 */
function Figure({ label, value, hint, unavailableHint = 'Not reported for this window' }) {
  const measured = value !== null && value !== undefined
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line py-2.5">
      <dt className="min-w-0 text-[13.5px] text-fg-subtle">
        {label}
        {hint && measured && (
          <span className="ml-2 text-[12px] text-fg-muted">{hint}</span>
        )}
        {!measured && (
          <span className="ml-2 text-[12px] text-fg-muted">{unavailableHint}</span>
        )}
      </dt>
      <dd
        className={cn(
          'shrink-0 tabular-nums',
          measured
            ? 'text-[17px] font-medium text-fg'
            : 'text-[13px] font-normal text-fg-muted',
        )}
      >
        {measured ? value : UNAVAILABLE}
      </dd>
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
        <div className="grid gap-x-16 gap-y-10 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, g) => (
            <div key={g}>
              <Skeleton className="h-3 w-20" />
              <div className="mt-4 flex flex-col gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-3 w-full" />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="grid gap-x-16 gap-y-10 sm:grid-cols-2">
            <FigureGroup title="Activity">
              <Figure
                label="API Requests"
                value={formatCount(data.http?.total_requests)}
              />
              <Figure
                label="AI Requests"
                value={formatCount(data.llm?.total_calls)}
              />
              <Figure
                label="Agent Runs"
                value={formatCount(data.agent_runs?.total_runs)}
              />
              <Figure
                label="Webhook Events"
                value={formatCount(data.webhooks?.total_events)}
              />
            </FigureGroup>

            <FigureGroup title="Response times">
              <Figure
                label="Avg Latency"
                value={formatMs(data.http?.avg_duration_ms)}
              />
              {/* Carried over from the Observability page, which was a
                  second view of this same endpoint. P95 was the only
                  figure it showed that this page did not. */}
              <Figure
                label="P95 Latency"
                value={formatMs(data.http?.p95_duration_ms)}
              />
              <Figure
                label="Error Rate"
                value={
                  isMeasured(data.http?.error_rate)
                    ? `${(data.http.error_rate * 100).toFixed(1)}%`
                    : null
                }
              />
              <Figure
                label="AI Latency"
                value={formatMs(data.llm?.avg_latency_ms)}
              />
            </FigureGroup>

            <FigureGroup title="Tool executions">
              <Figure
                label="Tool Calls"
                value={formatCount(data.tools?.total_executions)}
              />
              <Figure
                label="Successful"
                value={formatCount(data.tools?.successful)}
              />
              <Figure label="Failed" value={formatCount(data.tools?.failed)} />
              {/* The split is the one thing here worth drawing rather
                  than listing: successful and failed are components of
                  the total, and the bar says so without arithmetic. */}
              {isMeasured(data.tools?.successful) &&
                isMeasured(data.tools?.failed) &&
                data.tools.total_executions > 0 && (
                  <div
                    aria-hidden
                    className="mt-3 flex h-1 overflow-hidden rounded-full bg-surface-sunk"
                  >
                    <span
                      className="bg-success"
                      style={{
                        width: `${(data.tools.successful / data.tools.total_executions) * 100}%`,
                      }}
                    />
                    <span
                      className="bg-danger"
                      style={{
                        width: `${(data.tools.failed / data.tools.total_executions) * 100}%`,
                      }}
                    />
                  </div>
                )}
            </FigureGroup>

            <FigureGroup title="AI consumption">
              <Figure
                label="Tokens"
                value={formatCount(data.llm?.total_tokens)}
                hint="input and output"
              />
              <Figure
                label="AI Cost"
                value={formatUsd(data.llm?.total_cost_usd)}
                hint={
                  data.llm?.cost_coverage === 'partial'
                    ? `partial — ${formatCount(data.llm?.unknown_cost_records)} call(s) without pricing`
                    : undefined
                }
                unavailableHint={
                  data.llm?.cost_coverage === 'none' && data.llm?.total_calls === 0
                    ? 'No LLM calls in this window'
                    : 'Pricing unavailable for these calls'
                }
              />
            </FigureGroup>
          </div>

          {data.window_hours && (
            <p className="mt-10 text-xs text-fg-muted">
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
