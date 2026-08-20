import { useQuery } from '@tanstack/react-query'
import { getMe } from '../api/endpoints/me.js'
import { queryKeys } from '../api/queryKeys.js'
import { useAuth } from './useAuth.js'

export const APPLICATION_ROLES = {
  PLATFORM_ADMINISTRATOR: 'platform_administrator',
  COMPANY_ADMINISTRATOR: 'company_administrator',
  OPERATIONS_USER: 'operations_user',
  EMPLOYEE: 'employee',
}

/**
 * The authenticated user's authorized profile, as reported by the backend
 * `GET /auth/me` endpoint.
 *
 * The backend resolves the application role from the explicit X-11 role
 * assignments and returns the role's permission matrix. The frontend uses
 * this ONLY for presentation (what to show); every protected operation is
 * still authorized by the backend.
 *
 * In Demo Mode there is no backend session, so a synthetic profile is
 * returned: no role, no permissions, no memberships. The full navigation
 * surface stays available for inspection, and any API-backed page shows
 * its real loading/error states.
 */
export function useMe() {
  const { principal, isDemo } = useAuth()

  const query = useQuery({
    queryKey: queryKeys.me(principal?.sub),
    queryFn: getMe,
    enabled: Boolean(principal) && !isDemo,
    staleTime: 5 * 60 * 1000,
  })

  if (isDemo) {
    return {
      ...query,
      data: {
        user_id: principal?.sub,
        role: null,
        permissions: [],
        memberships: [],
        is_demo: true,
      },
    }
  }

  return query
}