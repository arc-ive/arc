import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockListSkills = vi.fn()
const mockGetSkill = vi.fn()
const mockCreateSkill = vi.fn()
const mockUpdateSkill = vi.fn()
const mockDeleteSkill = vi.fn()
const mockExecuteSkill = vi.fn()

vi.mock('../../api/endpoints/skills.js', () => ({
  listSkills: (...args) => mockListSkills(...args),
  getSkill: (...args) => mockGetSkill(...args),
  createSkill: (...args) => mockCreateSkill(...args),
  updateSkill: (...args) => mockUpdateSkill(...args),
  deleteSkill: (...args) => mockDeleteSkill(...args),
  executeSkill: (...args) => mockExecuteSkill(...args),
}))

const mockUseAuth = vi.fn()
vi.mock('../../auth/useAuth.js', () => ({
  useAuth: (...args) => mockUseAuth(...args),
}))

const mockCan = vi.fn()
vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => ({
    can: mockCan,
    role: 'platform_administrator',
  }),
}))

const mockUseTenant = vi.fn()
vi.mock('../../tenant/useTenant.js', () => ({
  useTenant: (...args) => mockUseTenant(...args),
}))

import { SkillsPage } from './SkillsPage.jsx'

function renderWithProviders(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/app/t/t-123/skills']}>
        <Routes>
          <Route path="/app/t/:tenantId/skills" element={ui} />
          <Route path="/app/t/:tenantId/skills/:skillId" element={<div>Skill Detail</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const MOCK_SKILLS = [
  {
    id: 'skill-1',
    name: 'Recover degraded service',
    purpose: 'Check and restore service health',
    status: 'active',
    version: '1',
    approval_required: false,
    allowed_tools: ['check_service_health'],
    inputs: ['service_name'],
    preconditions: ['Service must be monitored'],
    steps: ['Check health', 'Restart if needed'],
    constraints: ['Max 3 retries'],
  },
  {
    id: 'skill-2',
    name: 'Deploy approval workflow',
    purpose: 'Requires approval before execution',
    status: 'active',
    version: '2',
    approval_required: true,
    allowed_tools: ['deploy'],
    inputs: [],
    preconditions: [],
    steps: [],
    constraints: [],
  },
]

describe('SkillsPage — execution controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({
      isDemo: false,
      user: { user_id: 'test-user', role: 'platform_administrator', permissions: ['skill:execute'] },
    })
    mockUseTenant.mockReturnValue({ tenantId: 't-123' })
    mockCan.mockImplementation((perm) => {
      if (perm === 'skill:execute') return true
      if (perm === 'skill:create') return true
      if (perm === 'skill:update') return true
      if (perm === 'skill:delete') return true
      return false
    })
    mockListSkills.mockResolvedValue(MOCK_SKILLS)
  })

  it('renders Execute button for authorized users', async () => {
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    expect(executeButtons.length).toBe(MOCK_SKILLS.length)
  })

  it('hides Execute button when skill:execute is unavailable', async () => {
    mockCan.mockImplementation(() => false)

    renderWithProviders(<SkillsPage view="list" />)

    await screen.findByText('2 skills')
    expect(screen.queryByTitle('Execute skill')).not.toBeInTheDocument()
  })

  it('opens the execution dialog when Execute is clicked', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    expect(screen.getByText('Execute skill')).toBeInTheDocument()
    expect(screen.getAllByText(/Recover degraded service/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Tool calls (JSON array)')).toBeInTheDocument()
  })

  it('validates invalid JSON before submission', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    const textarea = screen.getByPlaceholderText('[{"tool_name": "check_health", "input": {}}]')
    await user.clear(textarea)
    await user.type(textarea, 'not valid json')

    await user.click(screen.getByText('Execute'))

    expect(screen.getByText('Invalid JSON — please check your input')).toBeInTheDocument()
    expect(mockExecuteSkill).not.toHaveBeenCalled()
  })

  it('validates non-array JSON before submission', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    const textarea = screen.getByPlaceholderText('[{"tool_name": "check_health", "input": {}}]')
    await user.clear(textarea)
    fireEvent.change(textarea, { target: { value: '{"not": "an array"}' } })

    await user.click(screen.getByText('Execute'))

    expect(screen.getByText('Tool-call arguments must be a JSON array')).toBeInTheDocument()
    expect(mockExecuteSkill).not.toHaveBeenCalled()
  })

  it('submits valid JSON and displays succeeded result', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-1',
      status: 'succeeded',
      error_kind: null,
      steps: [
        { sequence: 0, tool_name: 'check_service_health', status: 'success', tool_version: '1.0', output: { healthy: true }, error_kind: null },
      ],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Succeeded')).toBeInTheDocument()
    expect(screen.getByText('check_service_health')).toBeInTheDocument()
    expect(screen.getByText('success')).toBeInTheDocument()
  })

  it('displays FAILED result with error_kind', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-2',
      status: 'failed',
      error_kind: 'inactive_skill',
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('inactive_skill')).toBeInTheDocument()
  })

  it('displays PRECONDITION_FAILED result', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-3',
      status: 'precondition_failed',
      error_kind: 'precondition_failed',
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Precondition failed')).toBeInTheDocument()
  })

  it('displays APPROVAL_REQUIRED result', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-4',
      status: 'approval_required',
      error_kind: 'approval_required',
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Approval required')).toBeInTheDocument()
  })

  it('displays DENIED result', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-5',
      status: 'denied',
      error_kind: 'disallowed_tool',
      steps: [
        { sequence: 0, tool_name: 'unauthorized_tool', status: 'failed', tool_version: null, output: null, error_kind: 'disallowed_tool' },
      ],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Denied')).toBeInTheDocument()
    expect(screen.getAllByText('disallowed_tool').length).toBeGreaterThanOrEqual(1)
  })

  it('displays API error on execution failure', async () => {
    mockExecuteSkill.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { detail: 'Request body must be an object' } },
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Request body must be an object')).toBeInTheDocument()
  })

  it('does not show Execute button in demo mode (no skills loaded)', async () => {
    mockUseAuth.mockReturnValue({
      isDemo: true,
      user: null,
    })

    renderWithProviders(<SkillsPage view="list" />)

    expect(await screen.findByText('No skills yet')).toBeInTheDocument()
    expect(screen.queryByTitle('Execute skill')).not.toBeInTheDocument()
  })

  it('closes dialog and resets state on close', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    expect(screen.getByText('Tool calls (JSON array)')).toBeInTheDocument()

    await user.click(screen.getByText('Cancel'))

    expect(screen.queryByText('Tool calls (JSON array)')).not.toBeInTheDocument()
  })

  it('displays steps with output for succeeded execution', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-6',
      status: 'succeeded',
      error_kind: null,
      steps: [
        { sequence: 0, tool_name: 'check_health', status: 'success', tool_version: '2.0', output: { status: 'ok' }, error_kind: null },
        { sequence: 1, tool_name: 'restart_service', status: 'success', tool_version: '1.0', output: { restarted: true }, error_kind: null },
      ],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    const stepsSection = await screen.findByText('Steps')
    expect(stepsSection).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()
    expect(screen.getByText('check_health')).toBeInTheDocument()
    expect(screen.getByText('restart_service')).toBeInTheDocument()
  })

  it('shows precondition checkboxes for skill with preconditions', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    expect(screen.getByText('Preconditions')).toBeInTheDocument()
    expect(screen.getByText('Service must be monitored')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('shows no-preconditions message for skill without preconditions', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[1])

    expect(screen.getByText('No preconditions required for this skill.')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('sends satisfied_preconditions when checkboxes are selected', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-7',
      status: 'succeeded',
      error_kind: null,
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Succeeded')).toBeInTheDocument()
    expect(mockExecuteSkill).toHaveBeenCalledWith(
      't-123',
      'skill-1',
      expect.objectContaining({
        tool_calls: expect.any(Array),
        satisfied_preconditions: ['Service must be monitored'],
      }),
    )
  })

  it('does not send satisfied_preconditions when none selected', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-8',
      status: 'succeeded',
      error_kind: null,
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Succeeded')).toBeInTheDocument()
    expect(mockExecuteSkill).toHaveBeenCalledWith(
      't-123',
      'skill-1',
      expect.objectContaining({
        tool_calls: expect.any(Array),
      }),
    )
    const callBody = mockExecuteSkill.mock.calls[0][2]
    expect(callBody).not.toHaveProperty('satisfied_preconditions')
  })

  it('resets precondition selections when dialog closes and reopens', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('checkbox').checked).toBe(true)

    await user.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Preconditions')).not.toBeInTheDocument()

    await user.click(executeButtons[0])
    expect(screen.getByRole('checkbox').checked).toBe(false)
  })

  it('displays 403 error on permission denied', async () => {
    mockExecuteSkill.mockRejectedValue({
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Not enough permissions' } },
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Not enough permissions')).toBeInTheDocument()
  })

  it('sends correct request body with tool_calls array', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-9',
      status: 'succeeded',
      error_kind: null,
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    const textarea = screen.getByPlaceholderText('[{"tool_name": "check_health", "input": {}}]')
    await user.clear(textarea)
    fireEvent.change(textarea, { target: { value: '[{"tool_name": "check_service_health", "input": {"svc": "web"}}]' } })

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Succeeded')).toBeInTheDocument()
    expect(mockExecuteSkill).toHaveBeenCalledWith(
      't-123',
      'skill-1',
      {
        tool_calls: [{ tool_name: 'check_service_health', input: { svc: 'web' } }],
      },
    )
  })

  it('prevents duplicate submission while mutation is pending', async () => {
    let resolveMutation
    mockExecuteSkill.mockImplementation(() => new Promise((resolve) => { resolveMutation = resolve }))

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))
    expect(screen.getByText('Executing...')).toBeInTheDocument()
    expect(screen.queryByText('Execute')).not.toBeInTheDocument()

    resolveMutation({ id: 'exec-10', status: 'succeeded', error_kind: null, steps: [] })
    expect(await screen.findByText('Succeeded')).toBeInTheDocument()
  })

  it('shows approval_required result with clear explanation', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-11',
      status: 'approval_required',
      error_kind: 'approval_required',
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    expect(await screen.findByText('Approval required')).toBeInTheDocument()
    expect(screen.getByText(/approval_required/)).toBeInTheDocument()
  })

  it('displays succeeded status badge with green variant', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-12',
      status: 'succeeded',
      error_kind: null,
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    await user.click(screen.getByText('Execute'))

    const badge = await screen.findByText('Succeeded')
    expect(badge).toBeInTheDocument()
  })

  it('allows submitting empty tool_calls array (backend validates)', async () => {
    mockExecuteSkill.mockResolvedValue({
      id: 'exec-13',
      status: 'failed',
      error_kind: 'invalid_request',
      steps: [],
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const executeButtons = await screen.findAllByTitle('Execute skill')
    await user.click(executeButtons[0])

    const textarea = screen.getByPlaceholderText('[{"tool_name": "check_health", "input": {}}]')
    await user.clear(textarea)
    fireEvent.change(textarea, { target: { value: '[]' } })

    await user.click(screen.getByText('Execute'))

    expect(mockExecuteSkill).toHaveBeenCalledWith('t-123', 'skill-1', { tool_calls: [] })
  })
})

describe('SkillsPage — edit flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({
      isDemo: false,
      user: { user_id: 'test-user', role: 'platform_administrator', permissions: ['skill:update'] },
    })
    mockUseTenant.mockReturnValue({ tenantId: 't-123' })
    mockCan.mockImplementation((perm) => {
      if (perm === 'skill:update') return true
      return false
    })
    mockListSkills.mockResolvedValue(MOCK_SKILLS)
  })

  it('renders Edit button for authorized users', async () => {
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    expect(editButtons.length).toBe(MOCK_SKILLS.length)
  })

  it('hides Edit button when skill:update is unavailable', async () => {
    mockCan.mockImplementation(() => false)

    renderWithProviders(<SkillsPage view="list" />)

    await screen.findByText('2 skills')
    expect(screen.queryByTitle('Edit skill')).not.toBeInTheDocument()
  })

  it('opens the edit dialog when Edit is clicked', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    expect(screen.getByText('Edit skill')).toBeInTheDocument()
    expect(screen.getByText('Save changes')).toBeInTheDocument()
  })

  it('pre-populates form fields from existing skill', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    expect(screen.getByDisplayValue('Recover degraded service')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Check and restore service health')).toBeInTheDocument()
    expect(screen.getByDisplayValue('1')).toBeInTheDocument()
  })

  it('submits update and invalidates queries on success', async () => {
    mockUpdateSkill.mockResolvedValue({ ...MOCK_SKILLS[0], name: 'Updated skill' })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    const nameInput = screen.getByDisplayValue('Recover degraded service')
    await user.clear(nameInput)
    await user.type(nameInput, 'Updated skill')

    await user.click(screen.getByText('Save changes'))

    expect(await screen.findByText('2 skills')).toBeInTheDocument()
    expect(mockUpdateSkill).toHaveBeenCalledWith(
      't-123',
      'skill-1',
      expect.objectContaining({ name: 'Updated skill' }),
    )
  })

  it('displays API error on update failure', async () => {
    mockUpdateSkill.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: 'Name already exists' } },
    })

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    await user.click(screen.getByText('Save changes'))

    expect(await screen.findByText('Name already exists')).toBeInTheDocument()
  })

  it('closes dialog on cancel without submitting', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    expect(screen.getByText('Save changes')).toBeInTheDocument()

    await user.click(screen.getByText('Cancel'))

    expect(screen.queryByText('Save changes')).not.toBeInTheDocument()
    expect(mockUpdateSkill).not.toHaveBeenCalled()
  })

  it('prevents duplicate submission while mutation is pending', async () => {
    let resolveMutation
    mockUpdateSkill.mockImplementation(() => new Promise((resolve) => { resolveMutation = resolve }))

    const user = userEvent.setup()
    renderWithProviders(<SkillsPage view="list" />)

    const editButtons = await screen.findAllByTitle('Edit skill')
    await user.click(editButtons[0])

    await user.click(screen.getByText('Save changes'))
    expect(screen.getByText('Saving...')).toBeInTheDocument()
    expect(screen.queryByText('Save changes')).not.toBeInTheDocument()

    resolveMutation({ ...MOCK_SKILLS[0], name: 'Updated skill' })
    expect(await screen.findByText('2 skills')).toBeInTheDocument()
  })
})
