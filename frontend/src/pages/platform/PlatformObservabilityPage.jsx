import { Activity } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Platform Observability — shell.
 *
 * No telemetry endpoints exist yet. Platform-level observability will
 * aggregate tenant-scoped metrics without leaking tenant data.
 */
export function PlatformObservabilityPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Activity className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Observability
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Platform-level telemetry and operational insight.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Observability is not wired yet"
        description="The telemetry contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Platform administrators will see platform-level metrics — API
          requests, AI requests, token usage, agent executions, tool
          invocations, webhook events, successful and failed executions,
          latency, error rate, tenant usage, service health, incidents,
          automated actions, and human escalations.
        </p>
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Tenant users only see their own tenant&apos;s metrics. Sensitive
          data is never exposed unnecessarily, and payloads are never
          rendered raw.
        </p>
        <div className="flex flex-wrap gap-2">
          {[
            'API requests',
            'AI requests',
            'Token usage',
            'Agent executions',
            'Tool invocations',
            'Webhook events',
            'Latency',
            'Error rate',
            'Tenant usage',
            'Service health',
            'Incidents',
            'Escalations',
          ].map((label) => (
            <Badge key={label} variant="neutral" size="sm">
              {label}
            </Badge>
          ))}
        </div>
      </PendingContract>
    </div>
  )
}