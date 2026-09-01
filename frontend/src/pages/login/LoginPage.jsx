import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  FlaskConical,
  KeyRound,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { decodeJwt, isJwtExpired } from '../../auth/jwt.js'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Card } from '../../components/ui/Card.jsx'

function Brand() {
  return (
    <div className="mb-8 flex flex-col items-center gap-3">
      <div className="flex size-12 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900">
        <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
          <path d="M8 10.5h9a4.5 4.5 0 0 1 0 9h-3v6h-6v-15Z" fill="#e4e4e7" />
          <path d="M8 13.5h6v6H8v-6Z" fill="#6366f1" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-xl font-semibold tracking-tight text-zinc-100">
          Arc
        </p>
        <p className="mt-0.5 text-[13px] text-zinc-500">
          Enterprise Intelligence Platform
        </p>
      </div>
    </div>
  )
}

export function LoginPage() {
  const { isAuthenticated, signIn, enterDemo } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [token, setToken] = useState('')
  const [error, setError] = useState(null)

  if (isAuthenticated) {
    return <Navigate to="/app" replace />
  }

  const from = location.state?.from?.pathname ?? '/app'
  const decoded = token.trim() ? decodeJwt(token.trim()) : null
  const expired = decoded ? isJwtExpired(decoded) : false

  const handleSubmit = (event) => {
    event.preventDefault()
    const trimmed = token.trim()
    if (!trimmed) {
      setError('Enter your session token to continue.')
      return
    }
    try {
      signIn(trimmed)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDemo = () => {
    enterDemo()
    navigate('/app', { replace: true })
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-base px-4 py-10">
      <div className="w-full max-w-md">
        <Brand />

        <Card className="overflow-hidden">
          <div className="border-b border-amber-500/20 bg-amber-500/5 px-5 py-3">
            <div className="flex items-start gap-2.5">
              <Terminal className="mt-0.5 size-4 shrink-0 text-amber-400" />
              <div>
                <p className="text-[13px] font-semibold text-amber-300">
                  Development-only session
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-amber-200/60">
                  The simulated environment authenticates with a signed JWT
                  issued by the local backend (HS256, signed with your local
                  JWT_SECRET). This is not production authentication — no
                  role or tenant selection exists; the backend decides what
                  your identity is authorized to do.
                </p>
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
            <Textarea
              label="Session token"
              hint="Paste the full JWT — header.payload.signature"
              placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…"
              value={token}
              onChange={(event) => {
                setToken(event.target.value)
                setError(null)
              }}
              rows={4}
              error={error}
              className="font-mono [&_textarea]:font-mono [&_textarea]:text-xs"
              spellCheck={false}
              autoComplete="off"
            />

            {decoded && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3.5 py-3">
                <div className="mb-2 flex items-center gap-2">
                  {expired ? (
                    <Badge variant="red" dot>
                      Expired
                    </Badge>
                  ) : (
                    <Badge variant="green" dot>
                      Decoded
                    </Badge>
                  )}
                  <span className="text-[11px] uppercase tracking-wider text-zinc-600">
                    Unverified claims
                  </span>
                </div>
                <dl className="space-y-1.5 text-[13px]">
                  <div className="flex justify-between gap-4">
                    <dt className="text-zinc-500">Subject (sub)</dt>
                    <dd className="truncate font-mono text-xs text-zinc-300">
                      {String(decoded.sub)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-zinc-500">Expires (exp)</dt>
                    <dd className="font-mono text-xs text-zinc-300">
                      {decoded.exp
                        ? new Date(decoded.exp * 1000).toLocaleString()
                        : '—'}
                    </dd>
                  </div>
                  {decoded.iss && (
                    <div className="flex justify-between gap-4">
                      <dt className="text-zinc-500">Issuer (iss)</dt>
                      <dd className="truncate font-mono text-xs text-zinc-300">
                        {String(decoded.iss)}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}

            {!decoded && token.trim() && (
              <div className="flex items-start gap-2.5 rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>
                  This does not look like a valid JWT (expected three
                  dot-separated segments with a JSON payload).
                </span>
              </div>
            )}

            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={Boolean(token.trim()) && (!decoded || expired)}
            >
              <KeyRound className="size-4" />
              Sign in
            </Button>
          </form>
        </Card>

        {import.meta.env.DEV && (
          <div className="mt-8">
            <div className="flex items-center gap-3">
              <div className="h-px flex-1 bg-zinc-800" aria-hidden />
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600">
                No token handy?
              </span>
              <div className="h-px flex-1 bg-zinc-800" aria-hidden />
            </div>

            <Card className="mt-6 overflow-hidden">
              <div className="flex flex-col gap-4 p-5">
                <div className="flex items-start gap-2.5">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-cyan-400">
                    <FlaskConical className="size-4" />
                  </div>
                  <div>
                    <p className="text-[13px] font-semibold text-zinc-200">
                      Demo Mode
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                      Development only. Provides local frontend navigation so
                      you can inspect the authenticated UI — no backend
                      session, no token is minted, and no data is faked.
                      Pages that call the API will show their real loading,
                      empty, and error states.
                    </p>
                  </div>
                </div>
                <Button onClick={handleDemo}>
                  Enter Demo Mode (Development)
                </Button>
              </div>
            </Card>
          </div>
        )}

        <div className="mt-6 flex items-center justify-center gap-1.5 text-xs text-zinc-600">
          <ShieldCheck className="size-3.5" />
          The backend remains the source of truth for identity and access.
        </div>
      </div>
    </div>
  )
}