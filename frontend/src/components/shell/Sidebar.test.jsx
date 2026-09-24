import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const mockUseCapabilities = vi.fn()
const mockUseAuth = vi.fn()
const mockUseMe = vi.fn()

vi.mock('../../auth/capabilities.js', () => ({
  useCapabilities: () => mockUseCapabilities(),
}))

vi.mock('../../auth/useAuth.js', () => ({
  useAuth: () => mockUseAuth(),
}))

vi.mock('../../auth/useMe.js', () => ({
  useMe: () => mockUseMe(),
  APPLICATION_ROLES: {
    PLATFORM_ADMINISTRATOR: 'platform_administrator',
    COMPANY_ADMINISTRATOR: 'company_administrator',
    OPERATIONS_USER: 'operations_user',
    EMPLOYEE: 'employee',
  },
}))

vi.mock('../../tenant/useTenant.js', () => ({
  useTenant: () => ({ tenantId: 'test-tenant' }),
}))

// ContextHeader fetches the workspace name and has its own test file.
// These tests are about which nav items render, not the identity block.
vi.mock('./ContextHeader.jsx', () => ({
  ContextHeader: () => <div data-testid="context-header" />,
}))

import { Sidebar } from '../shell/Sidebar.jsx'

/**
 * The real permission matrix, transcribed from `ROLE_PERMISSIONS` in
 * `src/arc/security/authorization.py`.
 *
 * PR-2 made navigation permission-derived, so a harness that invented
 * permission sets would assert nothing useful. These are the sets the
 * backend actually returns from `GET /auth/me`.
 */
const ROLE_PERMISSIONS = {
  employee: ['knowledge:read', 'agent:execute'],

  operations_user: [
    'knowledge:read', 'agent:execute', 'tenant:read',
    'skill:read', 'skill:execute', 'tool:read', 'tool:execute',
    'connector:read', 'connector:sync', 'observability:read',
    'webhook:read', 'webhook:process',
  ],

  company_administrator: [
    'knowledge:read', 'knowledge:create', 'knowledge:update', 'knowledge:delete',
    'agent:execute', 'tenant:read', 'tenant:update',
    'skill:read', 'skill:create', 'skill:update', 'skill:delete', 'skill:execute',
    'tool:read', 'tool:execute', 'approval:read', 'approval:decide',
    'connector:read', 'connector:create', 'connector:sync',
    'connector:manage_credentials', 'observability:read',
    'webhook:read', 'webhook:process',
  ],

  platform_administrator: [
    'knowledge:read', 'knowledge:create', 'knowledge:update', 'knowledge:delete',
    'agent:execute', 'tenant:read', 'tenant:update', 'tenant:create', 'tenant:list',
    'skill:read', 'skill:create', 'skill:update', 'skill:delete', 'skill:execute',
    'tool:read', 'tool:execute', 'approval:read', 'approval:decide',
    'connector:read', 'connector:create', 'connector:sync',
    'connector:manage_credentials', 'observability:read',
    'observability:platform_read', 'webhook:read', 'webhook:process',
    'user:read', 'user:create', 'membership:create', 'capability:manage',
  ],
}

function capabilitiesFor(role, memberOf) {
  const permissions = new Set(ROLE_PERMISSIONS[role] ?? [])
  const memberships = memberOf.map((id) => ({ tenant_id: id, role: 'member' }))
  return {
    role,
    permissions,
    memberships,
    can: (p) => permissions.has(p),
    hasRole: (r) => r === role,
    isMemberOf: (id) => memberships.some((m) => m.tenant_id === id),
    isLoaded: true,
    isPending: false,
    isPlatformAdministrator: role === 'platform_administrator',
    isCompanyAdministrator: role === 'company_administrator',
    isOperationsUser: role === 'operations_user',
    isEmployee: role === 'employee',
  }
}

function renderSidebar(role, { memberOf = ['test-tenant'], path = '/app/t/test-tenant/overview' } = {}) {
  const caps = capabilitiesFor(role, memberOf)
  mockUseCapabilities.mockReturnValue(caps)
  mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
  mockUseMe.mockReturnValue({
    data: { role, permissions: [...caps.permissions] },
    isPending: false,
  })

  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/app/t/:tenantId/*" element={<Sidebar />} />
        <Route path="/platform/*" element={<Sidebar />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** The workspace nav routes currently rendered, in order. */
function workspaceRoutes() {
  return screen
    .getAllByRole('link')
    .map((a) => a.getAttribute('href'))
    .filter((h) => h && h.startsWith('/app/t/'))
    .map((h) => h.split('/').pop())
}

describe('Sidebar permission-derived navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('employee role', () => {
    it('offers exactly the surfaces its two permissions cover', () => {
      renderSidebar('employee')
      // knowledge:read -> Ask Arc + Company Brain; agent:execute -> Agents
      // and, since an agent run can raise an approval, the employee's own
      // Approvals (ADR-012). Home is the landing page for a member
      // without tenant:read.
      expect(workspaceRoutes()).toEqual([
        'home',
        'ask',
        'knowledge',
        'agents',
        'approvals',
      ])
    })

    it('now reaches Company Brain, which it holds knowledge:read for', () => {
      // Regression: the previous binary role gate hid Company Brain from
      // every employee even though the backend serves them GET /knowledge.
      renderSidebar('employee')
      expect(screen.getByText('Company Brain')).toBeInTheDocument()
    })

    it('does not show surfaces it has no permission for', () => {
      renderSidebar('employee')
      const hidden = ['Overview', 'Skills', 'Tools', 'Connectors', 'Webhooks', 'Settings', 'Usage']
      for (const label of hidden) {
        expect(screen.queryByText(label)).not.toBeInTheDocument()
      }
    })

    it('shows Approvals — agent:execute can raise one (ADR-012)', () => {
      // An employee reaches tools through Agent (V2-ADR-005), so an
      // employee can be a requester. The page shows them their own
      // requests and is where an approved one is spent, so hiding the
      // link would strand the approval.
      renderSidebar('employee')
      expect(screen.getByText('Approvals')).toBeInTheDocument()
    })

    it('does not show the Personal or Platform sections', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Profile')).not.toBeInTheDocument()
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
  })

  describe('operations user role', () => {
    it('shows the operational surfaces its permissions cover', () => {
      renderSidebar('operations_user')
      // Five areas now, with sub-navigation. Labels are the product's, not
      // the backend service's: Sources rather than Connectors, Activity
      // rather than Webhooks, Workspace rather than Overview.
      const shown = ['Ask Arc', 'Company Brain', 'Knowledge', 'Sources',
                     'AI Workflows', 'Skills', 'Agents',
                     'Operations', 'Approvals', 'Webhooks', 'Usage',
                     'Administration', 'People', 'Workspace']
      for (const label of shown) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('groups its surfaces into areas rather than a flat list', () => {
      renderSidebar('operations_user')
      for (const area of ['Company Brain', 'AI Workflows', 'Operations', 'Administration']) {
        expect(screen.getByText(area)).toBeInTheDocument()
      }
    })

    it('shows Approvals even though it lacks approval:read (ADR-012)', () => {
      // This is the role the ADR is about: tool:execute without
      // approval:read is exactly what raises a request nobody could then
      // see. It reads only its own requests, and decides none.
      renderSidebar('operations_user')
      expect(screen.getByText('Approvals')).toBeInTheDocument()
    })

    it('does not show Settings — it lacks tenant:update', () => {
      renderSidebar('operations_user')
      expect(screen.queryByText('Settings')).not.toBeInTheDocument()
    })

    it('does not show Home — it holds tenant:read and lands on Overview', () => {
      renderSidebar('operations_user')
      expect(workspaceRoutes()).not.toContain('home')
    })

    it('shows the Personal section', () => {
      renderSidebar('operations_user')
      expect(screen.getByText('Profile')).toBeInTheDocument()
    })
  })

  describe('company administrator role', () => {
    it('shows every workspace surface, grouped into five areas', () => {
      renderSidebar('company_administrator')
      const shown = ['Ask Arc',
                     'Company Brain', 'Knowledge', 'Sources',
                     'AI Workflows', 'Skills', 'Agents',
                     'Operations', 'Approvals', 'Webhooks', 'Usage',
                     'Administration', 'People', 'Workspace', 'Settings']
      for (const label of shown) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('no longer offers Company — it duplicated Overview and Settings', () => {
      renderSidebar('company_administrator')
      expect(workspaceRoutes()).not.toContain('company')
    })

    it('labels the webhook route Webhooks, not Activity', () => {
      // Review on #282: the route serves GET ~/webhooks/events — webhook
      // deliveries. "Activity" promises all workspace activity (agent runs,
      // skill executions, knowledge changes) and delivers one slice of it.
      renderSidebar('company_administrator')
      expect(screen.getByText('Webhooks')).toBeInTheDocument()
      expect(screen.queryByText('Activity')).not.toBeInTheDocument()
    })

    it('does not offer a second view of the usage endpoint', () => {
      // Review on #282: Observability was labelled "Health" but called the
      // same getTenantUsageSummary endpoint as Usage and rendered a card
      // titled "Usage Summary". Two nav items, one dataset.
      renderSidebar('company_administrator')
      expect(screen.queryByText('Health')).not.toBeInTheDocument()
      expect(workspaceRoutes()).not.toContain('observability')
    })

    it('no longer offers Tools as a top-level area', () => {
      // PRD §13: tools are platform-owned, and the tenant API has no
      // create/update/delete. There is nothing to manage here.
      renderSidebar('company_administrator')
      expect(workspaceRoutes()).not.toContain('tools')
    })

    it('does not route to the removed non-functional surfaces', () => {
      // PR-1 deleted the Operations, Incidents and Activity SHELL PAGES.
      // "Operations" and "Activity" now exist as an area name and a nav
      // label, so this asserts on routes rather than on words.
      renderSidebar('company_administrator')
      const routes = workspaceRoutes()
      expect(routes).not.toContain('operations')
      expect(routes).not.toContain('incidents')
      expect(routes).not.toContain('activity')
    })

    it('does not show the Platform section', () => {
      renderSidebar('company_administrator')
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
  })

  describe('platform administrator role (V2-ADR-003)', () => {
    it('shows the console navigation when in the console', () => {
      renderSidebar('platform_administrator', { memberOf: [], path: '/platform/dashboard' })
      expect(screen.getByText('Console')).toBeInTheDocument()
    })

    it('does NOT show console navigation from inside a workspace', () => {
      // The two contexts are mutually exclusive: stacking them is what
      // produced fifteen workspace items under the platform items.
      // ContextHeader carries the link across instead.
      renderSidebar('platform_administrator', { memberOf: ['test-tenant'] })
      expect(screen.queryByText('Console')).not.toBeInTheDocument()
    })

    it('shows NO workspace navigation without tenant membership', () => {
      // The defining fix of this PR. Previously a platform administrator
      // received all fifteen workspace items despite having no membership,
      // and every one dead-ended on RequireTenant's "not a member" state.
      // Holding every permission is not membership.
      renderSidebar('platform_administrator', { memberOf: [] })
      expect(workspaceRoutes()).toEqual([])
      expect(screen.queryByText('Workspace')).not.toBeInTheDocument()
    })

    it('shows workspace navigation when they ARE a member of the tenant', () => {
      // Membership, not role, is the gate — so a platform administrator who
      // genuinely belongs to a workspace still sees it.
      renderSidebar('platform_administrator', { memberOf: ['test-tenant'] })
      expect(screen.getByText('Company Brain')).toBeInTheDocument()
    })

    it('does not show removed platform surfaces', () => {
      renderSidebar('platform_administrator', { memberOf: [], path: '/platform/dashboard' })
      const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
      expect(hrefs).not.toContain('/platform/connectors')
      expect(hrefs).not.toContain('/platform/agents')
    })

    it('still shows the platform surfaces that are wired', () => {
      renderSidebar('platform_administrator', { memberOf: [], path: '/platform/dashboard' })
      const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
      expect(hrefs).toContain('/platform/dashboard')
      expect(hrefs).toContain('/platform/tenants')
      expect(hrefs).toContain('/platform/users')
      expect(hrefs).toContain('/platform/observability')
    })
  })

  describe('unresolved profile fails closed (PRD P4)', () => {
    it('offers nothing while permissions are unknown', () => {
      // The old default case returned the FULL product surface for an
      // unknown role. An unresolved profile must offer the minimum.
      mockUseCapabilities.mockReturnValue({
        role: null,
        permissions: new Set(),
        memberships: [],
        can: () => false,
        hasRole: () => false,
        isMemberOf: () => false,
        isLoaded: false,
        isPending: true,
        isPlatformAdministrator: false,
        isCompanyAdministrator: false,
        isOperationsUser: false,
        isEmployee: false,
      })
      mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
      mockUseMe.mockReturnValue({ data: undefined, isPending: true })

      render(
        <MemoryRouter initialEntries={['/app/t/test-tenant/overview']}>
          <Routes>
            <Route path="/app/t/:tenantId/*" element={<Sidebar />} />
          </Routes>
        </MemoryRouter>,
      )

      expect(workspaceRoutes()).toEqual([])
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
  })
})
