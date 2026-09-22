import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn.js'
import { useTenant } from '../../tenant/useTenant.js'
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
          <Icon
            className={cn(
              'size-4 shrink-0 transition-colors duration-150',
              isActive ? 'text-indigo-400' : 'text-fg-muted group-hover:text-zinc-400',
            )}
          />
          {label}
        </>
      )}
    </NavLink>
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

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2 py-1">
      <div className="flex size-7 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
        <svg viewBox="0 0 32 32" className="size-4" aria-hidden>
          <path d="M8 10.5h9a4.5 4.5 0 0 1 0 9h-3v6h-6v-15Z" fill="#e4e4e7" />
          <path d="M8 13.5h6v6H8v-6Z" fill="#6366f1" />
        </svg>
      </div>
      <span className="text-[15px] font-semibold tracking-tight text-zinc-100">
        Arc
      </span>
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

  const tenantPrefix = tenantId ? `/app/t/${encodeURIComponent(tenantId)}` : null
  const tenantNav = tenantNavForCapabilities(can)
  const showWorkspace = Boolean(tenantPrefix) && isMemberOf(tenantId) && tenantNav.length > 0

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'flex h-full flex-col gap-6 overflow-y-auto border-zinc-800/70 bg-base px-3 py-4',
        mobile ? '' : 'border-r',
      )}
    >
      <Brand />
      <div className="flex flex-1 flex-col gap-6">
        {isPlatformAdministrator ? (
          <NavGroup title="Platform">
            {platformNav.map((item) => (
              <NavItem key={item.to} {...item} onNavigate={onNavigate} />
            ))}
          </NavGroup>
        ) : null}

        {showWorkspace && (
          <NavGroup title="Workspace">
            {tenantNav.map((item) => (
              <NavItem
                key={item.to}
                to={`${tenantPrefix}/${item.to}`}
                label={item.label}
                icon={item.icon}
                onNavigate={onNavigate}
              />
            ))}
          </NavGroup>
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