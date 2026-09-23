import { NavLink, useLocation } from 'react-router-dom'
import { Search, Menu } from 'lucide-react'
import { useTenant } from '../../tenant/useTenant.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { platformNav, tenantNavForCapabilities } from './navigation.js'
import { TenantSwitcher } from './TenantSwitcher.jsx'
import { UserMenu } from './UserMenu.jsx'
import { IconButton } from '../ui/IconButton.jsx'
import { cn } from '../../lib/cn.js'

/**
 * Arc's navigation.
 *
 * Replaces a 240px sidebar that ran down every page whether or not the page
 * needed it. The information architecture is unchanged — the five areas, the
 * permission gates, the platform/workspace split are all the same, and the
 * gating calls are the same functions the sidebar used. What changes is that
 * navigation stops occupying a sixth of the viewport on every route, which
 * is what gives the pages a field wide enough to compose in.
 *
 * Two rows. The first carries identity and the areas; the second appears only
 * when the current area has more than one surface, so a single-surface area
 * costs nothing. The active area is marked with a rule rather than a filled
 * pill — a mark, not a button.
 *
 * Every permission decision here is read from `useCapabilities()`, which
 * reflects the backend's own matrix. Navigation fails closed: an unresolved
 * profile reports no permissions and gets no links.
 */
export function Masthead({ onOpenSearch, onOpenMenu }) {
  const { tenantId } = useTenant()
  const { can, isMemberOf, isPlatformAdministrator } = useCapabilities()
  const location = useLocation()

  const inPlatform = location.pathname.startsWith('/platform')
  const tenantPrefix = tenantId ? `/app/t/${encodeURIComponent(tenantId)}` : null
  const tenantNav = tenantNavForCapabilities(can)

  const showWorkspace =
    !inPlatform && Boolean(tenantPrefix) && isMemberOf(tenantId) && tenantNav.length > 0
  const showPlatform = inPlatform && isPlatformAdministrator

  const areas = showPlatform
    ? platformNav.map((item) => ({ ...item, id: item.to, href: item.to }))
    : showWorkspace
      ? tenantNav.map((area) => ({
          ...area,
          href: `${tenantPrefix}/${area.children ? area.children[0].to : area.to}`,
          childLinks: area.children?.map((c) => ({
            ...c,
            href: `${tenantPrefix}/${c.to}`,
          })),
        }))
      : []

  // The area whose surfaces the reader is currently inside. Matched on the
  // trailing segment so a detail route (knowledge/:id) keeps its area marked.
  const activeArea = areas.find((area) =>
    area.childLinks
      ? area.childLinks.some((c) => location.pathname.startsWith(c.href))
      : location.pathname.startsWith(area.href),
  )

  const subNav = activeArea?.childLinks?.length > 1 ? activeArea.childLinks : null

  return (
    <header className="sticky top-0 z-30 shrink-0 border-b border-line bg-canvas/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-[1600px] items-center gap-4 px-4 sm:px-6 lg:px-10">
        <IconButton label="Open menu" onClick={onOpenMenu} className="lg:hidden">
          <Menu className="size-4" />
        </IconButton>

        <Wordmark inPlatform={showPlatform} />

        {!showPlatform && (
          <div className="hidden lg:block">
            <TenantSwitcher />
          </div>
        )}

        {areas.length > 0 && (
          <nav aria-label="Primary" className="hidden min-w-0 lg:block">
            <ul className="flex items-center">
              {areas.map((area) => (
                <li key={area.id ?? area.to}>
                  <AreaLink
                    href={area.href}
                    label={area.label}
                    active={activeArea === area}
                  />
                </li>
              ))}
            </ul>
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenSearch}
            className={cn(
              'hidden h-9 items-center gap-2 rounded-md border border-line px-2.5 pr-2',
              'text-[13px] text-fg-muted transition-colors duration-150',
              'hover:border-line-strong hover:text-fg md:flex',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
            )}
          >
            <Search className="size-3.5" />
            <span>Search</span>
            <kbd className="ml-3 rounded border border-line px-1 py-0.5 font-mono text-[10px] text-fg-muted">
              ⌘K
            </kbd>
          </button>
          <IconButton label="Search" onClick={onOpenSearch} className="md:hidden">
            <Search className="size-4" />
          </IconButton>
          <UserMenu />
        </div>
      </div>

      {subNav && (
        <div className="border-t border-line/70">
          <div className="mx-auto w-full max-w-[1600px] px-4 sm:px-6 lg:px-10">
            <nav aria-label={`${activeArea.label} sections`}>
              <ul className="-mb-px flex items-center gap-6 overflow-x-auto">
                {subNav.map((child) => (
                  <li key={child.to}>
                    <SubLink href={child.href} label={child.label} />
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </div>
      )}
    </header>
  )
}

/**
 * The area mark.
 *
 * A 2px rule under the active label rather than a filled pill. A pill reads
 * as a button you could press to change something; a rule reads as "you are
 * here", which is what it means.
 */
function AreaLink({ href, label, active }) {
  return (
    <NavLink
      to={href}
      className={cn(
        'relative inline-flex h-16 items-center px-3.5 text-[13.5px] font-medium',
        'transition-colors duration-150',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
        active ? 'text-fg' : 'text-fg-muted hover:text-fg',
      )}
      aria-current={active ? 'page' : undefined}
    >
      {label}
      {active && (
        <span
          aria-hidden
          className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-accent"
        />
      )}
    </NavLink>
  )
}

function SubLink({ href, label }) {
  return (
    <NavLink
      to={href}
      end
      className={({ isActive }) =>
        cn(
          'inline-flex h-10 items-center border-b-2 text-[13px] transition-colors duration-150',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
          isActive
            ? 'border-fg font-medium text-fg'
            : 'border-transparent text-fg-muted hover:text-fg',
        )
      }
    >
      {label}
    </NavLink>
  )
}

/**
 * The wordmark.
 *
 * Set in the display serif, because it is the one piece of chrome that is
 * also content. The console plane says so in the mark itself rather than
 * relying on a badge somewhere further down the page.
 */
function Wordmark({ inPlatform }) {
  return (
    <div className="flex shrink-0 items-baseline gap-2">
      <span className="type-display text-[1.375rem] leading-none tracking-tight text-fg">
        Arc
      </span>
      {inPlatform && (
        <span className="type-label text-accent">Platform</span>
      )}
    </div>
  )
}
