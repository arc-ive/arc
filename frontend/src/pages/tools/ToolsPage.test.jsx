import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockListTools = vi.fn()
const mockExecuteTool = vi.fn()

vi.mock('../../api/endpoints/tools.js', () => ({
  listTools: (...a) => mockListTools(...a),
  executeTool: (...a) => mockExecuteTool(...a),
}))

const mockCan = vi.fn(() => true)
vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({ can: (...a) => mockCan(...a), role: 'company_administrator' }),
}))

vi.mock('../../tenant/useTenant.js', () => ({
  useTenant: () => ({ tenantId: 't-123' }),
}))

import { ToolsPage } from './ToolsPage.jsx'

const HIGH_RISK_TOOL = {
  name: 'grant_temporary_access',
  version: '1',
  description: 'Grant temporary elevated access.',
  risk_level: 'high',
  input_schema: { type: 'object', properties: {} },
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/t/t-123/tools']}>
        <ToolsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openDialogAndExecute() {
  const user = userEvent.setup()
  renderPage()
  await screen.findByText(/Grant temporary access/i)
  await user.click(screen.getAllByRole('button', { name: /^execute$/i })[0])
  // The dialog renders BEFORE the tool list in the tree, so once it is
  // open its submit button is the first "Execute", not the last. Clicking
  // the last one just reopens the dialog and executes nothing.
  await user.click(screen.getAllByRole('button', { name: /^execute$/i })[0])
  return user
}

describe('ToolsPage execution outcomes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCan.mockReturnValue(true)
    mockListTools.mockResolvedValue([HIGH_RISK_TOOL])
  })

  it('names an approval-gated result as waiting, not as success', async () => {
    // The tool has NOT run. Rendering the success banner over a null
    // output would be as wrong as the "not permitted" error this
    // replaced — one says it worked, the other said it was refused, and
    // the truth is that Arc filed an approval request.
    mockExecuteTool.mockResolvedValue({
      tool: 'grant_temporary_access',
      status: 'approval_required',
      approval_id: 'appr-abc123',
      output: null,
    })

    await openDialogAndExecute()

    expect(await screen.findByText(/waiting for approval/i)).toBeInTheDocument()
    expect(screen.getByText('appr-abc123')).toBeInTheDocument()
    expect(screen.queryByText(/execution successful/i)).not.toBeInTheDocument()
  })

  it('links an approval-gated result to the queue it now waits in', async () => {
    mockExecuteTool.mockResolvedValue({
      tool: 'grant_temporary_access',
      status: 'approval_required',
      approval_id: 'appr-abc123',
      output: null,
    })

    await openDialogAndExecute()

    const link = await screen.findByRole('link', { name: /open approvals/i })
    expect(link).toHaveAttribute('href', '/app/t/t-123/approvals')
  })

  it('still reports a real execution as successful', async () => {
    mockExecuteTool.mockResolvedValue({
      tool: 'grant_temporary_access',
      version: '1',
      status: 'executed',
      output: { granted: true },
    })

    await openDialogAndExecute()

    expect(await screen.findByText(/execution successful/i)).toBeInTheDocument()
    expect(screen.queryByText(/waiting for approval/i)).not.toBeInTheDocument()
  })

  it('omits the approvals link for a requester who cannot read approvals', async () => {
    // An operations user holds tool:execute but not approval:read. They
    // can raise this request and cannot open the queue it lands in.
    mockCan.mockImplementation((p) => p !== 'approval:read')
    mockExecuteTool.mockResolvedValue({
      tool: 'grant_temporary_access',
      status: 'approval_required',
      approval_id: 'appr-abc123',
      output: null,
    })

    await openDialogAndExecute()

    expect(await screen.findByText(/waiting for approval/i)).toBeInTheDocument()
    expect(screen.getByText('appr-abc123')).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: /open approvals/i }),
    ).not.toBeInTheDocument()
  })
})
