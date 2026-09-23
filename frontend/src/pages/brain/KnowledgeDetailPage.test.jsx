import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockGetKnowledgeDocument = vi.fn()
const mockUpdateKnowledge = vi.fn()

vi.mock('../../api/endpoints/knowledge.js', () => ({
  getKnowledgeDocument: (...args) => mockGetKnowledgeDocument(...args),
  updateKnowledge: (...args) => mockUpdateKnowledge(...args),
  KNOWLEDGE_SOURCES: [
    'policy',
    'procedure',
    'incident_report',
    'troubleshooting',
    'internal_knowledge',
    'solution',
  ],
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: (...args) => mockUseAuth(...args),
}))

import { KnowledgeDetailPage } from './KnowledgeDetailPage.jsx'
import { queryKeys } from '../../api/queryKeys.js'

const TENANT_ID = 't-123'
const DOCUMENT_ID = 'doc-1'

const MOCK_DOCUMENT = {
  id: DOCUMENT_ID,
  tenant_id: TENANT_ID,
  source: 'policy',
  provenance: 'Office handbook',
  version: 1,
  status: 'active',
  content: 'The office kitchen closes at six in the evening.',
  external_id: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
}

const UPDATED_CONTENT = 'The office kitchen closes at seven in the evening.'

function renderWithProviders(queryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/app/t/${TENANT_ID}/knowledge/${DOCUMENT_ID}`]}>
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

describe('KnowledgeDetailPage edit workflow', () => {
  let queryClient
  // Minimal in-memory "server": reads serve the latest saved state, so the
  // post-save invalidation refetch observes v2 exactly like the real API.
  let serverDoc

  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
    serverDoc = { ...MOCK_DOCUMENT }
    mockGetKnowledgeDocument.mockImplementation(() => Promise.resolve({ ...serverDoc }))
    mockUpdateKnowledge.mockImplementation((_tenantId, _documentId, payload) => {
      serverDoc = { ...serverDoc, ...payload, version: serverDoc.version + 1 }
      return Promise.resolve({ ...serverDoc })
    })
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
  })

  it('renders the existing document with its version', async () => {
    renderWithProviders(queryClient)

    expect(await screen.findByText('Office handbook')).toBeInTheDocument()
    expect(screen.getByText(MOCK_DOCUMENT.content)).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
    expect(mockGetKnowledgeDocument).toHaveBeenCalledWith(TENANT_ID, DOCUMENT_ID)
  })

  it('saves edited content with the same id and an incremented version', async () => {
    const user = userEvent.setup()
    renderWithProviders(queryClient)

    expect(await screen.findByText('Office handbook')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const editor = screen.getByPlaceholderText('Enter document content')
    await user.clear(editor)
    await user.type(editor, UPDATED_CONTENT)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockUpdateKnowledge).toHaveBeenCalledWith(TENANT_ID, DOCUMENT_ID, {
        content: UPDATED_CONTENT,
      }),
    )

    // Same document id, version incremented, updated content displayed.
    await waitFor(() => expect(screen.getByText('v2')).toBeInTheDocument())
    expect(screen.getByText(UPDATED_CONTENT)).toBeInTheDocument()
    expect(screen.getByText(DOCUMENT_ID)).toBeInTheDocument()

    // The detail cache holds the updated document (no stale v1 read-back).
    const cached = queryClient.getQueryData(
      queryKeys.knowledgeDocument(TENANT_ID, DOCUMENT_ID),
    )
    expect(cached.id).toBe(DOCUMENT_ID)
    expect(cached.version).toBe(2)
    expect(cached.content).toBe(UPDATED_CONTENT)
  })

  it('cancelling edit mode discards changes without calling the API', async () => {
    const user = userEvent.setup()
    renderWithProviders(queryClient)

    expect(await screen.findByText('Office handbook')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const editor = screen.getByPlaceholderText('Enter document content')
    await user.clear(editor)
    await user.type(editor, UPDATED_CONTENT)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(mockUpdateKnowledge).not.toHaveBeenCalled()
    expect(await screen.findByText(MOCK_DOCUMENT.content)).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
  })
})
