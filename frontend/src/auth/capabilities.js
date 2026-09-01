import { useMemo } from 'react'
import { APPLICATION_ROLES, useMe } from './useMe.js'

/**
 * Centralized frontend capability layer.
 *
 * Capability names are derived from the backend's actual authorization
 * model: `GET /auth/me` returns the application role and the role's
 * permission matrix exactly as the backend defines it. There is no
 * independent frontend RBAC system and no hardcoded
 * `role === "admin"` checks.
 *
 * This layer only decides PRESENTATION. The backend independently verifies
 * authentication, tenant context, role, and permission on every request.
 *
 * Demo Mode has no role and no permissions, so `can()` is always false;
 * the navigation shell exposes the full product surface for inspection.
 */
export function useCapabilities() {
  const me = useMe()

  return useMemo(() => {
    const role = me.data?.role ?? null
    const permissions = new Set(me.data?.permissions ?? [])
    const isDemo = Boolean(me.data?.is_demo)

    const can = (permission) => permissions.has(permission)
    const hasRole = (candidate) => role === candidate
    const isPlatformAdministrator = hasRole(APPLICATION_ROLES.PLATFORM_ADMINISTRATOR)
    const isCompanyAdministrator = hasRole(APPLICATION_ROLES.COMPANY_ADMINISTRATOR)
    const isOperationsUser = hasRole(APPLICATION_ROLES.OPERATIONS_USER)
    const isEmployee = hasRole(APPLICATION_ROLES.EMPLOYEE)

    return {
      me,
      role,
      permissions,
      can,
      hasRole,
      isPlatformAdministrator,
      isCompanyAdministrator,
      isOperationsUser,
      isEmployee,
      isDemo,
    }
  }, [me])
}