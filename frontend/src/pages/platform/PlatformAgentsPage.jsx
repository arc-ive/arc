import { Bot } from 'lucide-react'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Platform Agents — agent run history.
 *
 * The backend has POST /agent/runs (trigger a run) but no listing endpoint yet.
 * This page shows the agent architecture and available run details when available.
 */
export function PlatformAgentsPage() {
  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Bot className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Agents
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              AI agents operating on tenant data through OmniRoute.
            </p>
          </div>
        </div>
      </section>

      <Card>
        <CardHeader
          title="Agent Runtime"
          description="How agents execute within the ARC platform."
        />
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <Badge variant="indigo" size="sm">Runtime</Badge>
              <span className="text-sm text-zinc-300">
                OmniRoute → OpenRouter → Configurable LLM
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Trigger</p>
                <p className="text-xs text-zinc-500">Agent execution initiation</p>
              </div>
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Tenant</p>
                <p className="text-xs text-zinc-500">Tenant-scoped execution context</p>
              </div>
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Knowledge</p>
                <p className="text-xs text-zinc-500">Retrieved company knowledge</p>
              </div>
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Skill</p>
                <p className="text-xs text-zinc-500">Applied workflow procedure</p>
              </div>
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Tools</p>
                <p className="text-xs text-zinc-500">Authorized tool invocations</p>
              </div>
              <div className="p-3 rounded-lg bg-zinc-900/50">
                <p className="text-sm font-medium text-zinc-100">Result</p>
                <p className="text-xs text-zinc-500">Execution outcome and response</p>
              </div>
            </div>
            <p className="text-[13px] leading-relaxed text-zinc-500">
              Agent run history will be displayed here once the listing endpoint is implemented.
              Each run exposes its trigger, tenant context, retrieved knowledge, applied skill,
              tool invocations, result, and any human escalation — visible only to authorized viewers.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
