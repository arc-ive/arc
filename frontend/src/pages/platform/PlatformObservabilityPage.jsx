import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../../api/queryKeys.js'
import {
  getPlatformObservabilitySummary,
  getComponentHealth,
} from '../../api/endpoints/observability.js'
import { errorMessage } from '../../api/errors.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Section, Stat } from '../../components/layout/Section.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * Platform telemetry.
 *
 * Recomposed around the question an operator actually opens this page
 * with — "is anything wrong right now?" — rather than around the shape of
 * the response. The old version led with eight figures in eight boxes,
 * which is the same page whether the platform is healthy or on fire.
 *
 * So health leads, and it leads with the components that are NOT healthy.
 * Volume figures follow, because they are context for the answer rather
 * than the answer. Error rate sits with them but reads as a rate, not as
 * a fourth identical tile.
 */

function healthTone(status) {
  if (status === 'healthy') return 'success'
  if (status === 'degraded') return 'warning'
  return 'danger'
}

function ratio(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '0%'
  return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`
}

function count(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '0'
  return value.toLocaleString()
}

export function PlatformObservabilityPage() {
  useDocumentTitle('Observability')

  const health = useQuery({
    queryKey: queryKeys.healthComponents(),
    queryFn: getComponentHealth,
    refetchInterval: 30000,
    retry: 2,
  })

  const summary = useQuery({
    queryKey: queryKeys.observabilityPlatform(),
    queryFn: getPlatformObservabilitySummary,
    retry: 2,
    refetchOnWindowFocus: true,
  })

  const components = Object.entries(health.data?.components ?? {})
  const overall = health.data?.overall
  // Lead with what is wrong. On a healthy platform this is empty and the
  // page says so in one line instead of listing eight green rows.
  const unhealthy = components.filter(([, info]) => info.status !== 'healthy')
  const http = summary.data?.http ?? {}

  return (
    <div className="flex flex-col">
      <header>
        <h1 className="type-display-lg text-fg">Observability</h1>
        <p className="measure mt-2 text-[14px] text-fg-muted">
          Platform-wide telemetry. These figures cross every workspace and
          belong to the platform, not to any one customer.
        </p>
      </header>

      <Section title="Right now" className="mt-10">
        {health.isPending && (
          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-4 w-80" />
          </div>
        )}

        {health.isError && (
          <ErrorState
            title="Could not reach the health endpoint"
            message={errorMessage(health.error)}
            onRetry={() => health.refetch()}
            error={health.error}
          />
        )}

        {!health.isPending && !health.isError && (
          <div className="border-t border-line pt-5">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={healthTone(overall)} dot>
                {overall ?? 'unknown'}
              </Badge>
              <p className="text-[14px] text-fg-subtle">
                {unhealthy.length === 0
                  ? `All ${components.length} components reporting healthy.`
                  : `${unhealthy.length} of ${components.length} components need attention.`}
              </p>
            </div>

            {unhealthy.length > 0 && (
              <ul className="stagger mt-5 border-t border-line">
                {unhealthy.map(([name, info]) => (
                  <li
                    key={name}
                    className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-b border-line py-3"
                  >
                    <span className="font-mono text-[13px] text-fg">{name}</span>
                    <Badge variant={healthTone(info.status)} size="sm" dot>
                      {info.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}

            {/* The healthy ones still deserve naming — an operator needs to
                know what is being watched, not only what is failing — but
                as a quiet line rather than eight rows of green. */}
            {components.length > unhealthy.length && (
              <p className="measure mt-4 text-[12.5px] leading-relaxed text-fg-muted">
                Healthy:{' '}
                {components
                  .filter(([, info]) => info.status === 'healthy')
                  .map(([name]) => name)
                  .join(', ')}
                .
              </p>
            )}
          </div>
        )}
      </Section>

      <Section title="Volume" className="mt-12">
        {summary.isPending && (
          <div className="grid grid-cols-2 gap-8 border-t border-line pt-5 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-7 w-16" />
              </div>
            ))}
          </div>
        )}

        {summary.isError && (
          <ErrorState
            title="Could not load platform telemetry"
            message={errorMessage(summary.error)}
            onRetry={() => summary.refetch()}
            error={summary.error}
          />
        )}

        {!summary.isPending && !summary.isError && (
          <>
            <div className="grid grid-cols-2 gap-x-8 gap-y-9 border-t border-line pt-6 lg:grid-cols-4">
              <Stat
                label="API requests"
                value={count(http.total_requests)}
                hint={
                  http.avg_duration_ms
                    ? `${http.avg_duration_ms.toFixed(1)}ms average`
                    : 'No latency recorded'
                }
              />
              <Stat
                label="Errors"
                value={count(http.error_count)}
                hint={`${ratio(http.error_rate)} of requests`}
              />
              <Stat
                label="Tool executions"
                value={count(summary.data?.tool_activity_total)}
                hint="Through the execution boundary"
              />
              <Stat
                label="Connector syncs"
                value={count(summary.data?.connector_syncs_total)}
                hint={`${count(summary.data?.webhook_events_total)} webhook events`}
              />
            </div>

            <p className="measure mt-8 text-[12.5px] leading-relaxed text-fg-muted">
              Counts are cumulative for the platform process. Per-workspace
              usage is reported inside each workspace, where it can be
              attributed to a tenant.
            </p>
          </>
        )}
      </Section>
    </div>
  )
}
