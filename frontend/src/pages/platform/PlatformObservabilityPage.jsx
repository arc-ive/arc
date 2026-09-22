import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { queryKeys } from '../../api/queryKeys.js'
import { getPlatformObservabilitySummary, getComponentHealth } from '../../api/endpoints/observability.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

function ComponentHealth() {

  const healthQuery = useQuery({
    queryKey: queryKeys.healthComponents(),
    queryFn: getComponentHealth,
    refetchInterval: 30000,
    retry: 2,
  })

  if (healthQuery.isLoading) return <Spinner />
  if (healthQuery.error) return <ErrorState error={healthQuery.error} onRetry={() => healthQuery.refetch()} />

  const components = healthQuery.data?.components || {}
  const overall = healthQuery.data?.overall || 'unknown'

  return (
    <Card>
      <CardHeader title="Component Health" description="Status of platform components." />
      <CardContent>
        <div className="flex items-center gap-3 mb-4">
          <Badge variant={overall === 'healthy' ? 'green' : 'red'} dot>{overall}</Badge>
        </div>
        <div className="space-y-2">
          {Object.entries(components).map(([name, info]) => (
            <div key={name} className="flex items-center justify-between py-2 border-b border-zinc-800 last:border-0">
              <span className="text-sm text-zinc-300">{name}</span>
              <Badge variant={info.status === 'healthy' ? 'green' : 'red'} size="sm">
                {info.status}
              </Badge>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function PlatformSummary() {

  const summaryQuery = useQuery({
    queryKey: queryKeys.observabilityPlatform(),
    queryFn: getPlatformObservabilitySummary,
    retry: 2,
    refetchOnWindowFocus: true,
  })

  if (summaryQuery.isLoading) return <Spinner />
  if (summaryQuery.error) return <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />

  const http = summaryQuery.data?.http || {}

  return (
    <Card>
      <CardHeader title="Platform Summary" description="Aggregate platform metrics (tenant-agnostic)." />
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-2xl font-semibold text-zinc-100">{http.total_requests || 0}</p>
            <p className="text-xs text-fg-muted">Total API Requests</p>
          </div>
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-2xl font-semibold text-zinc-100">{http.error_count || 0}</p>
            <p className="text-xs text-fg-muted">Errors</p>
          </div>
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-2xl font-semibold text-zinc-100">{http.avg_duration_ms ? `${http.avg_duration_ms.toFixed(1)}ms` : '—'}</p>
            <p className="text-xs text-fg-muted">Avg Latency</p>
          </div>
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-2xl font-semibold text-zinc-100">{summaryQuery.data?.tool_activity_total || 0}</p>
            <p className="text-xs text-fg-muted">Tool Executions</p>
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-3 mt-4">
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-lg font-semibold text-zinc-100">{summaryQuery.data?.connector_syncs_total || 0}</p>
            <p className="text-xs text-fg-muted">Connector Syncs</p>
          </div>
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-lg font-semibold text-zinc-100">{summaryQuery.data?.webhook_events_total || 0}</p>
            <p className="text-xs text-fg-muted">Webhook Events</p>
          </div>
          <div className="p-3 rounded-lg bg-zinc-900/50">
            <p className="text-lg font-semibold text-zinc-100">{http.error_rate ? `${(http.error_rate * 100).toFixed(1)}%` : '0%'}</p>
            <p className="text-xs text-fg-muted">Error Rate</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function PlatformObservabilityPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title="Observability"
          description="Platform-level telemetry and operational insight." />
          </div>
        </div>
      </section>

      <PlatformSummary />
      <ComponentHealth />
    </div>
  )
}
