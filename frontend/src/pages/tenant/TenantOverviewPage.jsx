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
import { cn } from '../../lib/cn.js'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { formatDate } from '../../lib/format.js'

const ROLE_LABELS = {
  platform_administrator: 'Platform Administrator',
  company_administrator: 'Company Administrator',
  operations_user: 'Operations User',
  employee: 'Employee',
}

function StatCard({ label, value, hint, to }) {
  const body = (
    <>
      <p className="type-label text-fg-muted">{label}</p>
      <p className="mt-2 text-[1.75rem] font-medium leading-none tabular-nums text-fg">
        {value}
      </p>
      {hint && <p className="mt-2 text-[12.5px] text-fg-muted">{hint}</p>}
    </>
  )

  if (!to) return <div className="min-w-0">{body}</div>

  return (
    <Link
      to={to}
      className={cn(
        'group min-w-0',
        'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary',
      )}
    >
      {body}
      <span className="mt-2 inline-flex items-center gap-1 text-[12.5px] text-accent">
        Open
        <ArrowUpRight className="size-3 transition-transform duration-150 group-hover:-translate-y-0.5" />
      </span>
    </Link>
  )
}

function ModuleLink({ to, label, description }) {
  return (
    <Link
      to={to}
      className={cn(
        'group flex items-baseline justify-between gap-6 border-b border-line py-4',
        'transition-colors duration-150 hover:bg-surface-sunk/60',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
      )}
    >
      <span className="min-w-0">
        <span className="type-display block text-[1.25rem] leading-snug text-fg">
          {label}
        </span>
        <span className="measure mt-0.5 block text-[13.5px] leading-relaxed text-fg-muted">
          {description}
        </span>
      </span>
      <ArrowUpRight className="size-4 shrink-0 text-fg-muted transition-transform duration-150 group-hover:-translate-y-0.5 group-hover:text-fg" />
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
      <PageHeader
        title={tenant?.name ?? 'Workspace'}
        meta={
          <Badge
            variant={tenant?.status === 'active' ? 'success' : 'neutral'}
            dot
          >
            {tenant?.status ?? 'unknown'}
          </Badge>
        }
        description={
          role ? `You are in this workspace as a ${(ROLE_LABELS[role] ?? role).toLowerCase()}.` : undefined
        }
        actions={<span className="type-data text-fg-muted">{tenantId}</span>}
      />

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
        <section className="grid gap-x-10 gap-y-8 border-b border-line pb-8 sm:grid-cols-2 lg:grid-cols-4">
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
              <div className="flex shrink-0 items-center text-fg-muted">
                <Building2 className="size-4.5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-fg">
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
        <h2 className="type-label text-fg-muted">In this workspace</h2>
        <div className="mt-3 grid border-t border-line sm:grid-cols-2 sm:gap-x-12">
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