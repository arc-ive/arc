import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useAuth } from '../../auth/useAuth.js'
import { useTenant } from '../../tenant/useTenant.js'
import { queryKeys } from '../../api/queryKeys.js'
import { getTenantUsageSummary } from '../../api/endpoints/observability.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'

export function ObservabilityPage() {
  const { tenantId } = useTenant()
  const { isDemo } = useAuth()

  const usageQuery = useQuery({
    queryKey: queryKeys.observabilityTenant(tenantId),
    queryFn: () => getTenantUsageSummary(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })
  const usage = usageQuery.data
  const isLoading = isQueryLoading(usageQuery)
  // Issue #225: a failed-and-parked query is a failure, not loading.
  const failed = isQueryFailed(usageQuery)
  const error = usageQuery.error

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title="Observability"
          description="Usage metrics for this tenant." />
          </div>
        </div>
      </section>

      {isLoading && <Spinner />}
      {failed && (
        <ErrorState
          error={error}
          message={error ? undefined : STALLED_MESSAGE}
          onRetry={() => usageQuery.refetch()}
        />
      )}

      {!isLoading && !failed && (
        <Card>
          <CardHeader title="Usage Summary" description={`Metrics over the last ${usage?.window_hours || 24} hours.`} />
          <CardContent>
            <div className="space-y-6">
              {usage?.http && (
                <div>
                  <h3 className="text-sm font-medium text-zinc-200 mb-3">HTTP</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.total_requests || 0}</p>
                      <p className="text-xs text-fg-muted">Total Requests</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.error_count || 0}</p>
                      <p className="text-xs text-fg-muted">Errors</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.avg_duration_ms ? `${usage.http.avg_duration_ms.toFixed(1)}ms` : '—'}</p>
                      <p className="text-xs text-fg-muted">Avg Latency</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.p95_duration_ms ? `${usage.http.p95_duration_ms.toFixed(1)}ms` : '—'}</p>
                      <p className="text-xs text-fg-muted">P95 Latency</p>
                    </div>
                  </div>
                </div>
              )}

              {usage?.tools && (
                <div>
                  <h3 className="text-sm font-medium text-zinc-200 mb-3">Tools</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.total_executions || 0}</p>
                      <p className="text-xs text-fg-muted">Total Executions</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.successful || 0}</p>
                      <p className="text-xs text-fg-muted">Successful</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.failed || 0}</p>
                      <p className="text-xs text-fg-muted">Failed</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.denied || 0}</p>
                      <p className="text-xs text-fg-muted">Denied</p>
                    </div>
                  </div>
                </div>
              )}

              {usage?.connectors && (
                <div>
                  <h3 className="text-sm font-medium text-zinc-200 mb-3">Connectors</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.total_syncs || 0}</p>
                      <p className="text-xs text-fg-muted">Total Syncs</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.successful || 0}</p>
                      <p className="text-xs text-fg-muted">Successful</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.failed || 0}</p>
                      <p className="text-xs text-fg-muted">Failed</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.items_fetched || 0}</p>
                      <p className="text-xs text-fg-muted">Items Fetched</p>
                    </div>
                  </div>
                </div>
              )}

              {usage?.webhooks && (
                <div>
                  <h3 className="text-sm font-medium text-zinc-200 mb-3">Webhooks</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.total_events || 0}</p>
                      <p className="text-xs text-fg-muted">Total Events</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.distinct_event_types || 0}</p>
                      <p className="text-xs text-fg-muted">Distinct Event Types</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.total_payload_bytes || 0}</p>
                      <p className="text-xs text-fg-muted">Payload Bytes</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.available ? 'Yes' : 'No'}</p>
                      <p className="text-xs text-fg-muted">Available</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
