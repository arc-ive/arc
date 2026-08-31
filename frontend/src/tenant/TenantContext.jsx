import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { TenantContext } from './context.js'
import { queryKeys } from '../api/queryKeys.js'

const STORAGE_KEY = 'arc.tenantId'

export function TenantProvider({ children }) {
  const queryClient = useQueryClient()
  const [tenantId, setTenantIdState] = useState(() =>
    sessionStorage.getItem(STORAGE_KEY),
  )
  const prevTenantRef = useRef(tenantId)

  useEffect(() => {
    if (prevTenantRef.current !== tenantId) {
      const oldTenant = prevTenantRef.current
      const newTenant = tenantId
      prevTenantRef.current = tenantId

      if (oldTenant && newTenant && oldTenant !== newTenant) {
        queryClient.removeQueries({ queryKey: queryKeys.knowledge(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.skills(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.tools(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.connectors(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.webhookEvents(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.observabilityTenant(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.approvals(oldTenant), exact: true })
        queryClient.removeQueries({ queryKey: queryKeys.tenantUsers(oldTenant), exact: true })
      }
    }
  }, [tenantId, queryClient])

  const setTenantId = useCallback((next) => {
    if (next) {
      sessionStorage.setItem(STORAGE_KEY, next)
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
    setTenantIdState(next)
  }, [])

  const value = useMemo(
    () => ({ tenantId, setTenantId }),
    [tenantId, setTenantId],
  )

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
}