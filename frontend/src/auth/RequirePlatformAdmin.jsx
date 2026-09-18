import { Navigate, useLocation } from 'react-router-dom'
import { useCapabilities } from './capabilities.js'

/**
 * Route guard that restricts access to platform administrators.
 *
 * Non-platform-administrator users are redirected to their workspace.
 * Demo Mode users are allowed through (existing behavior).
 *
 * This is a UX guard. The backend independently enforces authorization
 * on every API request.
 */
export function RequirePlatformAdmin({ children }) {
  const { me, isPlatformAdministrator, isDemo } = useCapabilities()
  const location = useLocation()

  if (me.isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-base">
        <div className="size-6 animate-spin rounded-full border-2 border-zinc-600 border-t-zinc-300" />
      </div>
    )
  }

  if (!isPlatformAdministrator && !isDemo) {
    return <Navigate to="/app" replace state={{ from: location }} />
  }

  return children
}
