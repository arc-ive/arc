import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlatformTenantsPage } from './PlatformTenantsPage.jsx'

vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => ({
    principal: { sub: 'demo-user', roles: ['platform_administrator'] },
    isDemo: false,
  }),
}))

vi.mock('../../api/endpoints/tenants.js', () => ({
  createTenant: vi.fn().mockResolvedValue({ id: 'new-tenant', name: 'New Tenant' }),
  getUserTenants: vi.fn().mockResolvedValue([]),
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

describe('PlatformTenantsPage — tenant creation dialog focus', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('Tenant ID input retains focus while typing', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PlatformTenantsPage />)

    await user.click(screen.getByRole('button', { name: /new tenant/i }))

    const tenantIdInput = screen.getByLabelText(/tenant id/i)
    await user.click(tenantIdInput)
    await user.type(tenantIdInput, 'acme-corp')

    expect(tenantIdInput).toHaveFocus()
    expect(tenantIdInput).toHaveValue('acme-corp')
  })

  it('Tenant Name input retains focus while typing', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PlatformTenantsPage />)

    await user.click(screen.getByRole('button', { name: /new tenant/i }))

    const tenantNameInput = screen.getByLabelText(/^name/i)
    await user.click(tenantNameInput)
    await user.type(tenantNameInput, 'Acme Corporation')

    expect(tenantNameInput).toHaveFocus()
    expect(tenantNameInput).toHaveValue('Acme Corporation')
  })

  it('both inputs retain focus across sequential typing', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PlatformTenantsPage />)

    await user.click(screen.getByRole('button', { name: /new tenant/i }))

    const tenantIdInput = screen.getByLabelText(/tenant id/i)
    const tenantNameInput = screen.getByLabelText(/^name/i)

    await user.type(tenantIdInput, 'acme')
    expect(tenantIdInput).toHaveFocus()

    await user.type(tenantNameInput, 'Acme Corp')
    expect(tenantNameInput).toHaveFocus()
  })

  it('form submission works after filling both fields', async () => {
    const { createTenant } = await import('../../api/endpoints/tenants.js')
    const user = userEvent.setup()
    renderWithProviders(<PlatformTenantsPage />)

    await user.click(screen.getByRole('button', { name: /new tenant/i }))

    await user.type(screen.getByLabelText(/tenant id/i), 'test-id')
    await user.type(screen.getByLabelText(/^name/i), 'Test Tenant')

    const submitButtons = screen.getAllByRole('button', { name: /^create tenant$/i })
    const submitButton = submitButtons[submitButtons.length - 1]
    expect(submitButton).toBeEnabled()

    await user.click(submitButton)

    expect(createTenant).toHaveBeenCalledWith({
      id: 'test-id',
      name: 'Test Tenant',
      status: 'active',
    })
  })
})
