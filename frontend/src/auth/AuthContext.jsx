import { useCallback, useEffect, useMemo, useState } from 'react'
import { decodeJwt, isJwtExpired } from './jwt.js'
import { clearToken, getToken, setToken } from './token.js'
import { SESSION_EXPIRED_EVENT } from '../api/client.js'
import { AuthContext } from './context.js'

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(() => {
    const stored = getToken()
    if (!stored) return null
    const payload = decodeJwt(stored)
    if (!payload || isJwtExpired(payload)) {
      clearToken()
      return null
    }
    return stored
  })

  const [demo, setDemo] = useState(() => {
    if (!import.meta.env.DEV) return false
    return sessionStorage.getItem(DEMO_KEY) === '1'
  })

  const principal = useMemo(() => {
    if (token) {
      const payload = decodeJwt(token)
      if (payload) {
        return {
          sub: String(payload.sub),
          exp: typeof payload.exp === 'number' ? payload.exp * 1000 : null,
        }
      }
    }
    if (demo) {
      return { sub: DEMO_SUB, exp: null }
    }
    return null
  }, [token, demo])

  const signIn = useCallback((nextToken) => {
    const payload = decodeJwt(nextToken)
    if (!payload) {
      throw new Error('Invalid token: not a JWT with a sub claim')
    }
    if (isJwtExpired(payload)) {
      throw new Error('Token is already expired')
    }
    setToken(nextToken)
    setTokenState(nextToken)
  }, [])

  const signOut = useCallback(() => {
    clearToken()
    sessionStorage.removeItem(DEMO_KEY)
    setTokenState(null)
    setDemo(false)
  }, [])

  /**
   * Strictly development-only. Provides local frontend navigation so the
   * authenticated UI can be inspected without a backend session. It does not
   * mint a JWT and grants no backend access — the API remains authoritative.
   */
  const enterDemo = useCallback(() => {
    if (!import.meta.env.DEV) return
    clearToken()
    sessionStorage.setItem(DEMO_KEY, '1')
    setTokenState(null)
    setDemo(true)
  }, [])

  useEffect(() => {
    if (!token) return undefined

    const onSessionExpired = () => {
      setTokenState(null)
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)

    let timer = null
    if (principal?.exp) {
      const delay = Math.max(0, principal.exp - Date.now())
      timer = window.setTimeout(() => {
        clearToken()
        setTokenState(null)
      }, delay)
    }

    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
      if (timer) window.clearTimeout(timer)
    }
  }, [token, principal?.exp])

  const value = useMemo(
    () => ({
      token,
      principal,
      isAuthenticated: Boolean(token && principal) || demo,
      isDemo: demo,
      signIn,
      signOut,
      enterDemo,
    }),
    [token, principal, demo, signIn, signOut, enterDemo],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

const DEMO_KEY = 'arc.demoMode'
const DEMO_SUB = 'demo-user'