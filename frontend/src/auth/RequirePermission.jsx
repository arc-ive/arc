import { Navigate, Outlet, useLocation, useParams } from 'react-router-dom'
import { useCapabilities } from './capabilities.js'
import { tenantLandingForCapabilities } from '../components/shell/navigation.js'
import { Spinner } from '../components/ui/Spinner.jsx'

/**
 * Route guard for a single backend permission.
 *
 * Replaces the previous binary role gate, which wrapped every workspace
 * route in one `isEmployee` check. That had two defects this fixes:
 *
 *  1. It FAILED OPEN while `GET /auth/me` was in flight. `role` was null,
 *     so `isEmployee` was false, so the guard admitted the request — the
 *     page mounted, fired its queries and collected 403s before the
 *     redirect landed. The behaviour was nondeterministic: the same
 *     navigation produced different network traffic run to run. Both
 *     ARC_V2_PRD.md P4 and ARC_V2_TRD.md §6 require failing closed.
 *
 *  2. It was coarser than the backend. One role check stood in for
 *     fourteen different permissions, so it simultaneously denied an
 *     Employee the Company Brain they hold `knowledge:read` for, and
 *     admitted an Operations User to routes their permissions do not
 *     cover.
 *
 * The permission named here is the one the corresponding controller
 * declares via `require_tenant_permission(...)`. This is a UX guard: the
 * backend remains the authorization authority on every request.
 */
export function RequirePermission({ permission, children }) {
  const { can, isLoaded, isPending } = useCapabilities()
  const { tenantId } = useParams()
  const location = useLocation()

  // Hold while the profile is unresolved. Rendering children here is what
  // caused the spurious 403s; redirecting here would bounce a legitimate
  // user on a slow network.
  if (isPending || !isLoaded) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner className="size-6 text-fg-muted" />
      </div>
    )
  }

  if (!can(permission)) {
    const landing = tenantLandingForCapabilities(can)
    const to = tenantId
      ? `/app/t/${encodeURIComponent(tenantId)}/${landing}`
      : '/app'
    return <Navigate to={to} replace state={{ from: location }} />
  }

  return children ?? <Outlet />
}
