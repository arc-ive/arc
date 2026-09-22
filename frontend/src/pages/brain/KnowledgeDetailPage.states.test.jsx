import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from '../../api/errors.js'

const mockGetKnowledgeDocument = vi.fn()
vi.mock('../../api/endpoints/knowledge.js', async (importOriginal) => ({
  ...(await importOriginal()),
  getKnowledgeDocument: (...args) => mockGetKnowledgeDocument(...args),
  updateKnowledge: vi.fn(),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({ useAuth: (...a) => mockUseAuth(...a) }))

vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({ can: () => true, role: 'company_administrator' }),
}))

import { KnowledgeDetailPage } from './KnowledgeDetailPage.jsx'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, networkMode: 'always' } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/t/t-1/knowledge/doc-1']}>
        <Routes>
          <Route
            path="/app/t/:tenantId/knowledge/:documentId"
            element={<KnowledgeDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const skeletonCount = (container) =>
  container.querySelectorAll('[class*="animate-pulse"]').length

/**
 * Issue #225: a failed request rendered the loading skeleton forever.
 * Loading, error, not-found and success must be distinguishable.
 */
describe('KnowledgeDetailPage failure states (Issue #225)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ isDemo: false })
  })

  it('renders a not-found state for a 404, not a skeleton', async () => {
    mockGetKnowledgeDocument.mockRejectedValue(
      new ApiError('Knowledge document not found', { status: 404 }),
    )
    const { container } = renderPage()

    expect(await screen.findByText('Document not found')).toBeInTheDocument()
    expect(
      screen.getByText('This document does not exist, or it has been deleted.'),
    ).toBeInTheDocument()
    expect(skeletonCount(container)).toBe(0)
  })

  it('renders an error state with a retry control for a 500', async () => {
    mockGetKnowledgeDocument.mockRejectedValue(
      new ApiError('Internal server error', { status: 500 }),
    )
    const { container } = renderPage()

    expect(await screen.findByText('Could not load this document')).toBeInTheDocument()
    expect(screen.getByText('Internal server error')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(skeletonCount(container)).toBe(0)
  })

  it('retries the request when the retry control is used', async () => {
    const user = userEvent.setup()
    mockGetKnowledgeDocument.mockRejectedValue(
      new ApiError('Internal server error', { status: 500 }),
    )
    renderPage()

    await screen.findByText('Could not load this document')
    expect(mockGetKnowledgeDocument).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(mockGetKnowledgeDocument).toHaveBeenCalledTimes(2))
  })

  it('renders a permission-denied state for a 403', async () => {
    mockGetKnowledgeDocument.mockRejectedValue(new ApiError('Forbidden', { status: 403 }))
    const { container } = renderPage()

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(skeletonCount(container)).toBe(0)
  })
})
