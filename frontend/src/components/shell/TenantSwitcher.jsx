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
import { tenantLandingForRole } from './navigation.js'

export function TenantSwitcher() {
  const { principal, isDemo } = useAuth()
  const { tenantId, setTenantId } = useTenant()
  const { role } = useCapabilities()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useDismissable(ref, () => setOpen(false), open)

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: !isDemo && Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const current = userTenants.data?.find((t) => t.id === tenantId)

  const select = (tenant) => {
    setTenantId(tenant.id)
    setOpen(false)
    const landing = tenantLandingForRole(role)
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
          'flex h-9 max-w-52 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-2.5 text-left transition-colors duration-150 hover:border-zinc-700 hover:bg-zinc-900',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        )}
      >
        <Building2 className="size-4 shrink-0 text-zinc-500" />
        <span className="truncate text-[13px] font-medium text-zinc-200">
          {isDemo ? 'Demo Mode' : (current?.name ?? 'Select tenant')}
        </span>
        <ChevronsUpDown className="ml-auto size-3.5 shrink-0 text-zinc-600" />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Tenant switcher"
          className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-xl border border-zinc-800 bg-raised shadow-overlay animate-scale-in"
        >
          <p className="border-b border-zinc-800/70 px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-600">
            Your tenants
          </p>
          <div className="max-h-64 overflow-y-auto p-1">
            {isDemo && (
              <p className="px-3 py-2.5 text-[13px] text-zinc-500">
                Demo Mode — no tenant data
              </p>
            )}
            {!isDemo && userTenants.isPending && (
              <div className="flex items-center gap-2 px-3 py-2.5 text-[13px] text-zinc-500">
                <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                Loading…
              </div>
            )}
            {!isDemo && userTenants.isError && (
              <p className="px-3 py-2.5 text-[13px] text-red-400">
                Could not load tenants
              </p>
            )}
            {!isDemo &&
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
                      ? 'bg-zinc-800/70 text-zinc-100'
                      : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200',
                  )}
                >
                  <Building2 className="size-4 shrink-0 text-zinc-600" />
                  <span className="flex-1 truncate">{tenant.name}</span>
                  {tenant.id === tenantId && (
                    <Check className="size-3.5 text-indigo-400" />
                  )}
                </button>
              ))}
            {!isDemo &&
              !userTenants.isPending &&
              !userTenants.isError &&
              !userTenants.data?.length && (
                <p className="px-3 py-2.5 text-[13px] text-zinc-500">
                  No tenants assigned
                </p>
              )}
          </div>
        </div>
      )}
    </div>
  )
}