import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  BookOpen,
  Building2,
  History,
  Sparkles,
  Workflow,
} from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { relativeTime } from '../../lib/format.js'

function EmployeeCapability({ to, label, description, icon: Icon }) {
  return (
    <Link
      to={to}
      className="group flex flex-col gap-3 rounded-xl border border-zinc-800/80 bg-panel p-5 shadow-card transition-colors duration-150 hover:border-zinc-700 hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
    >
      <div className="flex items-center justify-between">
        <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500 transition-colors duration-150 group-hover:text-indigo-400">
          <Icon className="size-4.5" />
        </div>
        <ArrowUpRight className="size-4 text-zinc-600 transition-colors duration-150 group-hover:text-zinc-300" />
      </div>
      <div>
        <p className="text-sm font-semibold text-zinc-100">{label}</p>
        <p className="mt-1 text-[13px] leading-relaxed text-zinc-500">
          {description}
        </p>
      </div>
    </Link>
  )
}

/**
 * Employee workspace home.
 *
 * The employee's primary purpose is Unified Intelligence: ask questions,
 * browse approved company knowledge, and follow approved procedures.
 * Everything is tenant-scoped and backend-authorized.
 */
export function EmployeeHomePage() {
  const { tenantId } = useParams()
  const { principal, isDemo } = useAuth()
  const { role, me } = useCapabilities()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: !isDemo && Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const tenant = userTenants.data?.find((t) => t.id === tenantId)
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  return (
    <div className="flex flex-col gap-8">
      <section>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
            {tenant?.name ?? 'Your company'}
          </h1>
          <Badge variant="indigo" size="sm">
            Employee workspace
          </Badge>
        </div>
        <p className="mt-1 text-sm text-zinc-500">
          Approved company information and assistance — nothing else.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <EmployeeCapability
          to={`${tenantPrefix}/ask`}
          label="Ask Arc"
          description="Ask questions about your company — policies, procedures, and approved information."
          icon={Sparkles}
        />
        <EmployeeCapability
          to={`${tenantPrefix}/knowledge`}
          label="Company Knowledge"
          description="Browse knowledge and policies you are authorized to see."
          icon={BookOpen}
        />
        <EmployeeCapability
          to={`${tenantPrefix}/skills`}
          label="Procedures"
          description="Follow approved procedures as structured, reusable steps."
          icon={Workflow}
        />
        <EmployeeCapability
          to={`${tenantPrefix}/activity`}
          label="My Activity"
          description="Your recent activity in this company workspace."
          icon={History}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Your membership"
            description="The backend decides what you are authorized to access."
          />
          <CardContent>
            {userTenants.isPending ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-16 w-full" />
              </div>
            ) : userTenants.isError ? (
              <ErrorState
                title="Could not load your tenants"
                message={errorMessage(userTenants.error)}
                onRetry={() => userTenants.refetch()}
                compact
              />
            ) : tenant ? (
              <div className="flex items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3.5 py-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-zinc-800 bg-zinc-900/60 text-zinc-500">
                  <Building2 className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-zinc-200">
                    {tenant.name}
                  </p>
                  <p className="truncate font-mono text-[11px] text-zinc-600">
                    {tenant.id}
                  </p>
                </div>
                <Badge variant="green" size="sm" dot>
                  {tenant.status}
                </Badge>
              </div>
            ) : (
              <p className="text-[13px] text-zinc-500">
                Tenant membership not found.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title="Session"
            description="Identity derived from your session token."
          />
          <CardContent>
            <dl className="space-y-2.5">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-[13px] text-zinc-500">User ID</dt>
                <dd className="truncate font-mono text-xs text-zinc-300">
                  {principal?.sub}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-[13px] text-zinc-500">Application role</dt>
                <dd className="font-mono text-xs text-zinc-300">
                  {role ?? (me.data?.is_demo ? 'demo' : '—')}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-[13px] text-zinc-500">Expires</dt>
                <dd className="font-mono text-xs text-zinc-300">
                  {principal?.exp
                    ? relativeTime(principal.exp)
                    : 'No expiry claim'}
                </dd>
              </div>
            </dl>
            <div className="mt-4 flex">
              <Link
                to="/app/profile"
                className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-indigo-400 transition-colors duration-150 hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
              >
                View profile and session details
                <ArrowUpRight className="size-3.5" />
              </Link>
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  )
}