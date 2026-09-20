import { Navigate, useParams, useLocation } from 'react-router-dom'
import { useCapabilities } from './capabilities.js'

/**
 * Route guard that restricts workspace admin routes by role.
 *
 * Employees are redirected to their tenant home page. Company
 * administrators, operations users, platform administrators, and
 * Demo Mode users are allowed through.
 *
 * This is a UX/navigation guard. The backend remains the
 * authorization authority and independently rejects unauthorized
 * operations on every API request.
 */
export function RequireWorkspaceRole({ children }) {
  const { tenantId } = useParams()
  const { isEmployee, isDemo } = useCapabilities()
  const location = useLocation()

  if (isEmployee && !isDemo) {
    const tenantHome = `/app/t/${encodeURIComponent(tenantId)}/home`
    return <Navigate to={tenantHome} replace state={{ from: location }} />
  }

  return children
}
