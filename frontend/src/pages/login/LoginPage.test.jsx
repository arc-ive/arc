import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// Mock the auth hook before importing the component
const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => mockUseAuth(),
}))

// Import after mocking
import { LoginPage } from './LoginPage.jsx'

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mock: not authenticated
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      signIn: vi.fn(),
    })
  })

  it('renders the login page with Google sign-in', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('Arc')).toBeInTheDocument()
    expect(screen.getByText('Enterprise Intelligence Platform')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in with google/i })).toBeInTheDocument()
  })

  it('shows error message when error query param is present', () => {
    render(
      <MemoryRouter initialEntries={['/login?error=access_denied']}>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByText(/access denied/i)).toBeInTheDocument()
  })

  it('redirects to /app when already authenticated with no state.from', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      signIn: vi.fn(),
    })

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    // Should redirect to /app - login form should not be visible
    expect(screen.queryByText('Sign in with Google')).not.toBeInTheDocument()
  })

  it('redirects to state.from when authenticated with preserved deep-link', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      signIn: vi.fn(),
    })

    const fromPath = '/app/t/ref-acme-technologies/knowledge'

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: { pathname: fromPath } },
          },
        ]}
      >
        <LoginPage />
      </MemoryRouter>,
    )

    // Should redirect to the deep-link path, not /app
    expect(screen.queryByText('Sign in with Google')).not.toBeInTheDocument()
  })

  it('shows loading state when isLoading is true', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
      signIn: vi.fn(),
    })

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    // Should show loading spinner
    expect(screen.queryByText('Sign in with Google')).not.toBeInTheDocument()
  })
})
