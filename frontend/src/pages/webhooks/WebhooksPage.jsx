import { useQuery } from '@tanstack/react-query'
import { Webhook, AlertTriangle, CheckCircle } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useTenant } from '../../tenant/useTenant.js'
import { queryKeys } from '../../api/queryKeys.js'
import { listWebhookEvents } from '../../api/endpoints/webhooks.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'

export function WebhooksPage() {
  const { tenantId } = useTenant()
  const { isDemo } = useAuth()

  const { data: events, isLoading, error } = useQuery({
    queryKey: queryKeys.webhookEvents(tenantId),
    queryFn: () => listWebhookEvents(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Webhook className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Webhooks</h1>
            <p className="mt-1 text-sm text-zinc-500">Inbound webhook events for this tenant.</p>
          </div>
        </div>
      </section>

      {isLoading && <Spinner />}
      {error && <ErrorState error={error} />}

      {!isLoading && !error && (!events || events.length === 0) && (
        <EmptyState
          icon={Webhook}
          title="No webhook events"
          description="Webhook events from external integrations will appear here."
        />
      )}

      {!isLoading && !error && events && events.length > 0 && (
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
                      <p className="text-xs text-zinc-500">Endpoint: {event.endpoint_id}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={event.status === 'received' ? 'green' : 'amber'} size="sm">
                      {event.status}
                    </Badge>
                    {event.duplicate && (
                      <Badge variant="amber" size="sm">duplicate</Badge>
                    )}
                    <span className="text-xs text-zinc-600">
                      {event.payload_size_bytes} bytes
                    </span>
                    <span className="text-xs text-zinc-600">
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
