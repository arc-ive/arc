import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, UserCircle2 } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useDismissable } from '../../lib/useDismissable.js'
import { cn } from '../../lib/cn.js'
import { Avatar } from '../ui/Avatar.jsx'

export function UserMenu() {
  const { principal, signOut, isDemo } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useDismissable(ref, () => setOpen(false), open)

  const handleSignOut = () => {
    setOpen(false)
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          'flex h-9 items-center gap-2 rounded-lg border border-transparent px-1.5 transition-colors duration-150 hover:border-zinc-800 hover:bg-zinc-900',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
        )}
      >
        <Avatar name={principal?.sub} size="sm" />
        <span className="hidden max-w-28 truncate text-[13px] font-medium text-zinc-300 sm:block">
          {principal?.sub}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          aria-label="User menu"
          className="absolute right-0 top-11 z-40 w-60 overflow-hidden rounded-xl border border-zinc-800 bg-raised shadow-overlay animate-scale-in"
        >
          <div className="flex items-center gap-2.5 border-b border-zinc-800/70 px-3.5 py-3">
            <Avatar name={principal?.sub} />
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium text-zinc-200">
                {principal?.sub}
              </p>
              <p className="text-[11px] text-zinc-500">
                {isDemo ? 'Development demo session' : 'Signed in via session'}
              </p>
            </div>
          </div>
          <div className="p-1">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                navigate('/app/profile')
              }}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-zinc-400 transition-colors duration-100 hover:bg-zinc-900 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
            >
              <UserCircle2 className="size-4 text-zinc-600" />
              Profile &amp; session
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={handleSignOut}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-red-400 transition-colors duration-100 hover:bg-red-950/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
            >
              <LogOut className="size-4" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}