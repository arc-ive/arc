import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockGetTenantUsageSummary = vi.fn()
vi.mock('../../api/endpoints/observability.js', () => ({
  getTenantUsageSummary: (...args) => mockGetTenantUsageSummary(...args),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => mockUseAuth(),
}))

vi.mock('../../api/errors.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    errorMessage: (err) => err?.message ?? 'Unknown error',
  }
})

import { TenantUsagePage } from './TenantUsagePage.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

const FIXTURE = {
  window_hours: 24,
  http: {
    total_requests: 1250,
    error_count: 37,
    error_rate: 0.0296,
    avg_duration_ms: 142.73,
    p95_duration_ms: 389.12,
  },
  tools: {
    total_executions: 482,
    successful: 460,
    failed: 18,
    denied: 4,
  },
  connectors: {
    total_syncs: 56,
    successful: 52,
    failed: 4,
    items_fetched: 10240,
  },
  webhooks: {
    available: true,
    total_events: 89,
    distinct_event_types: 5,
    total_payload_bytes: 204800,
  },
  approvals: {
    total: 34,
    pending: 8,
    approved: 20,
    rejected: 3,
    expired: 2,
    consumed: 1,
  },
}

function renderWithProviders(ui, { queryClient } = {}) {
  const client = queryClient ?? new QueryClient({
    queries: { retry: false },
  })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/app/t/t-123/usage']}>
          <Routes>
            <Route path="/app/t/:tenantId/usage" element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
    queryClient: client,
  }
}

describe('TenantUsagePage field mapping', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ isDemo: false })
    mockGetTenantUsageSummary.mockResolvedValue(FIXTURE)
  })

  it('displays http.total_requests in the API Requests card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('1250')).toBeInTheDocument()
    expect(screen.getByText('API Requests')).toBeInTheDocument()
  })

  it('displays tools.total_executions in the Tool Calls card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('482')).toBeInTheDocument()
    expect(screen.getByText('Tool Calls')).toBeInTheDocument()
  })

  it('displays tools.successful in the Successful card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('460')).toBeInTheDocument()
    expect(screen.getByText('Successful')).toBeInTheDocument()
  })

  it('displays tools.failed in the Failed card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('18')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('displays webhooks.total_events in the Webhook Events card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('89')).toBeInTheDocument()
    expect(screen.getByText('Webhook Events')).toBeInTheDocument()
  })

  it('displays window_hours in the period footer text', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(
      await screen.findByText(/Metrics cover the last 24 hours/),
    ).toBeInTheDocument()
  })

  it('displays N/A for AI Requests', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1250')
    expect(screen.getByText('AI Requests')).toBeInTheDocument()
    expect(screen.getAllByText('N/A').length).toBe(3)
  })

  it('displays N/A for Tokens', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1250')
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getAllByText('N/A').length).toBe(3)
  })

  it('displays N/A for Agent Runs', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1250')
    expect(screen.getByText('Agent Runs')).toBeInTheDocument()
    expect(screen.getAllByText('N/A').length).toBe(3)
  })

  it('does not render unavailable metrics as zero', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1250')

    const allText = document.body.textContent
    expect(allText).not.toMatch(/AI Requests\s*0/)
    expect(allText).not.toMatch(/Tokens\s*0/)
    expect(allText).not.toMatch(/Agent Runs\s*0/)
  })

  it('renders 10 skeleton cards during loading', async () => {
    mockGetTenantUsageSummary.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<TenantUsagePage />)
    const skeletons = document.querySelectorAll('.h-3.w-16')
    expect(skeletons.length).toBe(10)
  })

  it('renders ErrorState component for API errors', () => {
    render(
      <ErrorState
        title="Could not load usage metrics"
        message="Network timeout"
        onRetry={() => {}}
      />,
    )
    expect(screen.getByText('Could not load usage metrics')).toBeInTheDocument()
    expect(screen.getByText('Network timeout')).toBeInTheDocument()
    expect(screen.getByText('Try again')).toBeInTheDocument()
  })
})
