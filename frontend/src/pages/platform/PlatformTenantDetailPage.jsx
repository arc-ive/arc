import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getPlatformTenants, getUserTenants } from '../../api/endpoints/tenants.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { Section, DataRow } from '../../components/layout/Section.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { formatDate } from '../../lib/format.js'

/**
 * One tenant, seen from the platform.
 *
 * Two corrections over the previous version, both about what is actually
 * readable from here.
 *
 * The record now comes from `/platform/tenants`, which is the endpoint a
 * platform administrator can actually read. It previously came from the
 * signed-in user's OWN tenant list, so for the page's real audience — an
 * administrator who, per V2-ADR-003, is deliberately not a member of any
 * customer workspace — the lookup missed and the page rendered "Tenant",
 * status "unknown", and two blank dates. The same class of mistake as the
 * blank dashboard: a page that looks fine until you are the person it is
 * for.
 *
 * The member list is now requested only when the signed-in user is a
 * member of this workspace. Membership is what grants that read, so for
 * everyone else the request was guaranteed to 403 and the page turned an
 * architectural boundary into what looked like a failure. Stating the
 * boundary is more useful than rendering its error.
 */
export function PlatformTenantDetailPage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()

  const tenants = useQuery({
    queryKey: queryKeys.platformTenants(),
    queryFn: getPlatformTenants,
    staleTime: 30 * 1000,
  })

  const myTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal?.sub),
    staleTime: 30 * 1000,
  })

  const tenant = tenants.data?.find((t) => t.id === tenantId)
  const isMember = Boolean(myTenants.data?.some((t) => t.id === tenantId))

  const members = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId) && isMember,
  })

  useDocumentTitle(tenant?.name ?? 'Tenant')

  return (
    <div className="flex flex-col">
      <Link
        to="/platform/tenants"
        className="inline-flex w-fit items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
      >
        <ArrowLeft className="size-3.5" />
        All tenants
      </Link>

      <header className="mt-6">
        {tenants.isPending ? (
          <Skeleton className="h-11 w-80" />
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="type-display-lg text-fg">
              {tenant?.name ?? 'Unknown tenant'}
            </h1>
            {tenant && (
              <Badge
                variant={tenant.status === 'active' ? 'success' : 'neutral'}
                dot
              >
                {tenant.status}
              </Badge>
            )}
          </div>
        )}
        <p className="mt-2 font-mono text-[12.5px] text-fg-muted">{tenantId}</p>
      </header>

      {tenants.isError && (
        <div className="mt-8">
          <ErrorState
            title="Could not load the tenant register"
            message={errorMessage(tenants.error)}
            onRetry={() => tenants.refetch()}
            error={tenants.error}
          />
        </div>
      )}

      {!tenants.isPending && !tenants.isError && !tenant && (
        <p className="measure mt-8 type-prose text-fg-subtle">
          No tenant with this identifier is registered on the platform. It may
          have been removed, or the link may be wrong.
        </p>
      )}

      {tenant && (
        <>
          <Section title="Record" className="mt-10">
            <dl className="border-t border-line">
              <DataRow label="Industry">
                {tenant.industry || 'Not recorded'}
              </DataRow>
              <DataRow label="Provisioned">{formatDate(tenant.created_at)}</DataRow>
              <DataRow label="Last changed">{formatDate(tenant.updated_at)}</DataRow>
              <DataRow label="Identifier">
                <span className="font-mono text-[13px]">{tenant.id}</span>
              </DataRow>
            </dl>
          </Section>

          <Section
            title="People"
            className="mt-12"
            actions={
              isMember ? (
                <Link
                  to={`/app/t/${encodeURIComponent(tenant.id)}/overview`}
                  className="inline-flex items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
                >
                  Open workspace
                  <ExternalLink className="size-3.5" />
                </Link>
              ) : null
            }
          >
            {!isMember && (
              <p className="measure border-t border-line pt-5 type-prose text-fg-subtle">
                Arc keeps administering the platform separate from reading a
                customer&rsquo;s data. Listing this workspace&rsquo;s people
                requires membership of it, which administering the platform
                does not grant. Provisioning, status and billing are
                administered from here; the people inside are not.
              </p>
            )}

            {isMember && members.isPending && (
              <div className="flex flex-col gap-4 border-t border-line pt-5">
                {Array.from({ length: 3 }, (_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="size-8 rounded-full" />
                    <span className="flex flex-1 flex-col gap-1.5">
                      <Skeleton className="h-3.5 w-1/3" />
                      <Skeleton className="h-3 w-1/4" />
                    </span>
                  </div>
                ))}
              </div>
            )}

            {isMember && members.isError && (
              <ErrorState
                title="Could not load this workspace's people"
                message={errorMessage(members.error)}
                onRetry={() => members.refetch()}
                error={members.error}
              />
            )}

            {isMember && members.data?.length === 0 && (
              <p className="border-t border-line pt-5 text-[14px] text-fg-muted">
                This workspace has no people yet.
              </p>
            )}

            {isMember && members.data?.length > 0 && (
              <ul className="stagger border-t border-line">
                {members.data.map((user) => (
                  <li
                    key={user.id}
                    className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line py-3.5"
                  >
                    <Avatar name={user.username || user.email} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] font-medium text-fg">
                        {user.username || user.email}
                      </p>
                      {user.username && (
                        <p className="truncate text-[12.5px] text-fg-muted">
                          {user.email}
                        </p>
                      )}
                    </div>
                    {user.status !== 'active' && (
                      <Badge variant="neutral" size="sm" dot>
                        {user.status}
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}
    </div>
  )
}
