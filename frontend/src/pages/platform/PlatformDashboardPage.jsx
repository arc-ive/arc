import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { cn } from '../../lib/cn.js'
import {
  ArrowUpRight,
} from 'lucide-react'
import { getHealth } from '../../api/endpoints/health.js'
import { queryKeys } from '../../api/queryKeys.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'

function HealthPill() {
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: getHealth,
    refetchInterval: 30000,
    retry: 1,
  })

  if (health.isPending) {
    return <Skeleton className="h-6 w-28" />
  }

  const operational = health.data?.status === 'ok'

  return (
    <Badge variant={operational ? 'success' : 'danger'} dot>
      {operational ? 'API operational' : 'API unreachable'}
    </Badge>
  )
}

function ConsoleLink({ to, label, description, figure, figureLabel }) {
  return (
    <Link
      to={to}
      className={cn(
        'group flex items-start justify-between gap-6 border-b border-line py-5',
        'transition-colors duration-150 hover:bg-surface-sunk/60',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
      )}
    >
      <span className="min-w-0">
        <span className="type-display block text-[1.25rem] leading-snug text-fg">
          {label}
        </span>
        <span className="measure mt-0.5 block text-[13.5px] leading-relaxed text-fg-muted">
          {description}
        </span>
        {figure && (
          <span className="mt-2 block text-[12.5px] text-fg-muted">
            <span className="tabular-nums text-fg">{figure}</span> {figureLabel}
          </span>
        )}
      </span>
      <ArrowUpRight className="mt-1 size-4 shrink-0 text-fg-muted transition-transform duration-150 group-hover:-translate-y-0.5 group-hover:text-fg" />
    </Link>
  )
}

export function PlatformDashboardPage() {
  return (
    <div className="flex flex-col gap-12">
      <PageHeader
        title="Platform"
        description="Administration of the Arc platform itself — the workspaces on it and the people who can reach them."
        actions={<HealthPill />}
      />

      {/* Two destinations, not three cards. The third used to explain the
          authorization model back at the administrator ("Platform
          administration ≠ tenant administration"), which is architecture,
          not a control — and the plane they are standing on now says it. */}
      <section className="grid border-t border-line sm:grid-cols-2 sm:gap-x-12">
        <ConsoleLink
          to="/platform/tenants"
          label="Workspaces"
          description="Every workspace on this platform, and the people in each."
        />
        <ConsoleLink
          to="/platform/users"
          label="People"
          description="Everyone provisioned on the platform, across all workspaces."
        />
      </section>

    </div>
  )
}