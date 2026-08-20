import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ClipboardCheck,
  GitBranch,
  ListChecks,
  Scale,
  Target,
  Wrench,
  Workflow,
} from 'lucide-react'
import { Badge } from '../../components/ui/Badge.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { PendingContract } from '../../components/shell/PendingContract.jsx'

const SKILL_METADATA = [
  {
    icon: Target,
    label: 'Purpose',
    description: 'Why the skill exists and what it achieves.',
  },
  {
    icon: ListChecks,
    label: 'Preconditions',
    description: 'Conditions that must hold before the skill can run.',
  },
  {
    icon: ClipboardCheck,
    label: 'Steps',
    description: 'The structured, ordered steps of the procedure.',
  },
  {
    icon: Wrench,
    label: 'Allowed tools',
    description: 'The exact tools the skill may invoke — never more.',
  },
  {
    icon: Scale,
    label: 'Risk & approval',
    description: 'Risk classification and whether human approval is required.',
  },
  {
    icon: GitBranch,
    label: 'Status, version & provenance',
    description: 'Lifecycle state, version history, and where it came from.',
  },
]

/**
 * Skills Engine — product-facing shell.
 *
 * The Skills domain model, service, repository, and database table exist in
 * the backend, but the HTTP management API and the skill:* permissions have
 * NOT been merged yet. Per the "no invented APIs" rule, this surface is
 * intentionally not wired to any backend call.
 */
export function SkillsPage({ view = 'list' }) {
  const { tenantId } = useParams()
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  const viewCopy = {
    list: {
      title: 'Skills',
      description:
        'Structured, reusable workflows that convert company procedures into capabilities Unified Intelligence can apply.',
    },
    new: {
      title: 'New skill',
      description: 'Author a new skill definition for this tenant.',
    },
    detail: {
      title: 'Skill details',
      description: 'Inspect a skill definition for this tenant.',
    },
  }[view]

  return (
    <div className="flex flex-col gap-6">
      <section>
        {view !== 'list' && (
          <Link
            to={`${tenantPrefix}/skills`}
            className="mb-4 inline-flex items-center gap-1.5 rounded text-[13px] text-zinc-500 transition-colors duration-150 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            <ArrowLeft className="size-3.5" />
            Back to Skills
          </Link>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Workflow className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              {viewCopy.title}
            </h1>
            <p className="mt-1 text-sm text-zinc-500">{viewCopy.description}</p>
          </div>
        </div>
      </section>

      <PendingContract
        title="Skills are not wired yet"
        description="The backend management API for Skills has not been implemented."
      >
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          The Arc backend currently contains the Skills domain model,
          service, and repository, but the HTTP management endpoints (
          <span className="font-mono text-zinc-400">POST /skills</span>,{' '}
          <span className="font-mono text-zinc-400">GET /skills</span>,{' '}
          <span className="font-mono text-zinc-400">
            GET /skills/{'{skill_id}'}
          </span>
          ,{' '}
          <span className="font-mono text-zinc-400">
            DELETE /skills/{'{skill_id}'}
          </span>
          ) and the{' '}
          <span className="font-mono text-zinc-400">skill:*</span>{' '}
          permissions are not merged yet. This surface will be enabled as
          soon as the backend contract exists.
        </p>
        <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
          Skill execution and AI/LLM functionality are separate future
          capabilities and are not part of the management surface.
        </p>
      </PendingContract>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">
          What a skill describes
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SKILL_METADATA.map((item) => (
            <div
              key={item.label}
              className="flex flex-col gap-2.5 rounded-lg border border-zinc-800/70 bg-zinc-900/40 p-4"
            >
              <div className="flex items-center gap-2">
                <item.icon className="size-4 text-zinc-500" />
                <p className="text-[13px] font-semibold text-zinc-100">
                  {item.label}
                </p>
              </div>
              <p className="text-xs leading-relaxed text-zinc-500">
                {item.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {view === 'detail' && (
        <Card>
          <CardHeader
            title="Authorization"
            description="Who can see and use this skill."
          />
          <CardContent>
            <div className="flex flex-col gap-2">
              <Badge variant="neutral" size="sm" className="self-start">
                Employees only see skills they are authorized to access
              </Badge>
              <Badge variant="neutral" size="sm" className="self-start">
                Company administrators manage skills when skill:* permissions
                allow it
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}