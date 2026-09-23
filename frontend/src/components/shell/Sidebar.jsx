import { NavLink, useLocation } from 'react-router-dom'
import { cn } from '../../lib/cn.js'
import { useTenant } from '../../tenant/useTenant.js'
import { ContextHeader } from './ContextHeader.jsx'
import { useCapabilities } from '../../auth/capabilities.js'
import {
  personalNav,
  platformNav,
  tenantNavForCapabilities,
} from './navigation.js'

function NavItem({ to, label, icon: Icon, onNavigate }) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors duration-150',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
          isActive
            ? 'bg-zinc-900 text-zinc-100'
            : 'text-fg-muted hover:bg-zinc-900/60 hover:text-zinc-200',
        )
      }
    >
      {({ isActive }) => (
        <>
          {Icon && <Icon
            className={cn(
              'size-4 shrink-0 transition-colors duration-150',
              isActive ? 'text-indigo-400' : 'text-fg-muted group-hover:text-zinc-400',
            )}
          />}
          {label}
        </>
      )}
    </NavLink>
  )
}


/**
 * One of the five product areas, with its sub-navigation.
 *
 * The area heading is not itself a link: an area is a grouping, not a
 * destination, and making it navigable would mean inventing a landing page
 * for it. The children are the destinations.
 *
 * The left rule is what carries the grouping visually — it costs less than
 * a card or a border box and stays legible at this density.
 */
function NavArea({ area, tenantPrefix, onNavigate }) {
  const Icon = area.icon
  return (
    <div className="mt-1 first:mt-0">
      <p className="flex items-center gap-2.5 px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
        {Icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
        {area.label}
      </p>
      <div className="ml-[18px] flex flex-col gap-0.5 border-l border-line pl-2.5">
        {area.children.map((child) => (
          <NavItem
            key={child.to}
            to={`${tenantPrefix}/${child.to}`}
            label={child.label}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  )
}

function NavGroup({ title, children }) {
  return (
    <div>
      <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
        {title}
      </p>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  )
}

/**
 * Capability-aware sidebar.
 *
 * Two independent decisions:
 *
 *  - The platform console is offered only to platform administrators.
 *  - Workspace navigation is offered only to an actual MEMBER of the tenant
 *    in scope, and lists only the surfaces that member's permissions cover.
 *
 * Membership rather than role is what gates the workspace section, per
 * V2-ADR-003: platform administration and tenant workspace administration
 * remain distinct, and holding every permission is not membership. A
 * platform administrator with no membership previously received all
 * fifteen workspace items, every one of which dead-ended on the
 * "not a member" state.
 *
 * This is UX only — the backend enforces every operation.
 */
export function Sidebar({ mobile = false, onNavigate }) {
  const { tenantId } = useTenant()
  const { can, isMemberOf, isPlatformAdministrator, isEmployee } = useCapabilities()
  const location = useLocation()

  // The two contexts are mutually exclusive. Previously both stacked, which
  // is how a platform administrator ended up with fifteen workspace items
  // under their platform items. One context's navigation shows at a time;
  // ContextHeader carries the link across.
  const inPlatform = location.pathname.startsWith('/platform')

  const tenantPrefix = tenantId ? `/app/t/${encodeURIComponent(tenantId)}` : null
  const tenantNav = tenantNavForCapabilities(can)
  const showWorkspace =
    !inPlatform && Boolean(tenantPrefix) && isMemberOf(tenantId) && tenantNav.length > 0
  const showPlatform = inPlatform && isPlatformAdministrator

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'flex h-full flex-col gap-6 overflow-y-auto border-zinc-800/70 bg-base px-3 py-4',
        mobile ? '' : 'border-r',
      )}
    >
      <ContextHeader onNavigate={onNavigate} />
      <div className="flex flex-1 flex-col gap-6">
        {showPlatform ? (
          <NavGroup title="Console">
            {platformNav.map((item) => (
              <NavItem key={item.to} {...item} onNavigate={onNavigate} />
            ))}
          </NavGroup>
        ) : null}

        {showWorkspace && (
          <div className="flex flex-col gap-0.5">
            {tenantNav.map((area) =>
              area.children ? (
                <NavArea
                  key={area.id}
                  area={area}
                  tenantPrefix={tenantPrefix}
                  onNavigate={onNavigate}
                />
              ) : (
                <NavItem
                  key={area.id ?? area.to}
                  to={`${tenantPrefix}/${area.to}`}
                  label={area.label}
                  icon={area.icon}
                  onNavigate={onNavigate}
                />
              ),
            )}
          </div>
        )}

        {!isEmployee && (
          <NavGroup title="Personal">
            {personalNav.map((item) => (
              <NavItem key={item.to} {...item} onNavigate={onNavigate} />
            ))}
          </NavGroup>
        )}
      </div>
    </nav>
  )
}