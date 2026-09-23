import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { X } from 'lucide-react'
import { Sidebar } from './Sidebar.jsx'
import { Masthead } from './Masthead.jsx'
import { CommandPalette } from './CommandPalette.jsx'
import { IconButton } from '../ui/IconButton.jsx'
import { SkipLink } from './SkipLink.jsx'
import { RouteAnnouncer } from './RouteAnnouncer.jsx'

/**
 * The application frame.
 *
 * Navigation moved from a permanent 240px sidebar to a masthead. The sidebar
 * survives as the mobile sheet, where a vertical list is the right shape and
 * where it costs nothing because it is not on screen.
 *
 * There is ONE Arc. Platform, tenant, employee and viewer stand on the
 * same ground, in the same type, with the same components — the role
 * changes what is reachable and what is shown, never what Arc looks like.
 * An earlier version gave the Platform Console its own dark plane and each
 * area its own paper; that made four products out of one.
 *
 * Context is carried where it belongs: by the masthead, which names the
 * workspace or says Platform, and by the navigation, which is filtered to
 * what the role may reach.
 */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    const handler = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <SkipLink />
      <RouteAnnouncer />

      <Masthead
        onOpenSearch={() => setPaletteOpen(true)}
        onOpenMenu={() => setDrawerOpen(true)}
      />

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 animate-fade-in bg-fg/40 backdrop-blur-[2px]"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 w-[min(20rem,85vw)] animate-fade-in bg-canvas shadow-overlay">
            <Sidebar mobile onNavigate={() => setDrawerOpen(false)} />
          </div>
          <IconButton
            label="Close menu"
            onClick={() => setDrawerOpen(false)}
            className="absolute right-4 top-4"
            variant="solid"
          >
            <X className="size-4" />
          </IconButton>
        </div>
      )}

      <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">
        {/* Keyed on the path so the content column re-enters on navigation.
            200ms and 6px — enough to register that the page changed, not
            enough to wait for. The masthead never moves. */}
        <div
          key={location.pathname}
          className="mx-auto w-full max-w-[1600px] animate-rise px-4 py-10 sm:px-6 lg:px-10 lg:py-14"
        >
          <Outlet />
        </div>
      </main>

      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}
