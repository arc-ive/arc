import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, Check, ChevronsUpDown, Loader2 } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useTenant } from '../../tenant/useTenant.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { useDismissable } from '../../lib/useDismissable.js'
import { cn } from '../../lib/cn.js'
import { tenantLandingForCapabilities } from './navigation.js'

export function TenantSwitcher() {
  const { principal } = useAuth()
  const { tenantId, setTenantId } = useTenant()
  const { can } = useCapabilities()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useDismissable(ref, () => setOpen(false), open)

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const current = userTenants.data?.find((t) => t.id === tenantId)

  const select = (tenant) => {
    setTenantId(tenant.id)
    setOpen(false)
    const landing = tenantLandingForCapabilities(can)
    navigate(`/app/t/${encodeURIComponent(tenant.id)}/${landing}`)
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          'flex h-9 max-w-52 items-center gap-2 rounded-lg border border-line bg-surface-raised px-2.5 text-left transition-colors duration-150 hover:border-line-strong hover:bg-surface-overlay',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        )}
      >
        <Building2 className="size-4 shrink-0 text-fg-muted" />
        <span className="truncate text-[13px] font-medium text-fg">
          {current?.name ?? 'Select workspace'}
        </span>
        <ChevronsUpDown className="ml-auto size-3.5 shrink-0 text-fg-muted" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Tenant switcher"
          className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-xl border border-line bg-raised shadow-overlay animate-scale-in"
        >
          <p className="border-b border-line/70 px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
            Your tenants
          </p>
          <div className="max-h-64 overflow-y-auto p-1">
                        {userTenants.isPending && (
              <div className="flex items-center gap-2 px-3 py-2.5 text-[13px] text-fg-muted">
                <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                Loading…
              </div>
            )}
            {userTenants.isError && (
              <p className="px-3 py-2.5 text-[13px] text-danger">
                Could not load tenants
              </p>
            )}
            {
              userTenants.data?.map((tenant) => (
                <button
                  key={tenant.id}
                  type="button"
                  role="option"
                  aria-selected={tenant.id === tenantId}
                  onClick={() => select(tenant)}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors duration-100',
                    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
                    tenant.id === tenantId
                      ? 'bg-surface-selected text-fg'
                      : 'text-fg-muted hover:bg-surface-overlay hover:text-fg',
                  )}
                >
                  <Building2 className="size-4 shrink-0 text-fg-muted" />
                  <span className="flex-1 truncate">{tenant.name}</span>
                  {tenant.id === tenantId && (
                    <Check className="size-3.5 text-accent" />
                  )}
                </button>
              ))}
            {
              !userTenants.isPending &&
              !userTenants.isError &&
              !userTenants.data?.length && (
                <p className="px-3 py-2.5 text-[13px] text-fg-muted">
                  No tenants assigned
                </p>
              )}
          </div>
        </div>
      )}
    </div>
  )
}