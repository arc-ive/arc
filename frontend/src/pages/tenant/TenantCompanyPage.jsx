import { useParams } from 'react-router-dom'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery } from '@tanstack/react-query'
import { Building2, Info, ShieldCheck } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { getKnowledge } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { formatDate } from '../../lib/format.js'

export function TenantCompanyPage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()

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

  const sources = (knowledge.data ?? []).reduce((counts, doc) => {
    counts[doc.source] = (counts[doc.source] ?? 0) + 1
    return counts
  }, {})

  return (
    <div className="flex flex-col gap-8">
      <section>
        <PageHeader title="Company"
          description="Information about this tenant organization, as authorized by the      backend." />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Organization"
            description="Tenant identity provisioned on the platform."
          />
          <CardContent>
            {userTenants.isPending ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-5 w-1/2" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-fg-muted">
                    <Building2 className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-zinc-100">
                      {tenant?.name ?? 'Tenant'}
                    </p>
                    <p className="truncate font-mono text-xs text-fg-muted">
                      {tenantId}
                    </p>
                  </div>
                  <Badge
                    variant={tenant?.status === 'active' ? 'green' : 'neutral'}
                    dot
                    className="ml-auto shrink-0"
                  >
                    {tenant?.status ?? 'unknown'}
                  </Badge>
                </div>
                <dl className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3.5 py-3">
                    <dt className="text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
                      Members
                    </dt>
                    <dd className="mt-1 text-lg font-semibold text-zinc-100">
                      {users.isPending ? '—' : users.data?.length ?? 0}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3.5 py-3">
                    <dt className="text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
                      Knowledge documents
                    </dt>
                    <dd className="mt-1 text-lg font-semibold text-zinc-100">
                      {knowledge.isPending ? '—' : knowledge.data?.length ?? 0}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3.5 py-3">
                    <dt className="text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
                      Created
                    </dt>
                    <dd className="mt-1 text-[13px] font-medium text-zinc-200">
                      {formatDate(tenant?.created_at)}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-3.5 py-3">
                    <dt className="text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
                      Updated
                    </dt>
                    <dd className="mt-1 text-[13px] font-medium text-zinc-200">
                      {formatDate(tenant?.updated_at)}
                    </dd>
                  </div>
                </dl>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title="Company Profile"
            description="Organization details configured in Settings."
          />
          <CardContent>
            {userTenants.isPending ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ) : (
              <dl className="flex flex-col gap-3 text-[13px]">
                {[
                  { label: 'Industry', value: tenant?.industry },
                  { label: 'Address', value: tenant?.address },
                  { label: 'Phone', value: tenant?.phone },
                  { label: 'Website', value: tenant?.website },
                  { label: 'Logo URL', value: tenant?.logo_url },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-baseline justify-between gap-3">
                    <dt className="shrink-0 text-fg-muted">{label}</dt>
                    <dd className="min-w-0 truncate text-right text-zinc-300">
                      {value || <span className="text-fg-muted">—</span>}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title="Company intelligence"
            description="Knowledge stored in the Company Brain, by source."
          />
          <CardContent>
            {knowledge.isPending ? (
              <div className="flex flex-col gap-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : knowledge.isError ? (
              <ErrorState
                title="Could not load knowledge"
                message={errorMessage(knowledge.error)}
                onRetry={() => knowledge.refetch()}
                compact
              />
            ) : (knowledge.data ?? []).length === 0 ? (
              <EmptyState
                icon={Building2}
                title="No knowledge stored"
                description="The Company Brain is empty. Documents added there appear here by source."
                compact
              />
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(sources).map(([source, count]) => (
                  <Badge key={source} variant="neutral">
                    {source} · {count}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="flex items-start gap-2.5 rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3">
        <Info className="mt-0.5 size-4 shrink-0 text-fg-muted" />
        <p className="text-xs leading-relaxed text-fg-muted">
          Company profile details are configured on the{' '}
          <span className="text-zinc-300">Settings</span> page. Every
          request is authorized by the backend — access to this tenant is
          validated on each call.
        </p>
      </section>

      <div className="flex items-center gap-1.5 text-xs text-fg-muted">
        <ShieldCheck className="size-3.5" />
        Tenant boundary enforced server-side for every request.
      </div>
    </div>
  )
}