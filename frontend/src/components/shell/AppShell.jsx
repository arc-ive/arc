import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Menu, Search, X } from 'lucide-react'
import { Sidebar } from './Sidebar.jsx'
import { Breadcrumbs } from './Breadcrumbs.jsx'
import { CommandPalette } from './CommandPalette.jsx'
import { TenantSwitcher } from './TenantSwitcher.jsx'
import { UserMenu } from './UserMenu.jsx'
import { IconButton } from '../ui/IconButton.jsx'
import { Badge } from '../ui/Badge.jsx'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { cn } from '../../lib/cn.js'

function Kbd({ children }) {
  return (
    <kbd className="ml-auto rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
      {children}
    </kbd>
  )
}

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { isDemo } = useAuth()
  const { isPlatformAdministrator } = useCapabilities()
  const location = useLocation()

  const inPlatformContext = location.pathname.startsWith('/platform')
  const showTenantSwitcher = !inPlatformContext || !isPlatformAdministrator

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
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-60 shrink-0 lg:block">
        <Sidebar />
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-[2px] animate-fade-in"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 w-60 animate-fade-in">
            <Sidebar
              mobile
              onNavigate={() => setDrawerOpen(false)}
            />
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

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-800/70 bg-base/80 px-4 backdrop-blur-sm sm:px-6">
          <IconButton
            label="Open menu"
            onClick={() => setDrawerOpen(true)}
            className="lg:hidden"
          >
            <Menu className="size-4" />
          </IconButton>

          <Breadcrumbs />

          <div className="ml-auto flex items-center gap-2.5">
            {isDemo && (
              <Badge variant="info" dot className="hidden sm:inline-flex">
                Demo
              </Badge>
            )}
            {showTenantSwitcher && <TenantSwitcher />}
            <button
              type="button"
              onClick={() => setPaletteOpen(true)}
              className={cn(
                'hidden h-9 items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 text-[13px] text-fg-muted transition-colors duration-150 hover:border-zinc-700 hover:text-zinc-300 md:flex',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
              )}
            >
              <Search className="size-3.5" />
              Search
              <Kbd>⌘K</Kbd>
            </button>
            <IconButton
              label="Search"
              onClick={() => setPaletteOpen(true)}
              className="md:hidden"
            >
              <Search className="size-4" />
            </IconButton>
            <div className="mx-1 h-5 w-px bg-zinc-800" aria-hidden />
            <UserMenu />
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>

      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}