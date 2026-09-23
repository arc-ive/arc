import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './useAuth.js'
import { FullPageLoader } from '../components/ui/FullPageLoader.jsx'
import { ArcIntro } from '../components/intro/ArcIntro.jsx'
import { useArcIntro } from '../components/intro/useArcIntro.js'

export function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  const { showIntro, onIntroDone } = useArcIntro(isAuthenticated)

  if (isLoading) {
    return (
      <FullPageLoader label="Checking your session" />
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  // The children mount underneath the curtain, so the application is
  // fetching and rendering while the intro plays. The intro costs the
  // user its duration only when the app would have been ready sooner —
  // it never delays a request.
  return (
    <>
      {children}
      {showIntro && <ArcIntro onDone={onIntroDone} />}
    </>
  )
}