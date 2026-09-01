import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LoginPage } from './LoginPage.jsx'

// Mock the auth hook
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    signIn: vi.fn(),
    enterDemo: vi.fn(),
  }),
}))

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the login form', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('Arc')).toBeInTheDocument()
    expect(screen.getByText('Enterprise Intelligence Platform')).toBeInTheDocument()
    expect(screen.getByLabelText(/session token/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('shows development-only warning', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByText(/development-only session/i)).toBeInTheDocument()
  })

  it('shows demo mode section in development environment', () => {
    // In Vite test environment, import.meta.env.DEV is true by default
    // so the demo mode section should be rendered
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByText(/no token handy/i)).toBeInTheDocument()
  })

  it('disables sign in button when token is expired', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    // Create an expired JWT (exp in the past)
    const hs256Header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    const expiredPayload = { sub: 'user-1', exp: Math.floor(Date.now() / 1000) - 1000 }
    const encoded = btoa(JSON.stringify(expiredPayload))
    const expiredToken = `${hs256Header}.${encoded}.signature`

    const textarea = screen.getByLabelText(/session token/i)
    fireEvent.change(textarea, { target: { value: expiredToken } })

    const submitButton = screen.getByRole('button', { name: /sign in/i })
    expect(submitButton).toBeDisabled()
  })
})
