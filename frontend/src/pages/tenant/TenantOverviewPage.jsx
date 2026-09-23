import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { PERMISSIONS } from '../../auth/permissions.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { getKnowledge } from '../../api/endpoints/knowledge.js'
import { listApprovals } from '../../api/endpoints/approvals.js'
import { listAgentRuns } from '../../api/endpoints/agent.js'
import { queryKeys } from '../../api/queryKeys.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { documentTitle } from '../../lib/knowledge.js'
import { runFailureReason } from '../../lib/agentRuns.js'
import { relativeTime } from '../../lib/format.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { cn } from '../../lib/cn.js'

/**
 * The workspace home.
 *
 * This page used to be a sitemap. Below a row of database fields it listed
 * eight destinations — Ask Arc, Company Brain, Skills, Tools, Connectors,
 * Approvals, Observability, Users — each with a title, a description and an
 * arrow. The masthead already offers every one of them. Navigation answers
 * "where can I go"; a home page has to answer "what needs me", and it was
 * answering the first question twice.
 *
 * What it shows now is what is actually true of the workspace right now:
 * decisions waiting on a person, runs that stopped, and what has recently
 * changed in the Company Brain. Nothing is invented — every line is a
 * record the API returned, and a section that has no records does not
 * render at all rather than showing a decorative empty state.
 *
 * `status` and `created` are gone. Status already sits beside the name as a
 * badge; a provisioning date is a database field, not a signal.
 */
export function TenantOverviewPage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { can, isEmployee } = useCapabilities()

  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })
  const tenant = userTenants.data?.find((t) => t.id === tenantId)

  useDocumentTitle(tenant?.name)

  const users = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId) && can(PERMISSIONS.TENANT_READ),
  })
  const knowledge = useQuery({
    queryKey: queryKeys.knowledge(tenantId),
    queryFn: () => getKnowledge(tenantId),
    enabled: Boolean(tenantId) && can(PERMISSIONS.KNOWLEDGE_READ),
  })
  const approvals = useQuery({
    queryKey: queryKeys.approvals(tenantId),
    queryFn: () => listApprovals(tenantId),
    enabled: Boolean(tenantId) && can(PERMISSIONS.APPROVAL_READ),
  })
  const runs = useQuery({
    queryKey: queryKeys.agentRuns(tenantId, 5),
    queryFn: () => listAgentRuns(tenantId, { limit: 5 }),
    enabled: Boolean(tenantId) && can(PERMISSIONS.AGENT_EXECUTE),
  })

  const documents = asList(knowledge.data)
  const members = asList(users.data)
  const pending = asList(approvals.data).filter((a) => a.status === 'pending')
  const stopped = asList(runs.data).filter((r) => r.error_kind)

  const recentDocuments = [...documents]
    .sort((a, b) => new Date(b.updated_at ?? 0) - new Date(a.updated_at ?? 0))
    .slice(0, 4)

  const attention = [
    pending.length > 0 && {
      key: 'approvals',
      count: pending.length,
      label: pending.length === 1 ? 'decision waiting' : 'decisions waiting',
      detail: pending[0].tool_name
        ? `${humanise(pending[0].tool_name)}${pending.length > 1 ? ` and ${pending.length - 1} more` : ''}`
        : null,
      to: `${tenantPrefix}/approvals`,
      tone: 'warning',
    },
    stopped.length > 0 && {
      key: 'runs',
      count: stopped.length,
      label: stopped.length === 1 ? 'agent run stopped' : 'agent runs stopped',
      detail: runFailureReason(stopped[0].error_kind),
      to: `${tenantPrefix}/agents`,
      tone: 'danger',
    },
  ].filter(Boolean)

  return (
    <div className="flex flex-col">
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <h1 className="type-display-lg min-w-0 text-fg">
          {tenant?.name ?? <Skeleton className="h-10 w-72" />}
        </h1>
        {tenant?.status && (
          <Badge variant={tenant.status === 'active' ? 'success' : 'neutral'} dot>
            {tenant.status}
          </Badge>
        )}
      </header>

      {/* One bordered block of figures rather than four cards. The cell
          divisions carry the grouping, so no card has to. */}
      <dl className="mt-8 grid grid-cols-2 border-y border-line sm:grid-cols-4">
        <Figure
          label="People"
          value={users.isPending ? null : members.length}
          to={can(PERMISSIONS.TENANT_READ) ? `${tenantPrefix}/users` : null}
        />
        <Figure
          label="Documents"
          value={knowledge.isPending ? null : documents.length}
          to={can(PERMISSIONS.KNOWLEDGE_READ) ? `${tenantPrefix}/knowledge` : null}
        />
        {can(PERMISSIONS.APPROVAL_READ) && (
          <Figure
            label="Awaiting decision"
            value={approvals.isPending ? null : pending.length}
            to={`${tenantPrefix}/approvals`}
            emphasis={pending.length > 0}
          />
        )}
        {can(PERMISSIONS.AGENT_EXECUTE) && (
          <Figure
            label="Agent runs"
            value={runs.isPending ? null : asList(runs.data).length}
            to={`${tenantPrefix}/agents`}
          />
        )}
      </dl>

      <div className="mt-14 grid gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          {attention.length > 0 ? (
            <section>
              <h2 className="type-label text-fg-muted">Needs a person</h2>
              <ul className="mt-3 border-t border-line">
                {attention.map((item) => (
                  <li key={item.key}>
                    <Link
                      to={item.to}
                      className={cn(
                        'group flex items-baseline gap-5 border-b border-line py-5',
                        'transition-colors duration-150 hover:bg-surface-sunk/70',
                        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
                      )}
                    >
                      <span
                        className={cn(
                          'type-display shrink-0 text-[2rem] leading-none tabular-nums',
                          item.tone === 'danger' ? 'text-danger' : 'text-warning',
                        )}
                      >
                        {item.count}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[15px] font-medium text-fg">
                          {item.label}
                        </span>
                        {item.detail && (
                          <span className="measure mt-0.5 block text-[13.5px] leading-relaxed text-fg-muted">
                            {item.detail}
                          </span>
                        )}
                      </span>
                      <ArrowRight className="size-4 shrink-0 self-center text-fg-muted transition-transform duration-200 group-hover:translate-x-1 group-hover:text-fg" />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            !approvals.isPending && (
              <p className="type-prose measure text-fg-subtle">
                Nothing is waiting on a person right now.
              </p>
            )
          )}

          {can(PERMISSIONS.KNOWLEDGE_READ) && (
            <section className="mt-14">
              <h2 className="type-label text-fg-muted">Recently in Company Brain</h2>
              {knowledge.isPending ? (
                <div className="mt-3 flex flex-col gap-3 border-t border-line pt-4">
                  <Skeleton className="h-5 w-72" />
                  <Skeleton className="h-5 w-56" />
                </div>
              ) : recentDocuments.length === 0 ? (
                <p className="mt-3 border-t border-line pt-4 text-[14px] text-fg-muted">
                  No documents yet.{' '}
                  {can(PERMISSIONS.KNOWLEDGE_CREATE) && (
                    <Link
                      to={`${tenantPrefix}/knowledge/new`}
                      className="text-accent underline underline-offset-2"
                    >
                      Add the first one
                    </Link>
                  )}
                </p>
              ) : (
                <ol className="mt-3 border-t border-line">
                  {recentDocuments.map((doc, index) => (
                    <li key={doc.id}>
                      <Link
                        to={`${tenantPrefix}/knowledge/${encodeURIComponent(doc.id)}`}
                        className={cn(
                          'group flex items-baseline gap-5 border-b border-line py-3.5',
                          'transition-colors duration-150 hover:bg-surface-sunk/70',
                          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
                        )}
                      >
                        <span className="type-data shrink-0 text-fg-muted">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[15px] text-fg-subtle group-hover:text-fg">
                          {documentTitle(doc)}
                        </span>
                        {doc.updated_at && (
                          <span className="shrink-0 text-[12.5px] text-fg-muted">
                            {relativeTime(doc.updated_at)}
                          </span>
                        )}
                      </Link>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
        </div>

        {/* One action, in the margin. Ask Arc is the thing a person most
            often came here to do, and it is the only destination this page
            repeats — because it is an action, not a route listing. */}
        <aside className="min-w-0">
          {can(PERMISSIONS.KNOWLEDGE_READ) && (
            <Link
              to={`${tenantPrefix}/ask`}
              className={cn(
                'group block border-t border-fg pt-5',
                'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary',
              )}
            >
              <span className="type-display block text-[1.5rem] leading-tight text-fg">
                Ask Arc
              </span>
              <span className="measure-tight mt-1.5 block text-[13.5px] leading-relaxed text-fg-muted">
                Answers drawn from this workspace&apos;s own knowledge, with the
                documents they came from.
              </span>
              <span className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-accent">
                Ask a question
                <ArrowRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-1" />
              </span>
            </Link>
          )}

          {isEmployee && (
            <p className="measure-tight mt-8 text-[13.5px] leading-relaxed text-fg-muted">
              You are a member of this workspace. Ask Arc searches the
              knowledge you are allowed to see.
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}

/** A cell in the figures block. */
function Figure({ label, value, to, emphasis = false }) {
  const body = (
    <>
      <dt className="type-label text-fg-muted">{label}</dt>
      <dd
        className={cn(
          'mt-2 text-[1.75rem] font-medium leading-none tabular-nums',
          emphasis ? 'text-warning' : 'text-fg',
        )}
      >
        {value === null || value === undefined ? (
          <Skeleton className="h-7 w-10" />
        ) : (
          value
        )}
      </dd>
    </>
  )

  const shared = 'border-line px-5 py-5 [&:not(:nth-child(-n+2))]:border-t sm:[&:not(:first-child)]:border-l sm:[&]:border-t-0 [&:nth-child(odd)]:border-r sm:[&:nth-child(odd)]:border-r-0'

  if (!to) return <div className={shared}>{body}</div>
  return (
    <Link
      to={to}
      className={cn(
        shared,
        'block transition-colors duration-150 hover:bg-surface-sunk/70',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
      )}
    >
      {body}
    </Link>
  )
}

function asList(data) {
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.items)) return data.items
  return []
}

/** `grant_temporary_access` reads as an action, not a registry key. */
function humanise(value) {
  const words = String(value ?? '').replace(/[_-]+/g, ' ').trim()
  if (!words) return null
  return words.charAt(0).toUpperCase() + words.slice(1)
}
