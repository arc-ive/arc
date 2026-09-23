import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const mockUseAuth = vi.fn()
vi.mock('./useAuth.js', () => ({
  useAuth: () => mockUseAuth(),
}))

import { RequireAuth } from './RequireAuth.jsx'

function TestChild() {
  return <div data-testid="protected">protected content</div>
}

describe('RequireAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
    })

    render(
      <MemoryRouter>
        <RequireAuth>
          <TestChild />
        </RequireAuth>
      </MemoryRouter>,
    )

    expect(screen.getByTestId('protected')).toBeInTheDocument()
  })

  it('redirects to /login when not authenticated and not loading', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
    })

    render(
      <MemoryRouter initialEntries={['/app/t/test/knowledge']}>
        <Routes>
          <Route
            path="/app/*"
            element={
              <RequireAuth>
                <TestChild />
              </RequireAuth>
            }
          />
          <Route path="/login" element={<div data-testid="login-page">login</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    expect(screen.getByTestId('login-page')).toBeInTheDocument()
  })

  it('passes location state.from when redirecting to /login', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
    })

    let loginLocation
    render(
      <MemoryRouter initialEntries={['/app/t/test/knowledge']}>
        <Routes>
          <Route
            path="/app/*"
            element={
              <RequireAuth>
                <TestChild />
              </RequireAuth>
            }
          />
          <Route
            path="/login"
            element={
              <LoginCapture
                onCapture={(loc) => {
                  loginLocation = loc
                }}
              />
            }
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(loginLocation?.state?.from?.pathname).toBe('/app/t/test/knowledge')
  })

  it('shows loading spinner when isLoading is true', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
    })

    render(
      <MemoryRouter>
        <RequireAuth>
          <TestChild />
        </RequireAuth>
      </MemoryRouter>,
    )

    expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    expect(screen.queryByText('Sign in with Google')).not.toBeInTheDocument()
    // Loading spinner rendered (animate-spin element)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('does not redirect when isLoading is true', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
    })

    render(
      <MemoryRouter initialEntries={['/app/t/test/knowledge']}>
        <Routes>
          <Route
            path="/app/*"
            element={
              <RequireAuth>
                <TestChild />
              </RequireAuth>
            }
          />
          <Route path="/login" element={<div data-testid="login-page">login</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
  })

  it('plays the entrance once the session check resolves', () => {
    // The shape of every real sign-in: RequireAuth mounts while
    // /auth/me is still in flight, so its first render is
    // loading + unauthenticated. The entrance has to survive that first
    // render and appear when authentication lands — deciding once at
    // mount left it permanently skipped in the product while every
    // fixed-value test still passed.
    sessionStorage.clear()
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true })

    // Two distinct elements: React bails out of a re-render given the
    // same element reference, and the point here is to re-render.
    const tree = () => (
      <MemoryRouter>
        <RequireAuth>
          <TestChild />
        </RequireAuth>
      </MemoryRouter>
    )

    const { rerender } = render(tree())
    expect(document.querySelector('canvas')).not.toBeInTheDocument()

    mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false })
    rerender(tree())

    // The curtain is up, and the app is mounted underneath it so it
    // fetches while the animation runs.
    expect(document.querySelector('canvas')).toBeInTheDocument()
    expect(screen.getByTestId('protected')).toBeInTheDocument()
  })
})

function LoginCapture({ onCapture }) {
  const location = useLocation()
  onCapture(location)
  return <div data-testid="login-page">login</div>
}
