import { useQuery } from '@tanstack/react-query'
import { getMe } from '../api/endpoints/me.js'
import { queryKeys } from '../api/queryKeys.js'
import { useAuth } from './useAuth.js'

/**
 * Interactive application roles.
 *
 * `webhook_processor` is deliberately absent: it is a synthetic,
 * non-interactive service role for webhook-triggered downstream execution,
 * not a human persona, and must never be presented as one
 * (ARC_PRODUCT_MODEL.md §5).
 *
 * These are ApplicationRole values. The X-10 tenant membership roles
 * (OWNER / MEMBER / VIEWER) are a separate authorization concept with no
 * mapping to these, and the two must not be merged.
 */
export const APPLICATION_ROLES = {
  PLATFORM_ADMINISTRATOR: 'platform_administrator',
  COMPANY_ADMINISTRATOR: 'company_administrator',
  OPERATIONS_USER: 'operations_user',
  EMPLOYEE: 'employee',
}

/**
 * Resolve the authorized profile from the server-side session.
 *
 * `GET /auth/me` returns the application role, the backend's own permission
 * matrix for that role, and the user's tenant memberships. This is the only
 * source of authorization information in the client — there is no synthetic
 * or fallback profile, so an unresolved query reports no permissions and
 * every capability check fails closed.
 */
export function useMe() {
  const { principal } = useAuth()

  return useQuery({
    queryKey: queryKeys.me(principal?.sub),
    queryFn: () => getMe(),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })
}
