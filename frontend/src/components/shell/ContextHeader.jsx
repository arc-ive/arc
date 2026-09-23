import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Layers } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { cn } from '../../lib/cn.js'

/**
 * States which operating context the user is in.
 *
 * V2-ADR-003 keeps platform administration and tenant workspace
 * administration distinct, but the UI gave that separation almost no
 * expression: both contexts rendered identical chrome, and the only
 * signal was an 11px uppercase sidebar section label. A platform
 * administrator who opened a workspace had no sense of having crossed a
 * boundary.
 *
 * Two changes carry the distinction:
 *
 *  - The sidebar leads with an identity block naming the context — the
 *    workspace by name, or the Platform Console — instead of an anonymous
 *    "Arc" wordmark that is identical everywhere.
 *
 *  - The two contexts are mutually exclusive. The sidebar shows one
 *    context's navigation plus a link to the other, rather than stacking
 *    both. Stacking was what produced fifteen workspace items under a
 *    platform administrator's platform items.
 *
 * Deliberately NOT a second navigation system: the link across is a
 * single row, and each context keeps the one nav it always had.
 */
export function ContextHeader({ onNavigate }) {
  const location = useLocation()
  const { principal } = useAuth()
  const { tenantId } = useTenant()
  const { isPlatformAdministrator, isMemberOf } = useCapabilities()

  const inPlatform = location.pathname.startsWith('/platform')

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal) && !inPlatform,
    staleTime: 5 * 60 * 1000,
  })

  const workspace = userTenants.data?.find((t) => t.id === tenantId)
  const showWorkspaceContext = !inPlatform && Boolean(tenantId) && isMemberOf(tenantId)

  // A platform administrator inside a workspace needs the way back to be
  // visible, not remembered.
  const showConsoleReturn = isPlatformAdministrator && showWorkspaceContext

  return (
    <div className="flex flex-col gap-3">
      {showConsoleReturn && (
        <Link
          to="/platform/dashboard"
          onClick={onNavigate}
          className={cn(
            'flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] font-medium',
            'text-fg-muted transition-colors duration-150 hover:bg-surface-raised hover:text-fg',
            'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
          )}
        >
          <ArrowLeft className="size-3.5 shrink-0" aria-hidden />
          Platform Console
        </Link>
      )}

      <div className="flex items-center gap-2.5 px-2 py-1">
        <ContextMark
          inPlatform={inPlatform || !showWorkspaceContext}
          name={workspace?.name}
        />
        <div className="min-w-0">
          <p className="truncate text-[14px] font-semibold leading-tight tracking-tight text-fg">
            {inPlatform || !showWorkspaceContext
              ? 'Arc'
              : (workspace?.name ?? 'Workspace')}
          </p>
          <p className="truncate text-[11px] leading-tight text-fg-muted">
            {inPlatform ? 'Platform Console' : showWorkspaceContext ? 'Workspace' : 'Enterprise Intelligence'}
          </p>
        </div>
      </div>
    </div>
  )
}

/**
 * The identity mark.
 *
 * The Arc glyph in the platform console; the workspace's own initial in a
 * workspace. Giving the workspace its own mark is what makes the two
 * contexts distinguishable at a glance rather than by reading.
 */
function ContextMark({ inPlatform, name }) {
  if (inPlatform) {
    return (
      <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-overlay">
        <Layers className="size-3.5 text-fg-muted" aria-hidden />
      </div>
    )
  }

  const initial = (name ?? '?').trim().charAt(0).toUpperCase()

  return (
    <div
      aria-hidden
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-lg',
        'border border-primary/40 bg-primary/10 text-[12px] font-semibold text-primary',
      )}
    >
      {initial}
    </div>
  )
}
