import { useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/useAuth.js'
import { getUserTenants } from '../api/endpoints/tenants.js'
import { queryKeys } from '../api/queryKeys.js'
import { errorMessage } from '../api/errors.js'
import { useTenant } from './useTenant.js'
import { Spinner } from '../components/ui/Spinner.jsx'
import { ErrorState } from '../components/ui/ErrorState.jsx'
import { EmptyState } from '../components/ui/EmptyState.jsx'
import { ShieldX, Building2 } from 'lucide-react'

/**
 * Guards tenant-scoped routes.
 *
 * The tenant id in the URL is never an authorization mechanism — it only
 * selects which tenant the API is asked about. The backend remains
 * authoritative for membership and permissions.
 */
export function RequireTenant({ children }) {
  const { tenantId } = useParams()
  const { principal, isDemo } = useAuth()
  const { setTenantId } = useTenant()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: !isDemo && Boolean(principal),
  })

  useEffect(() => {
    if (tenantId) setTenantId(tenantId)
  }, [tenantId, setTenantId])

  const tenant = useMemo(() => {
    if (!userTenants.data) return undefined
    return userTenants.data.find((t) => t.id === tenantId)
  }, [userTenants.data, tenantId])

  if (isDemo) {
    return (
      <EmptyState
        icon={ShieldX}
        title="Tenant access denied"
        description="Demo Mode provides no tenant membership data, so tenant workspaces cannot be opened. Sign in with a real session to load your tenants."
      />
    )
  }

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
        title="Could not load your tenants"
        message={errorMessage(userTenants.error)}
        onRetry={() => userTenants.refetch()}
      />
    )
  }

  if (!userTenants.data?.length) {
    return (
      <EmptyState
        icon={Building2}
        title="No tenants yet"
        description="You are not a member of any tenant. Ask a platform administrator to provision your membership."
      />
    )
  }

  if (!tenant) {
    return (
      <EmptyState
        icon={ShieldX}
        title="Tenant access denied"
        description="You are not a member of this tenant, or it does not exist. You cannot access its data."
      />
    )
  }

  return children
}