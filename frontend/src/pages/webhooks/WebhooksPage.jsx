import { useQuery } from '@tanstack/react-query'
import { useTenant } from '../../tenant/useTenant.js'
import { queryKeys } from '../../api/queryKeys.js'
import { listWebhookEvents } from '../../api/endpoints/webhooks.js'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'
import { deliveryStage, retryState, payloadSize } from '../../lib/webhookEvents.js'
import { runFailureReason } from '../../lib/agentRuns.js'
import { relativeTime } from '../../lib/format.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { cn } from '../../lib/cn.js'

const TONE_TEXT = {
  success: 'text-success',
  danger: 'text-danger',
  neutral: 'text-fg-muted',
}

/**
 * Inbound webhook events, as a delivery ledger.
 *
 * The task here is not configuration — Arc has no UI for creating
 * endpoints, and this page never did. It is "did the things other systems
 * sent us actually land?". So the composition is a ledger with the
 * failures lifted out of it: what needs a person first, the stream
 * underneath.
 *
 * The previous version showed a green tick for `received` and a warning
 * for everything else, which inverted the meaning — see
 * lib/webhookEvents.js.
 */
export function WebhooksPage() {
  const { tenantId } = useTenant()
  useDocumentTitle('Webhooks')

  const eventsQuery = useQuery({
    queryKey: queryKeys.webhookEvents(tenantId),
    queryFn: () => listWebhookEvents(tenantId),
    enabled: Boolean(tenantId),
  })

  const events = eventsQuery.data ?? []
  const isLoading = isQueryLoading(eventsQuery)
  // Issue #225: a failed-and-parked query is a failure, not loading.
  const failed = isQueryFailed(eventsQuery)
  const error = eventsQuery.error

  const failures = events.filter((e) => e.status === 'failed')
  const inFlight = events.filter((e) => e.status === 'received')

  return (
    <div className="flex flex-col">
      <header className="min-w-0">
        <h1 className="type-display-lg text-fg">Webhooks</h1>
        {!isLoading && events.length > 0 && (
          <p className="mt-2 text-[14px] text-fg-muted">
            {events.length} {events.length === 1 ? 'event' : 'events'} received
            {failures.length > 0 && (
              <>
                {' · '}
                <span className="font-medium text-danger">
                  {failures.length} failed
                </span>
              </>
            )}
            {inFlight.length > 0 && ` · ${inFlight.length} in flight`}
          </p>
        )}
      </header>

      {isLoading && (
        <div className="mt-8 flex flex-col gap-4 border-t border-line pt-6">
          <Skeleton className="h-5 w-72" />
          <Skeleton className="h-5 w-60" />
          <Skeleton className="h-5 w-64" />
        </div>
      )}

      {failed && (
        <div className="mt-8">
          <ErrorState
            error={error}
            message={error ? undefined : STALLED_MESSAGE}
            onRetry={() => eventsQuery.refetch()}
          />
        </div>
      )}

      {!isLoading && !failed && events.length === 0 && (
        <div className="measure mt-8 border-t border-line pt-6">
          <p className="type-prose text-fg-subtle">
            Nothing has been sent to this workspace yet.
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-fg-muted">
            When a connected system posts an event to Arc, it lands here with
            whether it was processed, and what happened if it was not. Arc
            receives webhooks; it does not send them.
          </p>
        </div>
      )}

      {!isLoading && !failed && events.length > 0 && (
        <>
          {/* Failures are lifted out of the stream. In a ledger of a
              hundred rows the four that need a person should not have to
              be hunted for. */}
          {failures.length > 0 && (
            <section className="mt-10">
              <h2 className="type-label text-danger">Needs attention</h2>
              <ul className="mt-3 border-t border-line">
                {failures.map((event) => {
                  const retry = retryState(event)
                  return (
                    <li key={event.id} className="border-b border-line py-4">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
                        <p className="type-data text-[14px] text-fg">
                          {event.event_type}
                        </p>
                        <p className="text-[12.5px] text-fg-muted">
                          {relativeTime(event.created_at)}
                        </p>
                      </div>
                      <p className="measure mt-1 text-[13.5px] leading-relaxed text-fg-subtle">
                        {runFailureReason(event.error_kind) ??
                          'Arc could not process this event.'}
                      </p>
                      {retry && (
                        <p
                          className={cn(
                            'mt-1 text-[12.5px]',
                            retry.exhausted ? 'text-danger' : 'text-fg-muted',
                          )}
                        >
                          {retry.text}
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          <section className="mt-12">
            <h2 className="type-label text-fg-muted">All events</h2>
            {/* A ledger, so it is a table: one row per event, columns
                aligned, scannable down a single attribute. Deliberately
                not animated — these are rows an operator compares. */}
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-y border-line">
                    <th className="type-label py-2.5 pr-6 text-left text-fg-muted">
                      Event
                    </th>
                    <th className="type-label py-2.5 pr-6 text-left text-fg-muted">
                      From
                    </th>
                    <th className="type-label py-2.5 pr-6 text-left text-fg-muted">
                      State
                    </th>
                    <th className="type-label py-2.5 pr-6 text-right text-fg-muted">
                      Size
                    </th>
                    <th className="type-label py-2.5 text-right text-fg-muted">
                      Received
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => {
                    const stage = deliveryStage(event)
                    return (
                      <tr key={event.id} className="border-b border-line">
                        <td className="whitespace-nowrap py-3 pr-6">
                          <span className="type-data text-fg">
                            {event.event_type}
                          </span>
                        </td>
                        <td className="whitespace-nowrap py-3 pr-6">
                          <span className="type-data text-fg-muted">
                            {event.endpoint_id}
                          </span>
                        </td>
                        <td className="whitespace-nowrap py-3 pr-6">
                          <span
                            className={cn(
                              'text-[13px] font-medium',
                              TONE_TEXT[stage.tone] ?? 'text-fg-muted',
                            )}
                          >
                            {stage.label}
                          </span>
                          {event.retry_count > 0 && (
                            <span className="ml-2 text-[12px] text-fg-muted tabular-nums">
                              ×{event.retry_count + 1}
                            </span>
                          )}
                        </td>
                        <td className="py-3 pr-6 text-right text-[13px] tabular-nums text-fg-muted">
                          {payloadSize(event.payload_size_bytes) ?? '—'}
                        </td>
                        <td className="whitespace-nowrap py-3 text-right text-[13px] text-fg-muted">
                          {relativeTime(event.created_at)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <p className="measure mt-6 text-[12.5px] leading-relaxed text-fg-muted">
            Arc receives webhooks from connected systems. Endpoints are
            registered outside this workspace, so they cannot be added or
            removed here.
          </p>
        </>
      )}
    </div>
  )
}
