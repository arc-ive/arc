import { Outlet, useParams } from 'react-router-dom'
import { RequireTenant } from '../../tenant/RequireTenant.jsx'

export function TenantLayout() {
  const { tenantId } = useParams()
  return (
    <RequireTenant key={tenantId}>
      <Outlet />
    </RequireTenant>
  )
}