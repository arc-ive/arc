import { useEffect, useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { Users } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { Button } from '../../components/ui/Button.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { FullPageLoader } from '../../components/ui/FullPageLoader.jsx'

function Brand() {
  return (
    <div className="mb-10">
      <p className="type-display-lg leading-none text-fg">Arc</p>
      <p className="mt-3 text-[15px] text-fg-muted">
        Answers from your company&apos;s own knowledge.
      </p>
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
        <p className="mt-1.5 text-xs text-danger">{error}</p>
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
    /* Asymmetric rather than a card centred in a void: the name takes the
       left, the way in takes the right. Same type, ground and components
       as the rest of Arc — the first screen should already look like the
       product, not like a gate in front of it. */
    <div className="min-h-dvh bg-canvas px-6 py-12 sm:px-10">
      <div className="mx-auto grid min-h-[calc(100dvh-6rem)] w-full max-w-5xl items-center gap-x-20 gap-y-12 lg:grid-cols-2">
        <div className="min-w-0">
          <Brand />
          <p className="measure-tight text-[13.5px] leading-relaxed text-fg-muted">
            Arc reads only what your company has given it, and shows the
            documents behind every answer.
          </p>
        </div>

        <div className="min-w-0">
          <div className="flex flex-col gap-5 border-t border-fg pt-6">
            <h1 className="type-label text-fg-muted">Sign in</h1>

            {error && (
              <InlineError>
                {error === 'access_denied'
                  ? 'That Google account is not linked to an Arc user. Ask your administrator to add it.'
                  : 'Sign-in did not complete. Try again.'}
              </InlineError>
            )}

            <Button onClick={signIn} size="lg" className="w-full" disabled={isLoading}>
              <GoogleIcon />
              Sign in with Google
            </Button>

            {import.meta.env.DEV && <DevUserSelector />}
          </div>

          <p className="mt-6 text-[12.5px] leading-relaxed text-fg-muted">
            Arc checks who you are on every request. Signing in here does not
            grant access on its own.
          </p>
        </div>
      </div>
    </div>
  )
}
