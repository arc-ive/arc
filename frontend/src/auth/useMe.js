import { useQuery } from '@tanstack/react-query'
import { getMe } from '../api/endpoints/me.js'
import { getUserTenants } from '../api/endpoints/tenants.js'
import { queryKeys } from '../api/queryKeys.js'
import { useAuth } from './useAuth.js'

export const APPLICATION_ROLES = {
  PLATFORM_ADMINISTRATOR: 'platform_administrator',
  COMPANY_ADMINISTRATOR: 'company_administrator',
  OPERATIONS_USER: 'operations_user',
  EMPLOYEE: 'employee',
}

/**
 * Resolve the user profile. Tries `GET /auth/me` first. When that
 * endpoint does not exist (404), falls back to deriving a minimal profile
 * from the JWT subject and `GET /users/{user_id}/tenants`. The returned
 * shape is always the same — downstream consumers never need to know
 * which path was taken.
 *
 * In Demo Mode there is no backend session, so a synthetic profile is
 * returned: no role, no permissions, no memberships. The full navigation
 * surface stays available for inspection, and any API-backed page shows
 * its real loading/error states.
 */
function fetchProfile(principal) {
  return getMe().catch((err) => {
    const status = err?.response?.status
    if (status !== 404) throw err

    const userId = principal?.sub
    if (!userId) return { user_id: null, role: null, permissions: [], memberships: [] }

    return getUserTenants(userId).then((tenants) => ({
      user_id: userId,
      role: null,
      permissions: [],
      memberships: (tenants ?? []).map((t) => ({ tenant_id: t.id, role: 'member' })),
    })).catch(() => ({
      user_id: userId,
      role: null,
      permissions: [],
      memberships: [],
    }))
  })
}

export function useMe() {
  const { principal, isDemo } = useAuth()

  const query = useQuery({
    queryKey: queryKeys.me(principal?.sub),
    queryFn: () => fetchProfile(principal),
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

  if (query.isError && query.error?.response?.status === 404) {
    return {
      ...query,
      isPending: false,
      isLoading: false,
      isError: false,
      error: null,
      data: query.data ?? {
        user_id: principal?.sub,
        role: null,
        permissions: [],
        memberships: [],
      },
    }
  }

  return query
}