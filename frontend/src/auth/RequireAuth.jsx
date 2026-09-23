import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './useAuth.js'
import { FullPageLoader } from '../components/ui/FullPageLoader.jsx'

export function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <FullPageLoader label="Checking your session" />
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children
}