import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { Webhook, AlertTriangle, CheckCircle } from 'lucide-react'
import { useTenant } from '../../tenant/useTenant.js'
import { queryKeys } from '../../api/queryKeys.js'
import { listWebhookEvents } from '../../api/endpoints/webhooks.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'

export function WebhooksPage() {
  const { tenantId } = useTenant()

  const eventsQuery = useQuery({
    queryKey: queryKeys.webhookEvents(tenantId),
    queryFn: () => listWebhookEvents(tenantId),
    enabled: Boolean(tenantId),
  })
  const events = eventsQuery.data
  const isLoading = isQueryLoading(eventsQuery)
  // Issue #225: a failed-and-parked query is a failure, not loading.
  const failed = isQueryFailed(eventsQuery)
  const error = eventsQuery.error

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title="Webhooks"
          description="Inbound webhook events for this tenant." />
          </div>
        </div>
      </section>

      {isLoading && <Spinner />}
      {failed && (
        <ErrorState
          error={error}
          message={error ? undefined : STALLED_MESSAGE}
          onRetry={() => eventsQuery.refetch()}
        />
      )}

      {!isLoading && !failed && (!events || events.length === 0) && (
        <EmptyState
          icon={Webhook}
          title="No webhook events"
          description="Webhook events from external integrations will appear here."
        />
      )}

      {!isLoading && !failed && events && events.length > 0 && (
        <Card>
          <CardHeader
            title="Recent Events"
            description={`${events.length} event${events.length !== 1 ? 's' : ''} received`}
          />
          <CardContent>
            <div className="space-y-3">
              {events.map((event) => (
                <div
                  key={event.id}
                  className="flex items-center justify-between py-3 border-b border-zinc-800 last:border-0"
                >
                  <div className="flex items-center gap-3">
                    {event.status === 'received' ? (
                      <CheckCircle className="size-4 text-green-400" />
                    ) : (
                      <AlertTriangle className="size-4 text-amber-400" />
                    )}
                    <div>
                      <p className="text-sm text-zinc-100">{event.event_type}</p>
                      <p className="text-xs text-fg-muted">Endpoint: {event.endpoint_id}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={event.status === 'received' ? 'success' : 'warning'} size="sm">
                      {event.status}
                    </Badge>
                    {event.duplicate && (
                      <Badge variant="warning" size="sm">duplicate</Badge>
                    )}
                    <span className="text-xs text-fg-muted">
                      {event.payload_size_bytes} bytes
                    </span>
                    <span className="text-xs text-fg-muted">
                      {new Date(event.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
