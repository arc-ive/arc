import { render, screen, waitFor } from '@testing-library/react'
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
  // Issue #223: the backend has always returned these; the page ignored them.
  llm: {
    total_calls: 312,
    total_tokens: 48210,
    avg_latency_ms: 812.4,
    total_cost_usd: 1.2345,
    unknown_cost_records: 0,
    cost_coverage: 'full',
  },
  agent_runs: {
    total_runs: 27,
    succeeded: 21,
    failed: 4,
    approval_required: 2,
    max_steps_reached: 0,
  },
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
  // `queries` must sit under `defaultOptions`; without it retries were
  // never actually disabled in these tests.
  const client = queryClient ?? new QueryClient({
    defaultOptions: { queries: { retry: false, networkMode: 'always' } },
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
    mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
    mockGetTenantUsageSummary.mockResolvedValue(FIXTURE)
  })

  it('displays http.total_requests in the API Requests card', async () => {
    renderWithProviders(<TenantUsagePage />)
    expect(await screen.findByText('1,250')).toBeInTheDocument()
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

  it('displays llm.total_calls in the AI Requests card', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText('AI Requests')).toBeInTheDocument()
    expect(screen.getByText('312')).toBeInTheDocument()
    // The defect: three tiles hardcoded "N/A" / "Not tracked".
    expect(screen.queryByText('Not tracked')).not.toBeInTheDocument()
  })

  it('displays llm.total_tokens in the Tokens card', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getByText('48,210')).toBeInTheDocument()
  })

  it('displays agent_runs.total_runs in the Agent Runs card', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText('Agent Runs')).toBeInTheDocument()
    expect(screen.getByText('27')).toBeInTheDocument()
  })

  it('does not render unavailable metrics as zero', async () => {
    // A metric the backend did not report must read as unavailable, never
    // as a fabricated 0 that looks like a real measurement.
    mockGetTenantUsageSummary.mockResolvedValue({
      ...FIXTURE,
      llm: undefined,
      agent_runs: undefined,
    })
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')

    const allText = document.body.textContent
    expect(allText).not.toMatch(/AI Requests\s*0/)
    expect(allText).not.toMatch(/Tokens\s*0/)
    expect(allText).not.toMatch(/Agent Runs\s*0/)
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
  })

  it('renders a skeleton card per metric tile during loading', async () => {
    mockGetTenantUsageSummary.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<TenantUsagePage />)
    const skeletons = document.querySelectorAll('.h-3.w-16')
    expect(skeletons.length).toBe(8)
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

/**
 * Issue #223: the page reported metrics the backend does track as
 * "Not tracked". These cover the distinction the issue asks for —
 * a real zero, a genuinely absent metric, and a failed request.
 */
describe('TenantUsagePage metric honesty (Issue #223)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
    mockGetTenantUsageSummary.mockResolvedValue(FIXTURE)
  })

  it('renders a measured zero as 0, not as unavailable', async () => {
    mockGetTenantUsageSummary.mockResolvedValue({
      ...FIXTURE,
      llm: {
        total_calls: 0,
        total_tokens: 0,
        avg_latency_ms: 0,
        total_cost_usd: null,
        unknown_cost_records: 0,
        cost_coverage: 'none',
      },
      agent_runs: { total_runs: 0, succeeded: 0, failed: 0, approval_required: 0, max_steps_reached: 0 },
    })
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')

    // A tenant with no AI activity has measured zeroes, not missing data.
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('Not tracked')).not.toBeInTheDocument()
  })

  it('shows cost when coverage is full', async () => {
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText('AI Cost')).toBeInTheDocument()
    expect(screen.getByText('$1.23')).toBeInTheDocument()
  })

  it('flags partial cost coverage instead of presenting it as complete', async () => {
    mockGetTenantUsageSummary.mockResolvedValue({
      ...FIXTURE,
      llm: { ...FIXTURE.llm, total_cost_usd: 0.5, unknown_cost_records: 9, cost_coverage: 'partial' },
    })
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText(/Partial: 9 call\(s\) without pricing/)).toBeInTheDocument()
  })

  it('explains an unavailable cost rather than showing a fake zero', async () => {
    mockGetTenantUsageSummary.mockResolvedValue({
      ...FIXTURE,
      llm: { ...FIXTURE.llm, total_calls: 0, total_cost_usd: null, cost_coverage: 'none' },
    })
    renderWithProviders(<TenantUsagePage />)
    await screen.findByText('1,250')
    expect(screen.getByText('No LLM calls in this window')).toBeInTheDocument()
  })

  it('renders an error state on API failure, never "Not tracked"', async () => {
    mockGetTenantUsageSummary.mockRejectedValue(new Error('boom'))
    renderWithProviders(<TenantUsagePage />)

    await waitFor(() =>
      expect(screen.getByText('Could not load usage metrics')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Not tracked')).not.toBeInTheDocument()
  })
})
