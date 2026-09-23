import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockQueryIntelligence = vi.fn()
vi.mock('../../api/endpoints/intelligence.js', () => ({
  queryIntelligence: (...a) => mockQueryIntelligence(...a),
}))

vi.mock('../../api/endpoints/knowledge.js', () => ({
  getKnowledge: () => Promise.resolve([]),
}))

vi.mock('../../tenant/useTenant.js', () => ({
  useTenant: () => ({ tenantId: 't-1' }),
}))

vi.mock('../../lib/useTypewriter.js', () => ({
  useTypewriter: () => ({ text: '', done: true }),
}))

import { AskArcPage } from './AskArcPage.jsx'

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, networkMode: 'always' } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/app/t/t-1/ask']}>
        <Routes>
          <Route path="/app/t/:tenantId/ask" element={<AskArcPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function askQuestion(user, text) {
  renderPage()
  const field = await screen.findByLabelText('Ask Arc')
  await user.type(field, text)
  await user.click(screen.getByText('Ask'))
}

describe('AskArcPage — source scoping', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockQueryIntelligence.mockResolvedValue({
      answer: 'Do this.',
      citations: [],
      context_used: true,
      request_id: 'r-1',
    })
  })

  it('renders human source labels, not enum values', async () => {
    renderPage()

    expect(await screen.findByText('Incident report')).toBeInTheDocument()
    expect(screen.queryByText('incident_report')).not.toBeInTheDocument()
  })

  it('sends source_type when a source is selected', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(screen.getByLabelText('Sources'), 'incident_report')
    const field = await screen.findByLabelText('Ask Arc')
    await user.type(field, 'outage help')
    await user.click(screen.getByText('Ask'))

    await waitFor(() =>
      expect(mockQueryIntelligence).toHaveBeenCalledWith(
        't-1',
        expect.objectContaining({ source_type: 'incident_report' }),
      ),
    )
  })

  it('omits source_type when unscoped', async () => {
    const user = userEvent.setup()
    await askQuestion(user, 'outage help')
    await user.click(screen.getByText('Ask'))

    await waitFor(() => expect(mockQueryIntelligence).toHaveBeenCalled())
    const payload = mockQueryIntelligence.mock.calls[0][1]
    expect(payload).not.toHaveProperty('source_type')
  })

  it('clears a stale answer when the scope changes', async () => {
    const user = userEvent.setup()
    await askQuestion(user, 'outage help')
    await user.click(screen.getByText('Ask'))
    await screen.findByText('Do this.')

    await user.selectOptions(screen.getByLabelText('Sources'), 'policy')

    expect(screen.queryByText('Do this.')).not.toBeInTheDocument()
  })
})
