import { Settings } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Tenant settings — shell.
 *
 * No tenant configuration contract exists yet. Shows the planned surface.
 */
export function TenantSettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Settings className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Settings
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Tenant configuration and preferences.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Tenant configuration is not wired yet"
        description="The tenant settings contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Settings will cover tenant-scoped configuration: company profile,
          knowledge defaults, incident routing, tool approvals, and
          observability preferences. Changes will be authorized by the
          backend — only permitted roles can modify tenant configuration.
        </p>
        <div className="flex flex-wrap gap-2">
          {['Company profile', 'Knowledge defaults', 'Incident routing', 'Tool approvals', 'Notifications'].map(
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