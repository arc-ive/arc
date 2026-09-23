import { useAuth } from '../../auth/useAuth.js'
import { useMe } from '../../auth/useMe.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

const ROLE_LABELS = {
  platform_administrator: 'Platform Administrator',
  company_administrator: 'Company Administrator',
  operations_user: 'Operations User',
  employee: 'Employee',
}

/**
 * What a role actually lets someone do, in a sentence.
 *
 * This replaces a grid of 23 permission strings (`agent:execute`,
 * `knowledge:read`, `connector:manage_credentials`…). Those are the
 * backend's own matrix keys: ARC_UX_SPEC.md §1 rules raw internals out of
 * the UI, and §5 of the redesign brief puts it directly — backend
 * permissions should power the UI, not become the UI.
 *
 * The sentences are derived from ROLE_PERMISSIONS in
 * src/arc/security/authorization.py. They describe; they do not decide.
 * Every gate in the app still reads `useCapabilities()`, which reads the
 * backend's matrix, and every operation is independently authorised
 * server-side.
 */
const ROLE_SUMMARY = {
  platform_administrator:
    'Administers the Arc platform itself — tenants, users and platform-wide telemetry.',
  company_administrator:
    'Full control of this workspace: its knowledge, capabilities, people and settings.',
  operations_user:
    'Runs and oversees day-to-day work — knowledge, skills, approvals and operational telemetry.',
  employee:
    'Reads the Company Brain and asks Arc questions grounded in it.',
}

export function ProfilePage() {
  const { principal, signOut } = useAuth()
  const { isEmployee } = useCapabilities()
  const me = useMe()

  const name = me.data?.display_name || principal?.sub
  const role = me.data?.role
  const memberships = me.data?.memberships ?? []

  if (me.isError) {
    return (
      <div className="measure">
        <ErrorState
          title="Could not load your account"
          message="Arc could not read your profile. Try again, or sign out and back in."
          onRetry={() => me.refetch()}
        />
      </div>
    )
  }

  return (
    <div className="grid gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="min-w-0">
        <PageHeader
          title="Your account"
          description="Who you are in Arc, and the access that comes with it."
        />

        {/* Identity leads, at the size a person's name deserves — this is a
            page about someone, not a dump of their claims. */}
        <section className="mt-10 flex items-center gap-5">
          <Avatar name={name} size="lg" />
          <div className="min-w-0">
            {me.isPending ? (
              <Skeleton className="h-8 w-56" />
            ) : (
              <h2 className="type-display truncate text-fg">{name}</h2>
            )}
            {me.data?.email && (
              <p className="mt-1 truncate text-[15px] text-fg-muted">
                {me.data.email}
              </p>
            )}
          </div>
        </section>

        <section className="mt-12">
          <h2 className="type-label text-fg-muted">Access</h2>
          <dl className="mt-3 border-t border-line">
            <Row label="Role">
              {me.isPending ? (
                <Skeleton className="h-5 w-40" />
              ) : (
                <>
                  <span className="text-fg">
                    {ROLE_LABELS[role] ?? 'No application role'}
                  </span>
                  {ROLE_SUMMARY[role] && (
                    <p className="measure mt-1.5 text-[13.5px] leading-relaxed text-fg-muted">
                      {ROLE_SUMMARY[role]}
                    </p>
                  )}
                </>
              )}
            </Row>

            <Row label="Workspaces">
              {memberships.length === 0 ? (
                <span className="text-fg-muted">
                  You are not a member of any workspace.
                </span>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {memberships.map((m) => (
                    <li key={m.tenant_id} className="flex flex-wrap items-baseline gap-x-3">
                      <span className="text-fg">{m.tenant_id}</span>
                      <span className="type-label text-fg-muted">{m.role}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Row>
          </dl>

          <p className="measure mt-4 text-[13px] leading-relaxed text-fg-muted">
            Arc shows you only what your role allows. Every action is checked
            again on the server when you take it — what you can see here is
            never what decides it.
          </p>
        </section>
      </div>

      {/* Session and its one destructive control sit in the margin: needed,
          rarely, and never the reason you opened this page. */}
      <aside className="min-w-0 lg:pt-2">
        <h2 className="type-label text-fg-muted">Session</h2>
        <dl className="mt-3 border-t border-line">
          <Row label="Signed in as" compact>
            <span className="type-data break-all text-fg-subtle">
              {principal?.sub ?? '—'}
            </span>
          </Row>
          <Row label="Managed by" compact>
            <span className="text-fg-subtle">
              Arc — server-managed, HTTP-only
            </span>
          </Row>
        </dl>

        <div className="mt-6">
          <Button variant="danger" onClick={signOut}>
            Sign out
          </Button>
          <p className="mt-2.5 text-[13px] leading-relaxed text-fg-muted">
            Ends this session everywhere it is open in this browser.
            {isEmployee && ' You will need to sign in again to ask Arc anything.'}
          </p>
        </div>
      </aside>
    </div>
  )
}

/** A labelled row on a rule. The pattern that replaced Arc's cards. */
function Row({ label, children, compact = false }) {
  return (
    <div
      className={
        compact
          ? 'flex flex-col gap-1 border-b border-line py-3'
          : 'grid grid-cols-1 gap-1 border-b border-line py-4 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-6'
      }
    >
      <dt className="type-label pt-0.5 text-fg-muted">{label}</dt>
      <dd className="min-w-0 text-[14px]">{children}</dd>
    </div>
  )
}
