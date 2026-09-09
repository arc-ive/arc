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
 * Resolve the user profile from the server-side session.
 * Calls GET /auth/me which returns the profile from the session cookie.
 * In Demo Mode, returns a synthetic profile.
 */
export function useMe() {
  const { principal, isDemo } = useAuth()

  const query = useQuery({
    queryKey: queryKeys.me(principal?.sub),
    queryFn: () => getMe(),
    enabled: Boolean(principal) && !isDemo,
    staleTime: 5 * 60 * 1000,
  })

  if (isDemo) {
    return {
      ...query,
      isPending: false,
      isLoading: false,
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
