import { useCallback, useEffect, useMemo, useState } from 'react'
import client from '../api/client.js'
import { clearAuthState } from './token.js'
import { clearArcIntroSeen } from '../components/intro/useArcIntro.js'
import { SESSION_EXPIRED_EVENT } from '../api/client.js'
import { AuthContext } from './context.js'

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  // Check session on mount
  useEffect(() => {
    // Check if we have a session by calling /auth/me via the shared API client
    // which uses the configured VITE_API_BASE_URL and withCredentials.
    client.get('/auth/me')
      .then((res) => {
        setSession(res.data)
        setLoading(false)
      })
      .catch(() => {
        setSession(null)
        setLoading(false)
      })
  }, [])

  // Listen for session expiry events
  useEffect(() => {
    const onSessionExpired = () => {
      setSession(null)
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
  }, [])

  const signIn = useCallback(() => {
    // For Google OIDC, the user is redirected to /auth/google
    // Derive the base URL from VITE_API_BASE_URL, defaulting to /api
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
    window.location.href = `${base}/auth/google`
  }, [])

  const devSignIn = useCallback(async (userId) => {
    // Development-only: authenticate as a reference user via dev auth endpoint.
    // The POST creates a real server-side session and sets cookies.
    // Then we call /auth/me to populate the session state.
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
    const res = await fetch(`${base}/internal/dev/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
      credentials: 'include',
    })
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail || 'Login failed'
      throw new Error(detail)
    }
    // Session cookies are now set — fetch the canonical /auth/me response
    const meRes = await fetch(`${base}/auth/me`, { credentials: 'include' })
    if (!meRes.ok) throw new Error('Failed to load profile')
    const sessionData = await meRes.json()
    setSession(sessionData)
    setLoading(false)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await client.post('/auth/logout')
    } catch {
      // Ignore errors — clear client state regardless
    }
    clearAuthState()
    // sessionStorage is per-tab and survives the navigation below, so the
    // "entrance already played" flag would otherwise outlive the session
    // it describes and deny the next person to sign in on this tab.
    clearArcIntroSeen()
    setSession(null)
    window.location.href = '/login'
  }, [])

  const principal = useMemo(() => {
    if (session) {
      return {
        sub: session.user_id,
        exp: null, // Session expiry is managed server-side
      }
    }
    return null
  }, [session])

  const value = useMemo(
    () => ({
      session,
      principal,
      isAuthenticated: Boolean(session),
      isLoading: loading,
      signIn,
      devSignIn,
      signOut,
    }),
    [session, principal, loading, signIn, devSignIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
