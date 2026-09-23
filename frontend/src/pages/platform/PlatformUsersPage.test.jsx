import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlatformUsersPage } from './PlatformUsersPage.jsx'

vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => ({
    principal: { sub: 'demo-user', roles: ['platform_administrator'] },
  }),
}))

vi.mock('../../api/endpoints/users.js', () => ({
  createUser: vi.fn().mockResolvedValue({
    id: 'new-user',
    email: 'new@example.com',
    username: 'new-user',
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }),
  listPlatformUsers: vi.fn(),
  getTenantUsers: vi.fn().mockResolvedValue([]),
}))

function renderWithProviders(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const wrapper = ({ children }) => (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  )
  const result = render(ui, { wrapper })
  return { ...result, queryClient }
}

describe('PlatformUsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page title', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    renderWithProviders(<PlatformUsersPage />)

    // The page is "People" on both planes now. Platform and workspace
    // directories are the same object at different scope, and calling one
    // "Users" and the other "People" made them read as two products.
    expect(
      screen.getByRole('heading', { level: 1, name: 'People' }),
    ).toBeInTheDocument()
  })

  it('shows empty state when no users exist', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    renderWithProviders(<PlatformUsersPage />)

    expect(
      await screen.findByText(/nobody has been provisioned on this platform/i),
    ).toBeInTheDocument()
  })

  it('shows New user button', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    renderWithProviders(<PlatformUsersPage />)

    const addButton = await screen.findByText('New user')
    expect(addButton).toBeInTheDocument()
  })

  it('displays user table when users exist', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([
      {
        id: 'u-1',
        email: 'alice@example.com',
        username: 'alice',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'u-2',
        email: 'bob@example.com',
        username: null,
        status: 'active',
        created_at: '2026-02-01T00:00:00Z',
        updated_at: '2026-02-01T00:00:00Z',
      },
    ])

    renderWithProviders(<PlatformUsersPage />)

    // Alice has a display name, so her name leads and her email sits
    // under it. Bob has none, so his email IS his name — printed once.
    // The old table put an em-dash in a Username column and the address
    // in another; a dash identifies nobody.
    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText('alice@example.com')).toBeInTheDocument()
    expect(screen.getAllByText('bob@example.com')).toHaveLength(1)
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })

  it('enables New user for a platform administrator', async () => {
    // Replaces a demo-mode test. Demo Mode is gone (PR-2 decision D4) and
    // with it the disabled variant it was the only cause of. Reaching this
    // page requires the platform-admin guard, so the control is live.
    renderWithProviders(<PlatformUsersPage />)
    const addButton = await screen.findByText('New user')
    expect(addButton.closest('button')).not.toBeDisabled()
  })

  describe('user creation dialog focus', () => {
    it('User ID input retains focus while typing', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      const userIdInput = screen.getByLabelText(/user id/i)
      await user.click(userIdInput)
      await user.type(userIdInput, 'u_acme_admin')

      expect(userIdInput).toHaveFocus()
      expect(userIdInput).toHaveValue('u_acme_admin')
    })

    it('Email input retains focus while typing', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      const emailInput = screen.getByLabelText(/^email/i)
      await user.click(emailInput)
      await user.type(emailInput, 'admin@acme.example')

      expect(emailInput).toHaveFocus()
      expect(emailInput).toHaveValue('admin@acme.example')
    })

    it('Username input retains focus while typing', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      const usernameInput = screen.getByLabelText(/^username/i)
      await user.click(usernameInput)
      await user.type(usernameInput, 'admin')

      expect(usernameInput).toHaveFocus()
      expect(usernameInput).toHaveValue('admin')
    })

    it('all inputs retain focus across sequential typing', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      const userIdInput = screen.getByLabelText(/user id/i)
      const emailInput = screen.getByLabelText(/^email/i)
      const usernameInput = screen.getByLabelText(/^username/i)

      await user.type(userIdInput, 'u_test')
      expect(userIdInput).toHaveFocus()

      await user.type(emailInput, 'test@example.com')
      expect(emailInput).toHaveFocus()

      await user.type(usernameInput, 'testuser')
      expect(usernameInput).toHaveFocus()
    })

    it('form submission works after filling required fields', async () => {
      const { createUser } = await import('../../api/endpoints/users.js')
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      await user.type(screen.getByLabelText(/user id/i), 'u_new_user')
      await user.type(screen.getByLabelText(/^email/i), 'new@example.com')

      const submitButtons = screen.getAllByRole('button', { name: /^create user$/i })
      const submitButton = submitButtons[submitButtons.length - 1]
      expect(submitButton).toBeEnabled()

      await user.click(submitButton)

      expect(createUser).toHaveBeenCalledWith({
        id: 'u_new_user',
        email: 'new@example.com',
        username: null,
        status: 'active',
      })
    })

    it('dialog closes and resets on cancel', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      expect(screen.getByLabelText(/user id/i)).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: /cancel/i }))

      expect(screen.queryByLabelText(/user id/i)).not.toBeInTheDocument()
    })

    it('retains input focus when parent re-renders while dialog is open', async () => {
      const user = userEvent.setup()
      const { rerender } = renderWithProviders(<PlatformUsersPage />)

      await user.click(screen.getByRole('button', { name: /new user/i }))

      const userIdInput = screen.getByLabelText(/user id/i)
      await user.click(userIdInput)
      await user.type(userIdInput, 'u_test')

      expect(userIdInput).toHaveFocus()

      // Trigger a parent re-render while the dialog is open.
      // Without the useCallback fix on handleCloseCreate, this re-render
      // creates a new onClose reference, causing Dialog's useEffect
      // [open, onClose] to re-run and steal focus via
      // dialogRef.current?.focus().
      rerender(<PlatformUsersPage />)

      // Wait for any async focus side-effects to settle (the Dialog
      // setTimeout(0) for focus).
      await act(async () => {
        await new Promise((resolve) => {
          setTimeout(resolve, 50)
        })
      })

      // The input must still have focus, not the dialog container.
      expect(userIdInput).toHaveFocus()
    })
  })
})
