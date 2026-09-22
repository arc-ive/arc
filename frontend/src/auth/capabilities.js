import { useMemo } from 'react'
import { APPLICATION_ROLES, useMe } from './useMe.js'

/**
 * Centralized frontend capability layer.
 *
 * Capability names are derived from the backend's actual authorization
 * model: `GET /auth/me` returns the application role and the role's
 * permission matrix exactly as the backend defines it. There is no
 * independent frontend RBAC system and no hardcoded `role === "admin"`
 * checks.
 *
 * This layer only decides PRESENTATION. The backend independently verifies
 * authentication, tenant context, role, and permission on every request.
 *
 * It fails closed. While the profile is loading, or if it failed to load,
 * `permissions` is empty and `can()` is false for everything — the UI offers
 * nothing until the backend has said what this principal may do. `isLoaded`
 * distinguishes "not yet known" from "known to have no permissions" so
 * guards can hold rather than redirect on an unresolved profile.
 */
export function useCapabilities() {
  const me = useMe()

  return useMemo(() => {
    const role = me.data?.role ?? null
    const permissions = new Set(me.data?.permissions ?? [])
    const memberships = me.data?.memberships ?? []

    const can = (permission) => permissions.has(permission)
    const hasRole = (candidate) => role === candidate

    /** Membership of a specific tenant, independent of application role. */
    const isMemberOf = (tenantId) =>
      Boolean(tenantId) && memberships.some((m) => m.tenant_id === tenantId)

    return {
      me,
      role,
      permissions,
      memberships,
      can,
      hasRole,
      isMemberOf,
      isLoaded: Boolean(me.data),
      isPending: me.isPending,
      isPlatformAdministrator: hasRole(APPLICATION_ROLES.PLATFORM_ADMINISTRATOR),
      isCompanyAdministrator: hasRole(APPLICATION_ROLES.COMPANY_ADMINISTRATOR),
      isOperationsUser: hasRole(APPLICATION_ROLES.OPERATIONS_USER),
      isEmployee: hasRole(APPLICATION_ROLES.EMPLOYEE),
    }
  }, [me])
}
