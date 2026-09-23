import { useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/useAuth.js'
import { useCapabilities } from '../auth/capabilities.js'
import { getUserTenants } from '../api/endpoints/tenants.js'
import { queryKeys } from '../api/queryKeys.js'
import { errorMessage } from '../api/errors.js'
import { useTenant } from './useTenant.js'
import { Spinner } from '../components/ui/Spinner.jsx'
import { ErrorState } from '../components/ui/ErrorState.jsx'
import { ShieldX, Building2 } from 'lucide-react'


/**
 * A blocked tenant route still has to be a page.
 *
 * Previously these states rendered a bare `EmptyState`, whose title is an
 * `h3` — so the document had no `h1` at all and screen-reader users landed
 * on a headless page. This gives the blocked state a real page heading
 * while keeping the same visual composition.
 */
function BlockedPage({ icon: Icon, title, description }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center">
      <div className="flex shrink-0 items-center text-fg-muted">
        <Icon className="size-5" aria-hidden />
      </div>
      <h1 className="text-lg font-semibold tracking-tight text-fg">{title}</h1>
      <p className="max-w-md text-[13px] leading-relaxed text-fg-muted">{description}</p>
    </div>
  )
}

/**
 * Guards tenant-scoped routes.
 *
 * The tenant id in the URL is never an authorization mechanism — it only
 * selects which tenant the API is asked about. The backend remains
 * authoritative for membership and permissions.
 */
export function RequireTenant({ children }) {
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { setTenantId } = useTenant()
  const { isPlatformAdministrator } = useCapabilities()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
  })

  useEffect(() => {
    if (tenantId) setTenantId(tenantId)
  }, [tenantId, setTenantId])

  const tenant = useMemo(() => {
    if (!userTenants.data) return undefined
    return userTenants.data.find((t) => t.id === tenantId)
  }, [userTenants.data, tenantId])

  if (userTenants.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner className="size-6 text-fg-muted" />
      </div>
    )
  }

  if (userTenants.isError) {
    return (
      <ErrorState
        title="Could not load your workspaces"
        message={errorMessage(userTenants.error)}
        onRetry={() => userTenants.refetch()}
      />
    )
  }

  if (!userTenants.data?.length) {
    return (
      <BlockedPage
        icon={Building2}
        title="No workspace access"
        description={
          isPlatformAdministrator
            ? 'Platform administration and customer workspaces are separate. Administering the platform does not grant access to a customer workspace — that requires membership of it.'
            : 'You are not a member of any workspace yet. Ask your administrator to add you to one.'
        }
      />
    )
  }

  if (!tenant) {
    return (
      <BlockedPage
        icon={ShieldX}
        title="You don't have access to this workspace"
        description="You are not a member of this workspace, or it does not exist."
      />
    )
  }

  return children
}