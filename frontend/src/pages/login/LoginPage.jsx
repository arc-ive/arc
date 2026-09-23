import { useEffect, useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { ShieldCheck, Users } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card } from '../../components/ui/Card.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { FullPageLoader } from '../../components/ui/FullPageLoader.jsx'

function Brand() {
  return (
    <div className="mb-8 flex flex-col items-center gap-3">
      <div className="flex size-12 items-center justify-center rounded-xl border border-line bg-surface-overlay">
        <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
          <path d="M8 10.5h9a4.5 4.5 0 0 1 0 9h-3v6h-6v-15Z" fill="#e4e4e7" />
          <path d="M8 13.5h6v6H8v-6Z" fill="#6366f1" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-xl font-semibold tracking-tight text-fg">
          Arc
        </p>
        <p className="mt-0.5 text-[13px] text-fg-muted">
          Enterprise Intelligence Platform
        </p>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  )
}

function DevUserSelector() {
  const { devSignIn } = useAuth()
  const [personas, setPersonas] = useState([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
    fetch(`${base}/internal/dev/auth/reference-personas`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => setPersonas(data.personas || []))
      .catch(() => {})
  }, [])

  const handleLogin = async () => {
    if (!selected) return
    setLoading(true)
    setError(null)
    try {
      await devSignIn(selected)
    } catch (e) {
      setError(e.message)
      setLoading(false)
    }
  }

  if (personas.length === 0) return null

  return (
    <div className="mt-3 border-t border-line pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-muted">
        <Users className="size-3" />
        Development Login
      </div>
      <Select
        value={selected}
        onChange={(e) => { setSelected(e.target.value); setError(null) }}
      >
        <option value="">Select a role persona…</option>
        {personas.map((p) => (
          <option key={p.user_id} value={p.user_id}>
            {p.persona} — {p.description}
          </option>
        ))}
      </Select>
      {error && (
        <p className="mt-1.5 text-xs text-red-400">{error}</p>
      )}
      <Button
        onClick={handleLogin}
        disabled={!selected || loading}
        variant="secondary"
        size="sm"
        className="mt-2 w-full"
      >
        {loading ? 'Signing in…' : 'Sign in as reference user'}
      </Button>
    </div>
  )
}

export function LoginPage() {
  const { isAuthenticated, signIn, isLoading } = useAuth()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const error = searchParams.get('error')

  if (isAuthenticated) {
    const from = location.state?.from?.pathname
    return <Navigate to={from || '/app'} replace />
  }

  if (isLoading) {
    return (
      <FullPageLoader label="Signing you in" />
    )
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-base px-4 py-10">
      <div className="w-full max-w-md">
        <Brand />

        <Card className="overflow-hidden">
          <div className="flex flex-col gap-4 p-5">
            {error && (
              <InlineError>
                {error === 'access_denied'
                  ? 'Access denied. Your Google account is not linked to an Arc user. Please contact your administrator.'
                  : 'Authentication failed. Please try again.'}
              </InlineError>
            )}

            <Button
              onClick={signIn}
              size="lg"
              className="w-full"
              disabled={isLoading}
            >
              <GoogleIcon />
              Sign in with Google
            </Button>

            {import.meta.env.DEV && <DevUserSelector />}
          </div>
        </Card>

        <div className="mt-6 flex items-center justify-center gap-1.5 text-xs text-fg-muted">
          <ShieldCheck className="size-3.5" />
          The backend remains the source of truth for identity and access.
        </div>
      </div>
    </div>
  )
}
