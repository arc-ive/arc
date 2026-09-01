import { Gauge } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

const PIPELINE = [
  'Health',
  'Events',
  'Incidents',
  'Unified Intelligence',
  'Skills',
  'Tools',
  'Action',
  'Verification',
  'Escalation',
]

/**
 * Tenant operational workspace — shell.
 *
 * Operations users monitor company/service operations and handle
 * incidents. None of those backend contracts exist yet, so this surface
 * is intentionally not wired to any API. The pipeline below is the
 * product architecture Arc will render.
 */
export function TenantOperationsPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Gauge className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Operations
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Operational visibility and response for this tenant.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Operational telemetry is not wired yet"
        description="The backend contracts for health, incidents, and tool execution have not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          The operational workspace will connect health signals, events, and
          incidents to Unified Intelligence, skills, and permitted tools —
          with visible action status, verification, and human escalation when
          a recovery fails.
        </p>
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          In the meantime, operations users can browse the tenant&apos;s
          Company Brain (read access is granted by the{' '}
          <span className="font-mono text-zinc-400">knowledge:read</span>{' '}
          permission) and review the tenant&apos;s members.
        </p>
      </PendingContract>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">
          Operational pipeline
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {PIPELINE.map((step, index) => (
            <div key={step} className="flex items-center gap-2">
              <Badge
                variant={index === 0 ? 'cyan' : 'neutral'}
                size="sm"
                className="px-2.5 py-1"
              >
                {step}
              </Badge>
              {index < PIPELINE.length - 1 && (
                <span className="text-zinc-700" aria-hidden>
                  →
                </span>
              )}
            </div>
          ))}
        </div>
        <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          This is the architecture Arc will render: a degraded service raises
          an event, becomes an incident, selects a recovery skill, executes
          permitted tools with visible status, verifies the outcome, and
          escalates to a human when recovery fails.
        </p>
      </section>
    </div>
  )
}