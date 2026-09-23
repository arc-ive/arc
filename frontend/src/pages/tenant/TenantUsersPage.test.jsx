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
      user: { user_id: 'test-user', role: 'platform_administrator', permissions: ['membership:create'] },
    })
  })

  it('names the page for the people on it, not the data model', async () => {
    // Was "Tenant users", with "as authorized by the backend" underneath.
    // A person in their own workspace is not in "a tenant" — that is the
    // platform's word for a customer, and ARC_UX_SPEC.md §1 keeps
    // implementation vocabulary out of the product. The nav has always
    // said "People"; the page now agrees with it.
    renderWithProviders(<TenantUsersPage />)

    expect(screen.getByRole('heading', { level: 1, name: 'People' })).toBeInTheDocument()
    expect(screen.queryByText(/tenant users/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/authorized by the backend/i)).not.toBeInTheDocument()
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

  it('renders the member list for a user who can read the workspace', async () => {
    // Replaces a demo-mode test. Demo Mode is gone (PR-2 decision D4).
    // Reaching this page at all now requires tenant:read, enforced by the
    // route guard, so the page itself no longer has a disabled variant.
    renderWithProviders(<TenantUsersPage />)
    expect(await screen.findByText('Add member')).toBeInTheDocument()
  })
})
