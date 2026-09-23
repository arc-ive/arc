import { Fragment } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronRight, Home } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/useAuth.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { tenantBreadcrumbLabels } from './navigation.js'

const staticLabels = {
  platform: 'Platform',
  dashboard: 'Dashboard',
  profile: 'Profile',
  tenants: 'Tenants',
  users: 'Users',
  connectors: 'Connectors',
  agents: 'Agents',
  observability: 'Observability',
  ...tenantBreadcrumbLabels,
}

export function Breadcrumbs() {
  const location = useLocation()
  const { principal } = useAuth()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  const segments = location.pathname
    .split('/')
    .filter(Boolean)
    .map((segment, index, all) => ({
      segment,
      path: `/${all.slice(0, index + 1).join('/')}`,
    }))

  const tenantIndex = segments.findIndex((s) => s.segment === 't')
  const tenantId = tenantIndex >= 0 ? segments[tenantIndex + 1]?.segment : null
  const tenant = userTenants.data?.find((t) => t.id === tenantId)

  const items = segments
    .map(({ segment, path }, index) => {
      let label = segment
      let href = path
      const isLast = index === segments.length - 1

      if (segment === 't') {
        label = 'Tenants'
        href = '/app/t'
      } else if (segment === tenantId) {
        label = tenant?.name ?? tenantId
      } else if (staticLabels[segment]) {
        label = staticLabels[segment]
      } else if (segment === 'new') {
        label = path.includes('/knowledge/') ? 'New document' : 'New'
      } else if (index > tenantIndex && path.includes('/knowledge/')) {
        label = 'Document'
      } else if (index > tenantIndex && path.includes('/skills/')) {
        label = 'Skill'
      }

      return { label, href, isLast }
    })
    .filter((item) => item.label !== 'app' && item.href !== '/app')

  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1">
      <Link
        to="/app"
        className="flex items-center rounded text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        aria-label="Home"
      >
        <Home className="size-4" />
      </Link>
      {items.map((item) => (
        <Fragment key={item.href}>
          <ChevronRight className="size-3.5 shrink-0 text-line-strong" aria-hidden />
          {item.isLast ? (
            <span className="truncate text-[13px] font-medium text-fg">
              {item.label}
            </span>
          ) : (
            <Link
              to={item.href}
              className="truncate rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
            >
              {item.label}
            </Link>
          )}
        </Fragment>
      ))}
    </nav>
  )
}