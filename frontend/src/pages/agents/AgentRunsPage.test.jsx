import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockRunAgent = vi.fn()
const mockListAgentRuns = vi.fn()
const mockGetAgentRun = vi.fn()
vi.mock('../../api/endpoints/agent.js', () => ({
  runAgent: (...a) => mockRunAgent(...a),
  listAgentRuns: (...a) => mockListAgentRuns(...a),
  getAgentRun: (...a) => mockGetAgentRun(...a),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({ useAuth: () => mockUseAuth() }))

const mockCan = vi.fn()
vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({ can: mockCan, role: 'company_administrator' }),
}))

import { AgentRunsPage } from './AgentRunsPage.jsx'

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, networkMode: 'always' } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/app/t/t-1/agents']}>
        <Routes>
          <Route path="/app/t/:tenantId/agents" element={<AgentRunsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const RUNS = {
  items: [
    {
      id: 'run-1',
      tenant_id: 't-1',
      principal_id: 'user-a',
      goal: 'investigate the production incident',
      status: 'failed',
      error_kind: 'agent_decision_unavailable',
      steps: [],
      created_at: '2026-09-22T09:44:37Z',
    },
    {
      id: 'run-2',
      tenant_id: 't-1',
      principal_id: 'user-b',
      goal: 'summarise open incidents',
      status: 'succeeded',
      error_kind: null,
      steps: [{ skill_id: 'incident-response', status: 'succeeded' }],
      created_at: '2026-09-22T08:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
}

/** Permission matrix mirroring the backend: the two capabilities differ. */
function grant({ execute = true, observability = true } = {}) {
  mockCan.mockImplementation((p) =>
    p === 'agent:execute' ? execute : p === 'observability:read' ? observability : false,
  )
}

describe('AgentRunsPage (Issue #226)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ principal: { sub: "u-1" } })
    mockListAgentRuns.mockResolvedValue(RUNS)
    grant()
  })

  it('lists past runs with status and terminal reason', async () => {
    renderPage()
    expect(await screen.findByText('investigate the production incident')).toBeInTheDocument()
    expect(screen.getByText('summarise open incidents')).toBeInTheDocument()
    // The reason is stated, not echoed. It used to read
    // "Reason: agent_decision_unavailable" — the backend's own identifier,
    // which ARC_UX_SPEC.md §1 rules out and which tells an operator nothing
    // about what to do. The sentence comes from what that kind actually
    // means in src/arc/services/agent.py: the default deterministic
    // provider carries no decision script, so the agent fails closed.
    expect(
      screen.getByText(/No decision capability is configured/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/agent_decision_unavailable/)).not.toBeInTheDocument()
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(mockListAgentRuns).toHaveBeenCalledWith('t-1', { limit: 20 })
  })

  it('starts an agent run through the real endpoint and shows the outcome', async () => {
    const user = userEvent.setup()
    mockRunAgent.mockResolvedValue({
      id: 'run-3',
      status: 'succeeded',
      error_kind: null,
      steps: [{ skill_id: 'incident-response', status: 'succeeded' }],
    })
    renderPage()
    await screen.findByText('investigate the production incident')

    await user.type(screen.getByLabelText(/goal/i), 'check service health')
    await user.click(screen.getByRole('button', { name: /start agent run/i }))

    await waitFor(() =>
      expect(mockRunAgent).toHaveBeenCalledWith('t-1', { goal: 'check service health' }),
    )
    expect(await screen.findByText('Run started')).toBeInTheDocument()
  })

  it('refreshes the run history after a run is started', async () => {
    const user = userEvent.setup()
    mockRunAgent.mockResolvedValue({ id: 'run-3', status: 'failed', error_kind: 'x', steps: [] })
    renderPage()
    await screen.findByText('investigate the production incident')
    expect(mockListAgentRuns).toHaveBeenCalledTimes(1)

    await user.type(screen.getByLabelText(/goal/i), 'a goal')
    await user.click(screen.getByRole('button', { name: /start agent run/i }))

    await waitFor(() => expect(mockListAgentRuns).toHaveBeenCalledTimes(2))
  })

  it('does not offer the control to a user without agent:execute', async () => {
    grant({ execute: false })
    renderPage()
    await screen.findByText('investigate the production incident')

    expect(screen.queryByRole('button', { name: /start agent run/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/goal/i)).not.toBeInTheDocument()
    expect(
      screen.getByText(/don't have access to start agent runs/i),
    ).toBeInTheDocument()
  })

  it('does not request run history without observability:read', async () => {
    grant({ observability: false })
    renderPage()

    expect(
      await screen.findByText(/don't have access to run history/i),
    ).toBeInTheDocument()
    expect(mockListAgentRuns).not.toHaveBeenCalled()
    // agent:execute alone still permits starting a run.
    expect(screen.getByRole('button', { name: /start agent run/i })).toBeInTheDocument()
  })

  it('renders an error state with retry when history fails', async () => {
    mockListAgentRuns.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText('Could not load agent runs')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('surfaces a failure to start the run without losing the page', async () => {
    const user = userEvent.setup()
    mockRunAgent.mockRejectedValue(new Error('provider exploded'))
    renderPage()
    await screen.findByText('investigate the production incident')

    await user.type(screen.getByLabelText(/goal/i), 'a goal')
    await user.click(screen.getByRole('button', { name: /start agent run/i }))

    expect(await screen.findByText('Could not start the agent run')).toBeInTheDocument()
    expect(screen.getByText('investigate the production incident')).toBeInTheDocument()
  })

  it('renders an empty state when the tenant has no runs', async () => {
    mockListAgentRuns.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    renderPage()
    expect(await screen.findByText('No agent runs')).toBeInTheDocument()
  })

  it('fetches the trace only when a run is expanded', async () => {
    const user = userEvent.setup()
    mockGetAgentRun.mockResolvedValue({ ...RUNS.items[1] })
    renderPage()
    await screen.findByText('investigate the production incident')
    expect(mockGetAgentRun).not.toHaveBeenCalled()

    await user.click(screen.getAllByRole('button', { name: /view trace/i })[0])
    await waitFor(() => expect(mockGetAgentRun).toHaveBeenCalledWith('t-1', 'run-1'))
  })

  it('does not request run history without observability:read', async () => {
    // Replaces a demo-mode test. Demo Mode is gone (PR-2 decision D4); the
    // real reason this page withholds history is the permission itself.
    grant({ observability: false })
    renderPage()
    expect(
      await screen.findByText(/don't have access to run history/i),
    ).toBeInTheDocument()
    expect(mockListAgentRuns).not.toHaveBeenCalled()
  })
})
