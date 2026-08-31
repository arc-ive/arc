import { Plug } from 'lucide-react'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

const PROVIDERS = [
  {
    id: 'github',
    name: 'GitHub',
    scope: 'Repositories and documentation as company knowledge; operational workflows.',
  },
  {
    id: 'slack',
    name: 'Slack',
    scope: 'Channels and messages for operational workflows and knowledge.',
  },
  {
    id: 'linear',
    name: 'Linear',
    scope: 'Issues and projects for operational workflows.',
  },
]

export function PlatformConnectorsPage() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Connectors</h1>
        <p className="mt-1 text-sm text-zinc-500">
          External integrations per the approved connector architecture (ADR-002).
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">Available Providers</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {PROVIDERS.map((provider) => (
            <Card key={provider.id} className="flex flex-col gap-3 p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-zinc-100">{provider.name}</p>
                <Badge variant="indigo" size="sm">ADR-002</Badge>
              </div>
              <p className="text-[13px] leading-relaxed text-zinc-500">{provider.scope}</p>
            </Card>
          ))}
        </div>
      </section>

      <Card>
        <CardHeader
          title="Connector management is tenant-scoped"
          description="Connectors are configured and synchronized inside a specific tenant workspace."
        />
        <CardContent>
          <div className="flex items-start gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500">
              <Plug className="size-4.5" />
            </div>
            <div>
              <p className="text-sm text-zinc-300">
                There is no platform-level connector listing or creation API.
                Each tenant manages its own connector configurations through
                the tenant workspace.
              </p>
              <p className="mt-2 text-[13px] text-zinc-500">
                To configure a connector, open a tenant and navigate to its
                Connectors page. Connector credentials are resolved from
                the runtime environment (CONNECTOR_CREDENTIALS) and are
                never accepted through API requests.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
