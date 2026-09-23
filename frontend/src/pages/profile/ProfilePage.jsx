import { useAuth } from '../../auth/useAuth.js'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useMe } from '../../auth/useMe.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
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

export function ProfilePage() {
  const { principal, signOut } = useAuth()
  const me = useMe()

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <section>
        <PageHeader title="Profile"
          description="Your identity, session, and authorized context. The authorized      context is reported by the backend — the frontend never assumes      what you can do." />
      </section>

      <Card>
        <CardHeader
          title="Identity"
          description="The identity used to authenticate every request."
        />
        <CardContent>
          <div className="flex items-center gap-3">
            <Avatar name={me.data?.display_name || principal?.sub} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-zinc-100">
                {me.data?.display_name || principal?.sub}
              </p>
              {me.data?.email && (
                <p className="mt-0.5 text-xs text-fg-muted">{me.data.email}</p>
              )}
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge variant="neutral" size="sm">
                  Server-managed session
                </Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Authorized context"
          description="Application role and permission matrix, as resolved by the backend (GET /auth/me)."
        />
        <CardContent>
          {me.isPending ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : me.isError ? (
            <ErrorState
              title="Could not load your authorized profile"
              message={me.error?.message ?? 'Something went wrong'}
              onRetry={() => me.refetch()}
              compact
            />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-fg-muted">Application role</span>
                {me.data?.role ? (
                  <Badge variant="accent">
                    {ROLE_LABELS[me.data.role] ?? me.data.role}
                  </Badge>
                ) : (
                  <Badge variant="neutral">None assigned</Badge>
                )}
              </div>
              <div>
                <p className="mb-1.5 text-[13px] text-fg-muted">
                  Granted permissions
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {me.data?.permissions?.length ? (
                    me.data.permissions.map((permission) => (
                      <Badge key={permission} variant="neutral" size="sm">
                        <span className="font-mono">{permission}</span>
                      </Badge>
                    ))
                  ) : (
                    <p className="text-xs text-fg-muted">
                      No matrix permissions — self-scoped operations only.
                    </p>
                  )}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-[13px] text-fg-muted">
                  Tenant memberships
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {me.data?.memberships?.length ? (
                    me.data.memberships.map((membership) => (
                      <Badge key={membership.tenant_id} variant="neutral" size="sm">
                        <span className="font-mono">{membership.tenant_id}</span>
                        <span className="text-fg-muted">·</span>
                        {membership.role}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-xs text-fg-muted">
                      No tenant memberships.
                    </p>
                  )}
                </div>
              </div>
              <p className="text-xs leading-relaxed text-fg-muted">
                These capabilities inform what this app shows you. Every
                protected operation is independently authorized by the
                backend.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Session"
          description="Server-managed session for your authenticated identity."
        />
        <CardContent>
          <dl className="divide-y divide-zinc-800/60">
            <div className="flex items-start justify-between gap-4 py-1.5">
              <dt className="shrink-0 text-[13px] text-fg-muted">Session type</dt>
              <dd className="text-right text-xs text-zinc-300">
                HttpOnly secure cookie
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4 py-1.5">
              <dt className="shrink-0 text-[13px] text-fg-muted">Session storage</dt>
              <dd className="text-right text-xs text-zinc-300">
                Server-side (PostgreSQL)
              </dd>
            </div>
            <div className="flex items-start justify-between gap-4 py-1.5">
              <dt className="shrink-0 text-[13px] text-fg-muted">Cookie attributes</dt>
              <dd className="text-right text-xs text-zinc-300">
                HttpOnly, Secure, SameSite=Lax
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Session controls"
          description="End your session and clear the server-side session."
        />
        <CardContent>
          <p className="mb-4 text-[13px] leading-relaxed text-fg-muted">
            Signing out invalidates your server-side session and clears the
            session cookie. You will need to authenticate again to access
            the platform.
          </p>
          <div className="flex items-center gap-2">
            <Button variant="danger" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
