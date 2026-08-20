import { BarChart3 } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Tenant-scoped usage / observability — shell.
 *
 * No tenant telemetry endpoints exist yet. This page shows the planned
 * metric surface without fabricating data.
 */
export function TenantUsagePage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <BarChart3 className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Usage
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Tenant-scoped metrics for AI and platform usage.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Usage metrics are not wired yet"
        description="The tenant observability contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          This tenant will see its own usage only: API requests, AI requests,
          token usage, agent executions, tool invocations, webhook events,
          successful and failed executions, latency, and error rate.
        </p>
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Usage is tenant-scoped and authorized by the backend; a member of
          one tenant never sees another tenant&apos;s metrics.
        </p>
        <div className="flex flex-wrap gap-2">
          {['API requests', 'AI requests', 'Tokens', 'Agent runs', 'Tool calls', 'Latency', 'Error rate'].map(
            (label) => (
              <Badge key={label} variant="neutral" size="sm">
                {label}
              </Badge>
            ),
          )}
        </div>
      </PendingContract>
    </div>
  )
}