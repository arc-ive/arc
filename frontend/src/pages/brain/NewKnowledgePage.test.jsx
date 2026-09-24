import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockCreateKnowledge = vi.fn()
const mockUploadKnowledge = vi.fn()

vi.mock('../../api/endpoints/knowledge.js', () => ({
  createKnowledge: (...a) => mockCreateKnowledge(...a),
  uploadKnowledge: (...a) => mockUploadKnowledge(...a),
  KNOWLEDGE_SOURCES: [
    'policy',
    'procedure',
    'incident_report',
    'troubleshooting',
    'internal_knowledge',
    'solution',
  ],
}))

import { NewKnowledgePage } from './NewKnowledgePage.jsx'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/t/t-123/knowledge/new']}>
        <Routes>
          <Route
            path="/app/t/:tenantId/knowledge/new"
            element={<NewKnowledgePage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const pdf = () =>
  new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'leave-policy.pdf', {
    type: 'application/pdf',
  })

describe('NewKnowledgePage upload (issue #299)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCreateKnowledge.mockResolvedValue({ id: 'doc-1' })
    mockUploadKnowledge.mockResolvedValue({ id: 'doc-2' })
  })

  it('offers a way to upload a file', async () => {
    // The endpoint shipped without this, so it was unreachable from the
    // product: a capability nobody could use.
    renderPage()
    expect(screen.getByText(/upload a file instead/i)).toBeInTheDocument()
  })

  it('sends the chosen file rather than typed content', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.upload(screen.getByLabelText(/upload a file instead/i), pdf())
    await user.click(screen.getByRole('button', { name: /create document/i }))

    await waitFor(() => expect(mockUploadKnowledge).toHaveBeenCalled())
    expect(mockCreateKnowledge).not.toHaveBeenCalled()
    const [, payload] = mockUploadKnowledge.mock.calls[0]
    expect(payload.file.name).toBe('leave-policy.pdf')
    expect(payload.source).toBe('policy')
  })

  it('replaces the editor rather than sitting beside it', async () => {
    // Two possible sources of content on one page is a question the
    // page cannot answer.
    const user = userEvent.setup()
    renderPage()

    expect(screen.getByLabelText(/^content/i)).toBeInTheDocument()
    await user.upload(screen.getByLabelText(/upload a file instead/i), pdf())

    expect(screen.queryByLabelText(/^content/i)).not.toBeInTheDocument()
    expect(screen.getByText('leave-policy.pdf')).toBeInTheDocument()
  })

  it('hides Version for an upload, which always creates version 1', async () => {
    // An editable field the server ignores is input that silently does
    // nothing.
    const user = userEvent.setup()
    renderPage()

    expect(screen.getByLabelText(/^version/i)).toBeInTheDocument()
    await user.upload(screen.getByLabelText(/upload a file instead/i), pdf())

    expect(screen.queryByLabelText(/^version/i)).not.toBeInTheDocument()
  })

  it('lets a file be removed to go back to typing', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.upload(screen.getByLabelText(/upload a file instead/i), pdf())
    await user.click(screen.getByRole('button', { name: /remove/i }))

    expect(screen.getByLabelText(/^content/i)).toBeInTheDocument()
  })

  it('does not require Source for an upload', async () => {
    // The filename stands in server-side, so demanding one here would
    // block a valid upload.
    const user = userEvent.setup()
    renderPage()

    await user.upload(screen.getByLabelText(/upload a file instead/i), pdf())
    await user.click(screen.getByRole('button', { name: /create document/i }))

    await waitFor(() => expect(mockUploadKnowledge).toHaveBeenCalled())
    expect(screen.queryByText('Source is required.')).not.toBeInTheDocument()
  })

  it('still creates a typed document when no file is chosen', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/^source/i), 'Employee Handbook')
    await user.type(screen.getByLabelText(/^content/i), 'Leave is 26 days.')
    await user.click(screen.getByRole('button', { name: /create document/i }))

    await waitFor(() => expect(mockCreateKnowledge).toHaveBeenCalled())
    expect(mockUploadKnowledge).not.toHaveBeenCalled()
  })
})
