import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
} from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { PERMISSIONS } from '../../auth/permissions.js'
import { getUserTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { cn } from '../../lib/cn.js'

/**
 * Employee workspace home.
 *
 * The employee's primary purpose is Unified Intelligence: ask questions,
 * browse approved company knowledge, and follow approved procedures.
 * Everything is tenant-scoped and backend-authorized.
 */
export function EmployeeHomePage() {
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { can } = useCapabilities()

  const userTenants = useQuery({
    queryKey: queryKeys.userTenants(principal?.sub),
    queryFn: () => getUserTenants(principal.sub),
    enabled: Boolean(principal),
    staleTime: 5 * 60 * 1000,
  })

  // An employee holds knowledge:read (ROLE_PERMISSIONS in
  // security/authorization.py), but the gate is read from capabilities
  // rather than assumed from the role.
  const canReadKnowledge = can(PERMISSIONS.KNOWLEDGE_READ)

  const tenant = userTenants.data?.find((t) => t.id === tenantId)
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  return (
    /* An employee's landing page.
     *
     * It used to show them their own session: User ID, Application role,
     * Expires / "No expiry claim", under a heading reading "Identity
     * derived from your session token". That is a debug panel, and
     * ARC_UX_SPEC.md §1 rules it out — an employee has no use for a token
     * claim, and "the backend decides what you are authorized to access"
     * explains Arc's architecture to someone who wanted to ask a question.
     *
     * What is left is the one thing they came for. */
    <div className="grid gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0">
        <h1 className="type-display-lg text-fg">
          {tenant?.name ?? <Skeleton className="h-10 w-72" />}
        </h1>

        <Link
          to={`${tenantPrefix}/ask`}
          className={cn(
            'group mt-10 block border-t border-fg pt-6',
            'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary',
          )}
        >
          <span className="type-display block text-fg">Ask Arc</span>
          <span className="measure mt-2 block text-[15px] leading-relaxed text-fg-muted">
            Ask anything about your company. Arc answers from approved company
            knowledge and shows the documents it used.
          </span>
          <span className="mt-4 inline-flex items-center gap-1.5 text-[14px] font-medium text-accent">
            Ask a question
            <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-1" />
          </span>
        </Link>

        {canReadKnowledge && (
          <Link
            to={`${tenantPrefix}/knowledge`}
            className={cn(
              'group mt-8 flex items-baseline justify-between gap-6 border-t border-line pt-5',
              'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary',
            )}
          >
            <span className="min-w-0">
              <span className="block text-[15px] font-medium text-fg">
                Company Brain
              </span>
              <span className="measure mt-0.5 block text-[13.5px] leading-relaxed text-fg-muted">
                Browse the documents Arc answers from.
              </span>
            </span>
            <ArrowRight className="size-4 shrink-0 self-center text-fg-muted transition-transform duration-200 group-hover:translate-x-1 group-hover:text-fg" />
          </Link>
        )}
      </div>

      <aside className="min-w-0">
        <h2 className="type-label text-fg-muted">Your access</h2>
        <dl className="mt-3 border-t border-line">
          <div className="flex items-baseline justify-between gap-4 border-b border-line py-3">
            <dt className="text-[13px] text-fg-muted">Workspace</dt>
            <dd className="min-w-0 truncate text-[13.5px] text-fg">
              {tenant?.name ?? '—'}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4 border-b border-line py-3">
            <dt className="text-[13px] text-fg-muted">Role</dt>
            <dd className="text-[13.5px] text-fg">Employee</dd>
          </div>
        </dl>
        <p className="measure-tight mt-4 text-[12.5px] leading-relaxed text-fg-muted">
          Arc shows you only what your role allows, and checks again on the
          server every time you act.
        </p>
      </aside>
    </div>
  )
}
