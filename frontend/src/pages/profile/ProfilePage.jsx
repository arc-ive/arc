import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth.js'
import { useMe } from '../../auth/useMe.js'
import { decodeJwt } from '../../auth/jwt.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { formatDateTime, relativeTime } from '../../lib/format.js'

function ClaimRow({ label, value, mono = true }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <dt className="shrink-0 text-[13px] text-zinc-500">{label}</dt>
      <dd
        className={mono ? 'truncate font-mono text-xs text-zinc-300' : 'text-right text-xs text-zinc-300'}
      >
        {value ?? '—'}
      </dd>
    </div>
  )
}

const ROLE_LABELS = {
  platform_administrator: 'Platform Administrator',
  company_administrator: 'Company Administrator',
  operations_user: 'Operations User',
  employee: 'Employee',
}

export function ProfilePage() {
  const { token, principal, isDemo, signOut } = useAuth()
  const navigate = useNavigate()
  const me = useMe()
  const claims = token ? decodeJwt(token) : null

  const handleSignOut = () => {
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
          Profile
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Your identity, session, and authorized context. The authorized
          context is reported by the backend — the frontend never assumes
          what you can do.
        </p>
      </section>

      <Card>
        <CardHeader
          title="Identity"
          description="The identity used to authenticate every request."
        />
        <CardContent>
          <div className="flex items-center gap-3">
            <Avatar name={principal?.sub} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-zinc-100">
                {principal?.sub}
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {isDemo && (
                  <Badge variant="cyan" dot>
                    Demo session
                  </Badge>
                )}
                <Badge variant="neutral" size="sm">
                  From JWT sub claim
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
                <span className="text-[13px] text-zinc-500">Application role</span>
                {me.data?.role ? (
                  <Badge variant="indigo">
                    {ROLE_LABELS[me.data.role] ?? me.data.role}
                  </Badge>
                ) : (
                  <Badge variant="neutral">None assigned</Badge>
                )}
                {me.data?.is_demo && (
                  <Badge variant="cyan" size="sm">
                    Demo — no backend context
                  </Badge>
                )}
              </div>
              <div>
                <p className="mb-1.5 text-[13px] text-zinc-500">
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
                    <p className="text-xs text-zinc-600">
                      No matrix permissions — self-scoped operations only.
                    </p>
                  )}
                </div>
              </div>
              <div>
                <p className="mb-1.5 text-[13px] text-zinc-500">
                  Tenant memberships
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {me.data?.memberships?.length ? (
                    me.data.memberships.map((membership) => (
                      <Badge key={membership.tenant_id} variant="neutral" size="sm">
                        <span className="font-mono">{membership.tenant_id}</span>
                        <span className="text-zinc-600">·</span>
                        {membership.role}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-xs text-zinc-600">
                      No tenant memberships.
                    </p>
                  )}
                </div>
              </div>
              <p className="text-xs leading-relaxed text-zinc-600">
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
          description="Unverified token claims, decoded client-side. The backend validates signatures and permissions on every request."
        />
        <CardContent>
          <dl className="divide-y divide-zinc-800/60">
            <ClaimRow label="Expires" value={principal?.exp ? formatDateTime(principal.exp) : '—'} />
            {principal?.exp && (
              <ClaimRow label="Time remaining" value={relativeTime(principal.exp)} mono={false} />
            )}
            <ClaimRow label="Issued at (iat)" value={claims?.iat ? formatDateTime(claims.iat * 1000) : '—'} />
            <ClaimRow label="Issuer (iss)" value={claims?.iss ?? '—'} />
            <ClaimRow label="Audience (aud)" value={claims?.aud ?? '—'} />
            <ClaimRow label="Stored in" value="sessionStorage (browser session)" mono={false} />
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Session controls"
          description="End your session and clear the stored token."
        />
        <CardContent>
          <p className="mb-4 text-[13px] leading-relaxed text-zinc-500">
            Signing out removes the access token from this browser session
            and returns you to the login page. The backend does not have a
            revocation endpoint yet, so sign-out is local.
          </p>
          <div className="flex items-center gap-2">
            <Button variant="danger" onClick={handleSignOut}>
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}