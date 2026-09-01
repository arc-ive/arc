import { History } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Tenant activity — shell.
 *
 * No activity feed contract exists yet.
 */
export function TenantActivityPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <History className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Activity
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Recent activity in this tenant.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="The activity feed is not wired yet"
        description="The activity contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Activity will surface tenant-scoped events the viewer is authorized
          to see — knowledge changes, incident updates, skill usage, agent
          executions, and human approvals — with timestamps and actors.
        </p>
        <div className="flex flex-wrap gap-2">
          {['Knowledge changes', 'Incident updates', 'Skill usage', 'Agent runs', 'Approvals'].map(
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