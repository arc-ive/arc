import { useCallback, useEffect, useMemo, useState } from 'react'
import { clearAuthState, enterDemoMode, exitDemoMode, isDemoMode } from './token.js'
import { SESSION_EXPIRED_EVENT } from '../api/client.js'
import { AuthContext } from './context.js'

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [demo, setDemo] = useState(() => isDemoMode())

  // Check session on mount
  useEffect(() => {
    if (demo) {
      setLoading(false)
      return
    }

    // Check if we have a session by calling /auth/me
    fetch('/api/auth/me', { credentials: 'same-origin' })
      .then((res) => {
        if (res.ok) {
          return res.json()
        }
        throw new Error('Not authenticated')
      })
      .then((data) => {
        setSession(data)
        setLoading(false)
      })
      .catch(() => {
        setSession(null)
        setLoading(false)
      })
  }, [demo])

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
    // This function is kept for API compatibility but the actual
    // sign-in happens via server redirect
    window.location.href = '/api/auth/google'
  }, [])

  const signOut = useCallback(async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
    } catch {
      // Ignore errors — clear client state regardless
    }
    clearAuthState()
    setSession(null)
    setDemo(false)
    window.location.href = '/login'
  }, [])

  const enterDemo = useCallback(() => {
    if (!import.meta.env.DEV) return
    enterDemoMode()
    setDemo(true)
    setLoading(false)
  }, [])

  const principal = useMemo(() => {
    if (session) {
      return {
        sub: session.user_id,
        exp: null, // Session expiry is managed server-side
      }
    }
    if (demo) {
      return { sub: 'demo-user', exp: null }
    }
    return null
  }, [session, demo])

  const value = useMemo(
    () => ({
      session,
      principal,
      isAuthenticated: Boolean(session) || demo,
      isDemo: demo,
      isLoading: loading,
      signIn,
      signOut,
      enterDemo,
    }),
    [session, principal, demo, loading, signIn, signOut, enterDemo],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
