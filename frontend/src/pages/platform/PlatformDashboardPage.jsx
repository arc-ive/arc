import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Building2,
  ShieldCheck,
  Users,
} from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getHealth } from '../../api/endpoints/health.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { Card } from '../../components/ui/Card.jsx'
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
    <Badge variant={operational ? 'green' : 'red'} dot>
      {operational ? 'API operational' : 'API unreachable'}
    </Badge>
  )
}

export function PlatformDashboardPage() {
  const { principal, isDemo } = useAuth()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: !isDemo && Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="flex flex-col gap-8">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
                ARC Platform Console
              </h1>
              <Badge variant="indigo">
                <ShieldCheck className="mr-1 size-3" />
                Platform Administrator
              </Badge>
            </div>
            <p className="mt-1 text-sm text-zinc-500">
              Platform-level administration of tenants and users.
            </p>
          </div>
          <HealthPill />
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500">
              <Building2 className="size-4.5" />
            </div>
            <p className="mt-4 text-2xl font-semibold tracking-tight text-zinc-100">
              {isDemo
                ? '—'
                : userTenants.isPending
                  ? '—'
                  : userTenants.data?.length ?? '0'}
            </p>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              {isDemo
                ? 'Demo Mode — backend data unavailable'
                : 'Your tenant memberships'}
            </p>
          </div>
          <Link
            to="/platform/tenants"
            className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-indigo-400 transition-colors duration-150 hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            Manage tenants
            <ArrowUpRight className="size-3.5" />
          </Link>
        </Card>

        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500">
              <Users className="size-4.5" />
            </div>
            <p className="mt-4 text-[15px] font-semibold text-zinc-100">
              User provisioning
            </p>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              Create and manage platform users
            </p>
          </div>
          <Link
            to="/platform/users"
            className="inline-flex items-center gap-1 rounded text-[13px] font-medium text-indigo-400 transition-colors duration-150 hover:text-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            Manage users
            <ArrowUpRight className="size-3.5" />
          </Link>
        </Card>

        <Card className="flex flex-col justify-between gap-6 p-5">
          <div>
            <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500">
              <ShieldCheck className="size-4.5" />
            </div>
            <p className="mt-4 text-[15px] font-semibold text-zinc-100">
              Authorization
            </p>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              Tenant membership and roles are enforced by the backend
            </p>
          </div>
          <span className="text-[13px] text-zinc-600">
            Platform administration ≠ tenant administration
          </span>
        </Card>
      </section>

    </div>
  )
}