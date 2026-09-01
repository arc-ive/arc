import { cn } from '../../lib/cn.js'

export function Tabs({ tabs, active, onChange, className, size = 'md' }) {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex items-center gap-1 rounded-lg border border-zinc-800/80 bg-zinc-900/40 p-1',
        className,
      )}
    >
      {tabs.map((tab) => {
        const isActive = tab.value === active
        return (
          <button
            key={tab.value}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.value)}
            className={cn(
              'rounded-md font-medium transition-colors duration-150 whitespace-nowrap',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-[13px]',
              isActive
                ? 'bg-zinc-800/90 text-zinc-100 shadow-sm'
                : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}