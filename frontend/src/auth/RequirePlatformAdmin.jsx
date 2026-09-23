import { Navigate, useLocation } from 'react-router-dom'
import { useCapabilities } from './capabilities.js'
import { FullPageLoader } from '../components/ui/FullPageLoader.jsx'

/**
 * Route guard that restricts access to platform administrators.
 *
 * Non-platform-administrator users are redirected to their workspace.
 *
 * Holds while the profile is unresolved rather than admitting the request:
 * an unknown principal is not a platform administrator.
 *
 * This is a UX guard. The backend independently enforces authorization
 * on every API request.
 */
export function RequirePlatformAdmin({ children }) {
  const { me, isPlatformAdministrator } = useCapabilities()
  const location = useLocation()

  if (me.isPending) {
    return (
      <FullPageLoader label="Checking your access" />
    )
  }

  if (!isPlatformAdministrator) {
    return <Navigate to="/app" replace state={{ from: location }} />
  }

  return children
}
