import { Bot } from 'lucide-react'
import { PendingContract } from '../../components/shell/PendingContract.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

/**
 * Platform Agents — shell.
 *
 * The agent runtime (OmniRoute → OpenRouter → configurable LLM) is part of
 * the ARC AI architecture, but no agent management API exists yet.
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
              AI agents operating on tenant data.
            </p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Agent management is not wired yet"
        description="The agent API contract has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Agents execute on tenant data through the ARC runtime —{' '}
          <span className="text-zinc-300">OmniRoute → OpenRouter → configurable
          LLM</span>. The runtime model stays outside this console; agents will
          expose their execution trail (trigger, tenant, knowledge retrieved,
          skill, tools, actions, result, human intervention) to authorized
          viewers.
        </p>
        <div className="flex flex-wrap gap-2">
          {['Trigger', 'Tenant', 'Knowledge', 'Skill', 'Tools', 'Result', 'Escalation'].map(
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