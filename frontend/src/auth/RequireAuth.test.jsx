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
})

function LoginCapture({ onCapture }) {
  const location = useLocation()
  onCapture(location)
  return <div data-testid="login-page">login</div>
}
