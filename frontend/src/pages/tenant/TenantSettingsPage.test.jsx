import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { queryKeys } from '../../api/queryKeys.js'

vi.mock('../../api/client.js', () => ({
  default: { get: vi.fn(), put: vi.fn() },
}))

const TENANT = {
  id: 't-123',
  name: 'Acme Technologies',
  status: 'active',
  industry: 'Technology',
  address: '1 Market Street',
  phone: '+1-555-0400',
  website: 'https://acme.example.com',
  logo_url: 'https://acme.example.com/logo.png',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const getTenant = vi.fn()
const updateTenant = vi.fn()
vi.mock('../../api/endpoints/tenants.js', () => ({
  getTenant: (...args) => getTenant(...args),
  updateTenant: (...args) => updateTenant(...args),
}))

vi.mock('../../api/errors.js', () => ({
  errorMessage: (err) => err?.message || 'Unknown error',
}))

vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => ({ principal: { sub: 'user-1' } }),
}))

vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({ can: () => true }),
}))

import { TenantSettingsPage } from './TenantSettingsPage.jsx'

const USER_TENANTS_KEY = queryKeys.userTenants('user-1')

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // Seed the list cache the Company and Overview pages read from, so the test
  // can observe whether saving actually marks it stale rather than only
  // observing that a method was called.
  queryClient.setQueryData(USER_TENANTS_KEY, [TENANT])

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/tenants/t-123/settings']}>
        <Routes>
          <Route
            path="/tenants/:tenantId/settings"
            element={<TenantSettingsPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { queryClient }
}

async function saveIndustry() {
  const industry = await screen.findByLabelText('Industry')
  fireEvent.change(industry, { target: { value: 'Healthcare' } })
  fireEvent.click(screen.getByText('Save changes'))
  await waitFor(() => expect(updateTenant).toHaveBeenCalled())
}

describe('TenantSettingsPage save invalidation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getTenant.mockResolvedValue(TENANT)
    updateTenant.mockResolvedValue({ ...TENANT, industry: 'Healthcare' })
  })

  it('marks the user-tenants list stale so the Company page refetches', async () => {
    const { queryClient } = renderPage()
    expect(queryClient.getQueryState(USER_TENANTS_KEY).isInvalidated).toBe(false)

    await saveIndustry()

    await waitFor(() =>
      expect(queryClient.getQueryState(USER_TENANTS_KEY).isInvalidated).toBe(
        true,
      ),
    )
  })

  it('still refetches the single-tenant cache it already invalidated', async () => {
    renderPage()
    await waitFor(() => expect(getTenant).toHaveBeenCalledTimes(1))

    await saveIndustry()

    // The Settings page observes this key itself, so invalidation surfaces as
    // a refetch rather than a lingering stale flag.
    await waitFor(() => expect(getTenant).toHaveBeenCalledTimes(2))
  })
})
