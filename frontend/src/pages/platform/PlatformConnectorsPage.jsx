import { Link } from 'react-router-dom'
import { Plug, ShieldCheck } from 'lucide-react'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'

const PROVIDERS = [
  {
    id: 'github',
    name: 'GitHub',
    scope: 'Repositories and documentation as company knowledge; operational workflows.',
    committed: true,
  },
  {
    id: 'slack',
    name: 'Slack',
    scope: 'Channels and messages for operational workflows and knowledge.',
    committed: true,
  },
  {
    id: 'linear',
    name: 'Linear',
    scope: 'Issues and projects for operational workflows.',
    committed: true,
  },
  {
    id: 'google_drive',
    name: 'Google Drive',
    scope: 'Document knowledge — conditional only, pending the ADR-002 selection criteria.',
    committed: false,
  },
]

/**
 * Platform Connectors — shell.
 *
 * ADR-002 commits Arc to GitHub, Slack, and Linear (Google Drive is a
 * conditional fourth). The backend contains the tenant-aware connector
 * foundation (ConnectorProvider, ConnectorService, PostgreSQL repository),
 * but no connector HTTP API exists yet, so no connector is wired.
 */
export function PlatformConnectorsPage() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
          Connectors
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          External integrations per the approved connector architecture
          (ADR-002).
        </p>
      </section>

      <Card>
        <CardHeader
          title="Not yet available"
          description="The connector management API has not been implemented."
        />
        <CardContent>
          <div className="flex flex-col gap-4">
            <div>
              <Badge variant="amber" dot>
                Backend contract pending
              </Badge>
            </div>
            <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
              The backend foundation exists —{' '}
              <span className="font-mono text-zinc-400">ConnectorProvider</span>,{' '}
              <span className="font-mono text-zinc-400">ConnectorService</span>{' '}
              (trusted tenant context only), and a tenant-scoped repository —
              but there are no connector endpoints yet. No OAuth flow is
              implemented; nothing is wired.
            </p>
            <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
              When the contract lands, connectors will be tenant-scoped
              integrations showing provider, connection state, last sync,
              and authorized actions — with tenant isolation enforced by the
              backend.
            </p>
          </div>
        </CardContent>
      </Card>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">
          Providers
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {PROVIDERS.map((provider) => (
            <Card
              key={provider.id}
              className="flex flex-col gap-3 p-5"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-zinc-100">
                  {provider.name}
                </p>
                <Badge
                  variant={provider.committed ? 'indigo' : 'neutral'}
                  size="sm"
                >
                  {provider.committed ? 'Committed (ADR-002)' : 'Conditional'}
                </Badge>
              </div>
              <p className="text-[13px] leading-relaxed text-zinc-500">
                {provider.scope}
              </p>
              <div className="mt-auto flex items-center gap-2 pt-1">
                <Badge variant="neutral" size="sm" dot>
                  Not connected
                </Badge>
              </div>
            </Card>
          ))}
        </div>
        <div className="mt-6 flex flex-col items-start gap-2">
          <EmptyState
            icon={Plug}
            title="No connector connections"
            description="Connector endpoints do not exist yet — this surface will be wired when the backend contract lands."
            compact
          />
          <Link
            to="/platform/observability"
            className="inline-flex items-center gap-1.5 rounded text-[13px] font-medium text-indigo-400 transition-colors duration-150 hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            <ShieldCheck className="size-3.5" />
            Connector events will appear in Observability
          </Link>
        </div>
      </section>
    </div>
  )
}