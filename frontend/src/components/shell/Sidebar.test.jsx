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

function renderSidebar(role, { memberOf = ['test-tenant'] } = {}) {
  const caps = capabilitiesFor(role, memberOf)
  mockUseCapabilities.mockReturnValue(caps)
  mockUseAuth.mockReturnValue({ principal: { sub: 'user-1' } })
  mockUseMe.mockReturnValue({
    data: { role, permissions: [...caps.permissions] },
    isPending: false,
  })

  return render(
    <MemoryRouter initialEntries={['/app/t/test-tenant/overview']}>
      <Routes>
        <Route path="/app/t/:tenantId/*" element={<Sidebar />} />
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
      // knowledge:read -> Ask Arc + Company Brain; agent:execute -> Agents.
      // Home is the landing page for a member without tenant:read.
      expect(workspaceRoutes()).toEqual(['home', 'ask', 'knowledge', 'agents'])
    })

    it('now reaches Company Brain, which it holds knowledge:read for', () => {
      // Regression: the previous binary role gate hid Company Brain from
      // every employee even though the backend serves them GET /knowledge.
      renderSidebar('employee')
      expect(screen.getByText('Company Brain')).toBeInTheDocument()
    })

    it('does not show surfaces it has no permission for', () => {
      renderSidebar('employee')
      const hidden = ['Overview', 'Skills', 'Tools', 'Connectors', 'Webhooks', 'Settings', 'Approvals', 'Usage']
      for (const label of hidden) {
        expect(screen.queryByText(label)).not.toBeInTheDocument()
      }
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
      const shown = ['Ask Arc', 'Overview', 'Company Brain', 'Skills', 'Agents', 'Tools', 'Connectors', 'Webhooks', 'Observability', 'Usage']
      for (const label of shown) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('does not show Approvals — it lacks approval:read', () => {
      renderSidebar('operations_user')
      expect(screen.queryByText('Approvals')).not.toBeInTheDocument()
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
    it('shows every workspace surface', () => {
      renderSidebar('company_administrator')
      const shown = ['Ask Arc', 'Overview', 'Company', 'Company Brain', 'Skills', 'Agents', 'Tools', 'Connectors', 'Webhooks', 'Users', 'Observability', 'Approvals', 'Usage', 'Settings']
      for (const label of shown) {
        expect(screen.getByText(label)).toBeInTheDocument()
      }
    })

    it('does not show removed non-functional surfaces', () => {
      // PR-1: Operations, Incidents and Activity called no API and rendered
      // internal build status (UX_SPEC §1).
      renderSidebar('company_administrator')
      expect(screen.queryByText('Operations')).not.toBeInTheDocument()
      expect(screen.queryByText('Incidents')).not.toBeInTheDocument()
      expect(screen.queryByText('Activity')).not.toBeInTheDocument()
    })

    it('does not show the Platform section', () => {
      renderSidebar('company_administrator')
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
  })

  describe('platform administrator role (V2-ADR-003)', () => {
    it('shows the platform console', () => {
      renderSidebar('platform_administrator', { memberOf: [] })
      expect(screen.getByText('Platform')).toBeInTheDocument()
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
      renderSidebar('platform_administrator', { memberOf: [] })
      const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
      expect(hrefs).not.toContain('/platform/connectors')
      expect(hrefs).not.toContain('/platform/agents')
    })

    it('still shows the platform surfaces that are wired', () => {
      renderSidebar('platform_administrator', { memberOf: [] })
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
