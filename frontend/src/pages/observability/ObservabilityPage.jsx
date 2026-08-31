import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useTenant } from '../../tenant/useTenant.js'
import { queryKeys } from '../../api/queryKeys.js'
import { getTenantUsageSummary } from '../../api/endpoints/observability.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

export function ObservabilityPage() {
  const { tenantId } = useTenant()
  const { isDemo } = useAuth()

  const { data: usage, isLoading, error } = useQuery({
    queryKey: queryKeys.observabilityTenant(tenantId),
    queryFn: () => getTenantUsageSummary(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Activity className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Observability</h1>
            <p className="mt-1 text-sm text-zinc-500">Usage metrics for this tenant.</p>
          </div>
        </div>
      </section>

      {isLoading && <Spinner />}
      {error && <ErrorState error={error} />}

      {!isLoading && !error && (
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
                      <p className="text-xs text-zinc-500">Total Requests</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.error_count || 0}</p>
                      <p className="text-xs text-zinc-500">Errors</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.avg_duration_ms ? `${usage.http.avg_duration_ms.toFixed(1)}ms` : '—'}</p>
                      <p className="text-xs text-zinc-500">Avg Latency</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.http.p95_duration_ms ? `${usage.http.p95_duration_ms.toFixed(1)}ms` : '—'}</p>
                      <p className="text-xs text-zinc-500">P95 Latency</p>
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
                      <p className="text-xs text-zinc-500">Total Executions</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.successful || 0}</p>
                      <p className="text-xs text-zinc-500">Successful</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.failed || 0}</p>
                      <p className="text-xs text-zinc-500">Failed</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.tools.denied || 0}</p>
                      <p className="text-xs text-zinc-500">Denied</p>
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
                      <p className="text-xs text-zinc-500">Total Syncs</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.successful || 0}</p>
                      <p className="text-xs text-zinc-500">Successful</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.failed || 0}</p>
                      <p className="text-xs text-zinc-500">Failed</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.connectors.items_fetched || 0}</p>
                      <p className="text-xs text-zinc-500">Items Fetched</p>
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
                      <p className="text-xs text-zinc-500">Total Events</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.distinct_event_types || 0}</p>
                      <p className="text-xs text-zinc-500">Distinct Event Types</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.total_payload_bytes || 0}</p>
                      <p className="text-xs text-zinc-500">Payload Bytes</p>
                    </div>
                    <div className="p-3 rounded-lg bg-zinc-900/50">
                      <p className="text-2xl font-semibold text-zinc-100">{usage.webhooks.available ? 'Yes' : 'No'}</p>
                      <p className="text-xs text-zinc-500">Available</p>
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
