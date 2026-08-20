import { useCallback, useMemo, useState } from 'react'
import { TenantContext } from './context.js'

const STORAGE_KEY = 'arc.tenantId'

export function TenantProvider({ children }) {
  const [tenantId, setTenantIdState] = useState(() =>
    sessionStorage.getItem(STORAGE_KEY),
  )

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