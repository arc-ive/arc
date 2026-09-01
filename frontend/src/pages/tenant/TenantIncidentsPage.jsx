import { AlertTriangle } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Tenant-scoped incidents — shell.
 *
 * Incident endpoints do not exist yet. The surface below is the planned
 * information architecture; nothing is fabricated and no API is called.
 */
export function TenantIncidentsPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <AlertTriangle className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Incidents
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Operational incidents for this tenant.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Incident tracking is not wired yet"
        description="The backend incident contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          When the contract lands, incidents will show their ID, status,
          severity, trigger, related services, created time, and the ARC
          execution trail: retrieved knowledge, selected skill, tool
          executions, actions taken, human intervention, and resolution.
        </p>
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Incident access is tenant-scoped and authorized by the backend — a
          member of one tenant can never see another tenant&apos;s incidents.
        </p>
        <div className="flex flex-wrap gap-2">
          {['Status', 'Severity', 'Trigger', 'Related knowledge', 'Skill', 'Tool runs', 'Resolution'].map(
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