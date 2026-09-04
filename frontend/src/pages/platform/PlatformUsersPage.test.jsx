import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlatformUsersPage } from './PlatformUsersPage.jsx'

vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => ({
    principal: { sub: 'demo-user', roles: ['platform_administrator'] },
    isDemo: false,
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
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('PlatformUsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page title', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    renderWithProviders(<PlatformUsersPage />)

    expect(screen.getByText('Users')).toBeInTheDocument()
  })

  it('shows empty state when no users exist', async () => {
    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    renderWithProviders(<PlatformUsersPage />)

    const emptyText = await screen.findByText('No users provisioned yet')
    expect(emptyText).toBeInTheDocument()
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

    expect(await screen.findByText('alice@example.com')).toBeInTheDocument()
    expect(screen.getByText('bob@example.com')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('disables New user button in demo mode', async () => {
    vi.doMock('../../auth/useAuth.js', () => ({
      useAuth: () => ({
        principal: null,
        isDemo: true,
      }),
    }))

    const { listPlatformUsers } = await import('../../api/endpoints/users.js')
    listPlatformUsers.mockResolvedValue([])

    const { PlatformUsersPage: DemoPage } = await import(
      './PlatformUsersPage.jsx'
    )
    renderWithProviders(<DemoPage />)

    const addButton = await screen.findByText('New user')
    expect(addButton.closest('button')).toBeDisabled()

    vi.doUnmock('../../auth/useAuth.js')
  })
})
