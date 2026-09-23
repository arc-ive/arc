import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Building2, ExternalLink } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { formatDate } from '../../lib/format.js'

/**
 * Platform-level tenant detail.
 *
 * Tenant data is only readable through the tenant-scoped API, which
 * requires a trusted membership and the tenant:read permission. A platform
 * administrator without membership receives a 403 from the backend, which
 * is rendered truthfully here — platform administration does not
 * automatically grant tenant data access.
 */
export function PlatformTenantDetailPage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 30 * 1000,
  })

  const members = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId),
  })

  const tenant = userTenants.data?.find((t) => t.id === tenantId)

  return (
    <div className="flex flex-col gap-8">
      <section>
        <Link
          to="/platform/tenants"
          className="mb-4 inline-flex items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowUpRight className="size-3.5 rotate-180" />
          Back to Tenants
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl border border-line bg-surface-raised text-fg-muted">
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
          {tenant && (
            <Link
              to={`/app/t/${encodeURIComponent(tenant.id)}/overview`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface-raised px-3 py-1.5 text-[13px] font-medium text-fg-subtle transition-colors duration-150 hover:border-line-strong hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
            >
              <ExternalLink className="size-3.5" />
              Open workspace
            </Link>
          )}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <p className="text-[13px] text-fg-muted">Created</p>
            <p className="mt-1 text-lg font-semibold text-fg">
              {formatDate(tenant?.created_at)}
            </p>
          </div>
          <span className="text-[13px] text-fg-muted">
            Provisioned on the platform
          </span>
        </Card>
        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <p className="text-[13px] text-fg-muted">Updated</p>
            <p className="mt-1 text-lg font-semibold text-fg">
              {formatDate(tenant?.updated_at)}
            </p>
          </div>
          <span className="text-[13px] text-fg-muted">Tenant record</span>
        </Card>
        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <p className="text-[13px] text-fg-muted">Members (visible to you)</p>
            <p className="mt-1 text-lg font-semibold text-fg">
              {members.isPending ? '—' : members.data?.length ?? 0}
            </p>
          </div>
          <span className="text-[13px] text-fg-muted">
            Requires workspace membership
          </span>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-fg">Members</h2>
        <Card className="overflow-hidden">
          {members.isPending && (
            <div className="flex flex-col gap-4 p-5">
              {Array.from({ length: 3 }, (_, i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="size-8 rounded-full" />
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Skeleton className="h-3.5 w-1/3" />
                    <Skeleton className="h-3 w-1/4" />
                  </div>
                </div>
              ))}
            </div>
          )}
          {members.isError && (
            <ErrorState
              title="Member listing denied"
              message={errorMessage(members.error)}
              onRetry={() => members.refetch()}
              error={members.error}
            />
          )}
          {!members.isPending &&
            !members.isError &&
            members.data?.length === 0 && (
            <EmptyState
              icon={Building2}
              title="No members visible"
              description="Either this tenant has no users, or your role does not grant access to them."
              compact
            />
          )}
          {members.data?.length > 0 && (
            <div className="divide-y divide-line/60">
              {members.data.map((user) => (
                <div key={user.id} className="flex items-center gap-3 px-5 py-3">
                  <Avatar name={user.email} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-fg">
                      {user.email}
                    </p>
                    <p className="truncate font-mono text-[11px] text-fg-muted">
                      {user.id}
                    </p>
                  </div>
                  <Badge
                    variant={user.status === 'active' ? 'success' : 'neutral'}
                    size="sm"
                    dot
                  >
                    {user.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
        <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-fg-muted">
          Platform administration and customer data access are distinct.
          Reading a customer workspace requires membership of that workspace
          and permission to read it. Administering the platform does not
          grant either.
        </p>
      </section>
    </div>
  )
}