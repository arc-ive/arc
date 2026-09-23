import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockListApprovals = vi.fn()
const mockDecideApproval = vi.fn()

vi.mock('../../api/endpoints/approvals.js', () => ({
  listApprovals: (...args) => mockListApprovals(...args),
  decideApproval: (...args) => mockDecideApproval(...args),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: (...args) => mockUseAuth(...args),
}))

const mockCan = vi.fn()
vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({ can: mockCan, role: 'company_administrator' }),
}))

import { ApprovalsPage } from './ApprovalsPage.jsx'
import { queryKeys } from '../../api/queryKeys.js'

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/t/t-123/approvals']}>
        <Routes>
          <Route path="/app/t/:tenantId/approvals" element={<ApprovalsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// Mirrors the reproduction in issue #224: three approvals, none pending.
const MOCK_APPROVALS = [
  {
    id: 'ap-approved',
    tool_name: 'check_service_health',
    tool_version: '1',
    status: 'approved',
    risk_level: 'low',
    requester_user_id: 'user-1',
    created_at: '2026-09-01T10:00:00Z',
  },
  {
    id: 'ap-rejected',
    tool_name: 'send_notification',
    tool_version: '1',
    status: 'rejected',
    risk_level: 'medium',
    requester_user_id: 'user-2',
    created_at: '2026-09-02T10:00:00Z',
  },
  {
    id: 'ap-expired',
    tool_name: 'rotate_credentials',
    tool_version: '2',
    status: 'expired',
    risk_level: 'high',
    requester_user_id: 'user-3',
    created_at: '2026-09-03T10:00:00Z',
  },
]

describe('ApprovalsPage status filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
    mockCan.mockReturnValue(true)
    // Filtering is server-side: the mock honours the status argument the
    // same way the API does, so a stale cache entry is observable.
    mockListApprovals.mockImplementation((_tenantId, { status } = {}) =>
      Promise.resolve(
        status ? MOCK_APPROVALS.filter((a) => a.status === status) : MOCK_APPROVALS,
      ),
    )
  })

  it('includes the status filter in the query key', () => {
    // Regression guard for #224: the key must change with the filter,
    // otherwise React Query serves the previous status from cache.
    expect(queryKeys.approvalsList('t-123', null)).not.toEqual(
      queryKeys.approvalsList('t-123', 'pending'),
    )
    expect(queryKeys.approvalsList('t-123', 'pending')).toContain('pending')
  })

  it('keeps the unfiltered key as a prefix so a decision invalidates every filter', () => {
    const prefix = queryKeys.approvals('t-123')
    for (const status of [null, 'pending', 'approved', 'rejected']) {
      const key = queryKeys.approvalsList('t-123', status)
      expect(key.slice(0, prefix.length)).toEqual(prefix)
    }
  })

  it('refetches with the selected status instead of serving the cached list', async () => {
    const user = userEvent.setup()
    renderWithProviders()

    expect(await screen.findByText('Check service health')).toBeInTheDocument()
    expect(mockListApprovals).toHaveBeenCalledTimes(1)
    expect(mockListApprovals).toHaveBeenLastCalledWith('t-123', { status: null })

    await user.click(screen.getByRole('button', { name: 'pending' }))

    // The bug: no second call was ever issued for the whole page lifetime.
    await waitFor(() => expect(mockListApprovals).toHaveBeenCalledTimes(2))
    expect(mockListApprovals).toHaveBeenLastCalledWith('t-123', { status: 'pending' })
  })

  it('renders only approvals matching the selected status', async () => {
    const user = userEvent.setup()
    renderWithProviders()

    expect(await screen.findByText('Check service health')).toBeInTheDocument()
    expect(screen.getByText('Send notification')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'approved' }))

    await waitFor(() =>
      expect(screen.queryByText('Send notification')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Check service health')).toBeInTheDocument()
    expect(screen.queryByText('Rotate credentials')).not.toBeInTheDocument()
  })

  it('renders an explicit empty state when the filter matches nothing', async () => {
    const user = userEvent.setup()
    renderWithProviders()

    expect(await screen.findByText('Check service health')).toBeInTheDocument()

    // None of the seeded approvals are pending — the reproduction case.
    await user.click(screen.getByRole('button', { name: 'pending' }))

    expect(await screen.findByText('No pending approvals')).toBeInTheDocument()
    expect(screen.queryByText('Check service health')).not.toBeInTheDocument()
  })

  it('returns to the full list when All is selected again', async () => {
    const user = userEvent.setup()
    renderWithProviders()

    expect(await screen.findByText('Check service health')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'approved' }))
    await waitFor(() =>
      expect(screen.queryByText('Send notification')).not.toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'All' }))

    expect(await screen.findByText('Send notification')).toBeInTheDocument()
    expect(screen.getByText('Rotate credentials')).toBeInTheDocument()
  })
})
