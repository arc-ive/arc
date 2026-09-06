import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock all dependencies before importing the component
vi.mock('../../api/client.js', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../api/endpoints/memberships.js', () => ({
  createTenantMembership: vi.fn(),
  deleteTenantMembership: vi.fn(),
}))

vi.mock('../../api/endpoints/users.js', () => ({
  getTenantUsers: vi.fn().mockResolvedValue([]),
}))

vi.mock('../../api/errors.js', () => ({
  errorMessage: (err) => err?.message || 'Unknown error',
}))

vi.mock('../../lib/format.js', () => ({
  formatDate: (date) => new Date(date).toLocaleDateString(),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: (...args) => mockUseAuth(...args),
}))

import { TenantUsersPage } from './TenantUsersPage.jsx'

function renderWithProviders(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/tenants/t-123/users']}>
        <Routes>
          <Route path="/tenants/:tenantId/users" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TenantUsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({
      isDemo: false,
      user: { user_id: 'test-user', role: 'platform_administrator', permissions: ['membership:create'] },
    })
  })

  it('renders the page title', async () => {
    renderWithProviders(<TenantUsersPage />)

    expect(screen.getByText('Tenant users')).toBeInTheDocument()
  })

  it('shows empty state when no users exist', async () => {
    renderWithProviders(<TenantUsersPage />)

    const emptyText = await screen.findByText('No users in this tenant')
    expect(emptyText).toBeInTheDocument()
  })

  it('shows Add member button', async () => {
    renderWithProviders(<TenantUsersPage />)

    const addButton = await screen.findByText('Add member')
    expect(addButton).toBeInTheDocument()
  })

  it('disables Add member button in demo mode', async () => {
    mockUseAuth.mockReturnValue({
      isDemo: true,
      user: null,
    })

    renderWithProviders(<TenantUsersPage />)

    const addButton = await screen.findByText('Add member')
    expect(addButton.closest('button')).toBeDisabled()
  })
})
