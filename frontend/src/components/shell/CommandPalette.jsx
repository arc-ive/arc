import { useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Search, CornerDownLeft } from 'lucide-react'
import { cn } from '../../lib/cn.js'
import { useTenant } from '../../tenant/useTenant.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { personalNav, platformNav, tenantNavForCapabilities } from './navigation.js'

/**
 * Rendered only while open (AppShell conditionally mounts it), so all
 * search/keyboard state starts fresh on every open.
 */
export function CommandPalette({ onClose }) {
  const navigate = useNavigate()
  const { tenantId } = useTenant()
  const { can } = useCapabilities()
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const groups = []
    const push = (group, items) => {
      const filtered = items.filter(
        (item) => !q || item.label.toLowerCase().includes(q),
      )
      if (filtered.length) groups.push({ group, items: filtered })
    }
    push('Platform', platformNav)
    if (tenantId) {
      push(
        'Tenant',
        tenantNavForCapabilities(can).map((item) => ({
          ...item,
          to: `/app/t/${encodeURIComponent(tenantId)}/${item.to}`,
        })),
      )
    }
    push('Personal', personalNav)
    return groups
  }, [query, tenantId, can])

  const flat = useMemo(() => results.flatMap((g) => g.items), [results])

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const item = flat[activeIndex]
      if (item) {
        navigate(item.to)
        onClose()
      }
    }
  }

  const handleQueryChange = (event) => {
    setQuery(event.target.value)
    setActiveIndex(0)
  }

  const go = (to) => {
    navigate(to)
    onClose()
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]"
      role="presentation"
    >
      <div
        className="fixed inset-0 bg-black/70 backdrop-blur-[2px] animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl border border-zinc-800 bg-raised shadow-overlay animate-scale-in"
      >
        <div className="flex items-center gap-2.5 border-b border-zinc-800/70 px-4">
          <Search className="size-4 shrink-0 text-fg-muted" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={handleQueryChange}
            onKeyDown={handleKeyDown}
            placeholder="Jump to a page…"
            className="h-12 w-full bg-transparent text-sm text-zinc-100 placeholder:text-fg-muted focus-visible:outline-none"
            aria-label="Search pages"
          />
          <kbd className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
            ESC
          </kbd>
        </div>

        <div ref={listRef} className="max-h-72 overflow-y-auto p-2">
          {flat.length === 0 && (
            <p className="px-3 py-8 text-center text-[13px] text-fg-muted">
              No matches for “{query}”
            </p>
          )}
          {results.map(({ group, items }) => (
            <div key={group} className="mb-1 last:mb-0">
              <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
                {group}
              </p>
              {items.map((item) => {
                const globalIndex = flat.indexOf(item)
                const isActive = globalIndex === activeIndex
                return (
                  <button
                    key={item.to}
                    data-active={isActive}
                    onMouseEnter={() => setActiveIndex(globalIndex)}
                    onClick={() => go(item.to)}
                    className={cn(
                      'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] transition-colors duration-100',
                      'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
                      isActive
                        ? 'bg-zinc-800/80 text-zinc-100'
                        : 'text-zinc-400',
                    )}
                  >
                    <item.icon
                      className={cn(
                        'size-4 shrink-0',
                        isActive ? 'text-indigo-400' : 'text-fg-muted',
                      )}
                    />
                    <span className="flex-1 truncate">{item.label}</span>
                    {isActive && (
                      <CornerDownLeft className="size-3.5 text-fg-muted" />
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}