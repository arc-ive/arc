import { Navigate } from 'react-router-dom'
import { Building2, ShieldCheck } from 'lucide-react'
import { useCapabilities } from '../../auth/capabilities.js'
import { errorMessage } from '../../api/errors.js'
import { tenantLandingForCapabilities } from '../../components/shell/navigation.js'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

/**
 * Authenticated workspace dispatch.
 *
 * After authentication the correct experience is determined from the
 * authorized context reported by the backend (`GET /auth/me`):
 *
 * - Platform Administrator  → the ARC platform console
 * - Tenant member           → their tenant workspace
 * - No memberships          → an explicit "no tenants" state
 *
 * This is UX routing only. The backend validates membership and
 * permissions on every request.
 */
export function WorkspaceDispatch() {
  const { me, can, isPlatformAdministrator } = useCapabilities()

  if (me.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner className="size-6 text-fg-muted" />
      </div>
    )
  }

  if (me.isError) {
    return (
      <ErrorState
        title="Could not load your authorized profile"
        message={errorMessage(me.error)}
        onRetry={() => me.refetch()}
        error={me.error}
      />
    )
  }

  if (isPlatformAdministrator) {
    return <Navigate to="/platform/dashboard" replace />
  }

  const memberships = me.data?.memberships ?? []
  const first = memberships[0]

  if (first?.tenant_id) {
    const landing = tenantLandingForCapabilities(can)
    return (
      <Navigate
        to={`/app/t/${encodeURIComponent(first.tenant_id)}/${landing}`}
        replace
      />
    )
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-lg">
        <EmptyState
          icon={Building2}
          title="You are not a member of any tenant"
          description="Your identity is authenticated, but no tenant membership has been provisioned. Ask a platform administrator to assign you to an organization."
          action={
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-raised px-2.5 py-1 text-[11px] font-medium tracking-wide text-fg-muted">
              <ShieldCheck className="size-3" />
              Identity and membership are managed by the backend
            </span>
          }
        />
      </div>
    </div>
  )
}