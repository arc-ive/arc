import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Building2,
  Sparkles,
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
      className="group flex flex-col gap-3 rounded-xl border border-line/80 bg-panel p-5 shadow-card transition-colors duration-150 hover:border-line-strong hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
    >
      <div className="flex items-center justify-between">
        <div className="flex shrink-0 items-center text-fg-muted transition-colors duration-150 group-hover:text-accent">
          <Icon className="size-4.5" />
        </div>
        <ArrowUpRight className="size-4 text-fg-muted transition-colors duration-150 group-hover:text-fg-subtle" />
      </div>
      <div>
        <p className="text-sm font-semibold text-fg">{label}</p>
        <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
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
  const { principal } = useAuth()
  const { role } = useCapabilities()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const tenant = userTenants.data?.find((t) => t.id === tenantId)
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  return (
    <div className="flex flex-col gap-8">
      <section>
        <div className="flex flex-wrap items-center gap-2">
          <PageHeader title={tenant?.name ?? 'Your company'} />
          <Badge variant="accent" size="sm">
            Employee workspace
          </Badge>
        </div>
        <p className="mt-1 text-sm text-fg-muted">
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
              <div className="flex items-center gap-3 rounded-lg border border-line/70 bg-surface px-3.5 py-3">
                <div className="flex shrink-0 items-center text-fg-muted">
                  <Building2 className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-fg">
                    {tenant.name}
                  </p>
                  <p className="truncate font-mono text-[11px] text-fg-muted">
                    {tenant.id}
                  </p>
                </div>
                <Badge variant="success" size="sm" dot>
                  {tenant.status}
                </Badge>
              </div>
            ) : (
              <p className="text-[13px] text-fg-muted">
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
                <dt className="text-[13px] text-fg-muted">User ID</dt>
                <dd className="truncate font-mono text-xs text-fg-subtle">
                  {principal?.sub}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-[13px] text-fg-muted">Application role</dt>
                <dd className="font-mono text-xs text-fg-subtle">
                  {role ?? '—'}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-[13px] text-fg-muted">Expires</dt>
                <dd className="font-mono text-xs text-fg-subtle">
                  {principal?.exp
                    ? relativeTime(principal.exp)
                    : 'No expiry claim'}
                </dd>
              </div>
            </dl>
            <div className="mt-4 flex">
              <Link
                to="/app/profile"
                className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-accent transition-colors duration-150 hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
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