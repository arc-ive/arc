import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  BookOpen,
  Building2,
  Users,
  Workflow,
  Sparkles,
  Wrench,
  Plug,
  Activity,
  ShieldCheck,
} from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { getKnowledge } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { formatDate } from '../../lib/format.js'

const ROLE_LABELS = {
  platform_administrator: 'Platform Administrator',
  company_administrator: 'Company Administrator',
  operations_user: 'Operations User',
  employee: 'Employee',
}

function StatCard({ label, value, hint, to, icon: Icon }) {
  return (
    <Card className="flex flex-col justify-between gap-6 p-5">
      <div>
        <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-fg-muted">
          <Icon className="size-4.5" />
        </div>
        <div className="mt-4 text-2xl font-semibold tracking-tight text-zinc-100">
          {value}
        </div>
        <p className="mt-0.5 text-[13px] text-fg-muted">{label}</p>
      </div>
      {to ? (
        <Link
          to={to}
          className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-indigo-400 transition-colors duration-150 hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          {hint}
          <ArrowUpRight className="size-3.5" />
        </Link>
      ) : (
        <span className="text-[13px] text-fg-muted">{hint}</span>
      )}
    </Card>
  )
}

function ModuleLink({ to, label, description, icon: Icon }) {
  return (
    <Link
      to={to}
      className="group flex items-start gap-3.5 rounded-xl border border-zinc-800/70 bg-panel p-5 shadow-card transition-colors duration-150 hover:border-zinc-700 hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-fg-muted transition-colors duration-150 group-hover:text-indigo-400">
        <Icon className="size-4.5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-zinc-100">{label}</p>
        <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>
      </div>
      <ArrowUpRight className="ml-auto mt-1 size-4 shrink-0 text-fg-muted transition-colors duration-150 group-hover:text-zinc-300" />
    </Link>
  )
}

export function TenantOverviewPage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { role } = useCapabilities()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const users = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId),
  })

  const knowledge = useQuery({
    queryKey: queryKeys.knowledge(tenantId),
    queryFn: () => getKnowledge(tenantId),
    enabled: Boolean(tenantId),
    staleTime: 30 * 1000,
  })

  const tenant = userTenants.data?.find((t) => t.id === tenantId)
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  return (
    <div className="flex flex-col gap-8">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Building2 className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <PageHeader title={tenant?.name ?? 'Tenant'} />
              <Badge
                variant={tenant?.status === 'active' ? 'success' : 'neutral'}
                dot
              >
                {tenant?.status ?? 'unknown'}
              </Badge>
            </div>
            <p className="mt-0.5 font-mono text-xs text-fg-muted">{tenantId}</p>
          </div>
          {role && (
            <Badge variant="accent" className="self-start">
              {ROLE_LABELS[role] ?? role} workspace
            </Badge>
          )}
        </div>
      </section>

      {(userTenants.isError || users.isError || knowledge.isError) && role !== 'employee' && (
        <Card>
          <ErrorState
            title="Could not load the workspace"
            message="One or more services did not respond. The backend enforces access on every request."
            onRetry={() => {
              userTenants.refetch()
              users.refetch()
              knowledge.refetch()
            }}
          />
        </Card>
      )}

      {role !== 'employee' && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Knowledge documents"
            value={
              knowledge.isPending ? (
                <Skeleton className="h-7 w-10" />
              ) : (
                knowledge.data?.length ?? 0
              )
            }
            hint="Open Company Brain"
            to={`${tenantPrefix}/knowledge`}
            icon={BookOpen}
          />
          <StatCard
            label="Members"
            value={
              users.isPending ? (
                <Skeleton className="h-7 w-10" />
              ) : (
                users.data?.length ?? 0
              )
            }
            hint="View members"
            to={`${tenantPrefix}/users`}
            icon={Users}
          />
          <StatCard
            label="Status"
            value={tenant?.status ?? '—'}
            hint="Provisioned on the platform"
            icon={Activity}
          />
          <StatCard
            label="Created"
            value={
              tenant?.created_at ? (
                <span className="text-lg">{formatDate(tenant.created_at)}</span>
              ) : (
                '—'
              )
            }
            hint="Tenant workspace"
            icon={Building2}
          />
        </section>
      )}

      {role === 'employee' && (
        <section>
          <Card>
            <div className="flex items-start gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-fg-muted">
                <Building2 className="size-4.5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-zinc-100">
                  {tenant?.name ?? 'Tenant'}
                </p>
                <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
                  You are signed in as an employee of this workspace.
                  Use Ask Arc to search approved company information.
                </p>
              </div>
            </div>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-200">
          Workspace
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <ModuleLink
            to={`${tenantPrefix}/ask`}
            label="Ask Arc"
            description="Ask questions grounded in the Company Brain."
            icon={Sparkles}
          />
          {role !== 'employee' && (
            <>
              <ModuleLink
                to={`${tenantPrefix}/knowledge`}
                label="Company Brain"
                description="Knowledge, policies, procedures, and solutions."
                icon={BookOpen}
              />
              <ModuleLink
                to={`${tenantPrefix}/skills`}
                label="Skills"
                description="Structured, reusable workflows for this tenant."
                icon={Workflow}
              />
              <ModuleLink
                to={`${tenantPrefix}/tools`}
                label="Tools"
                description="Platform-owned AI tools available for execution."
                icon={Wrench}
              />
              <ModuleLink
                to={`${tenantPrefix}/connectors`}
                label="Connectors"
                description="External integrations — GitHub, Slack, Linear."
                icon={Plug}
              />
              <ModuleLink
                to={`${tenantPrefix}/approvals`}
                label="Approvals"
                description="Human-in-the-loop approval requests."
                icon={ShieldCheck}
              />
              <ModuleLink
                to={`${tenantPrefix}/observability`}
                label="Observability"
                description="Usage metrics and operational telemetry."
                icon={Activity}
              />
              <ModuleLink
                to={`${tenantPrefix}/users`}
                label="Users"
                description="Tenant members and access."
                icon={Users}
              />
            </>
          )}
        </div>
      </section>
    </div>
  )
}