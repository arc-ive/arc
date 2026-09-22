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

function renderSidebar(role) {
  mockUseCapabilities.mockReturnValue({
    role,
    isPlatformAdministrator: role === 'platform_administrator',
    isCompanyAdministrator: role === 'company_administrator',
    isOperationsUser: role === 'operations_user',
    isEmployee: role === 'employee',
    isDemo: false,
    can: () => false,
  })

  mockUseAuth.mockReturnValue({
    principal: { sub: 'user-1' },
    isDemo: false,
  })

  mockUseMe.mockReturnValue({
    data: { role, permissions: [] },
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

describe('Sidebar role-based rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('employee role', () => {
    it('shows Home in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.getByText('Home')).toBeInTheDocument()
    })

    it('shows Ask Arc in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.getByText('Ask Arc')).toBeInTheDocument()
    })

    it('does not show Personal section', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Profile')).not.toBeInTheDocument()
    })

    it('does not show Overview in tenant navigation', () => {
      renderSidebar('employee')
      const navItems = screen.getAllByRole('link')
      const overviewLink = navItems.find(
        (item) => item.textContent.includes('Overview'),
      )
      expect(overviewLink).toBeUndefined()
    })

    it('does not show Skills in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Skills')).not.toBeInTheDocument()
    })

    it('does not show Tools in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Tools')).not.toBeInTheDocument()
    })

    it('does not show Connectors in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Connectors')).not.toBeInTheDocument()
    })

    it('does not show Webhooks in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Webhooks')).not.toBeInTheDocument()
    })

    it('does not show Settings in tenant navigation', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Settings')).not.toBeInTheDocument()
    })

    it('does not show Platform section', () => {
      renderSidebar('employee')
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
  })

  describe('company administrator role', () => {
    it('shows Overview in tenant navigation', () => {
      renderSidebar('company_administrator')
      expect(screen.getByText('Overview')).toBeInTheDocument()
    })

    it('shows Skills in tenant navigation', () => {
      renderSidebar('company_administrator')
      expect(screen.getByText('Skills')).toBeInTheDocument()
    })

    it('shows Tools in tenant navigation', () => {
      renderSidebar('company_administrator')
      expect(screen.getByText('Tools')).toBeInTheDocument()
    })

    it('shows Personal section', () => {
      renderSidebar('company_administrator')
      expect(screen.getByText('Profile')).toBeInTheDocument()
    })

    it('does not show Platform section', () => {
      renderSidebar('company_administrator')
      expect(screen.queryByText('Platform')).not.toBeInTheDocument()
    })
    // PR-1: these three tenant surfaces were removed — they called no API
    // and rendered internal build status to customers (UX_SPEC §1).
    it('does not show removed non-functional surfaces', () => {
      renderSidebar('company_administrator')
      expect(screen.queryByText('Operations')).not.toBeInTheDocument()
      expect(screen.queryByText('Incidents')).not.toBeInTheDocument()
      expect(screen.queryByText('Activity')).not.toBeInTheDocument()
    })
  })

  describe('platform administrator role', () => {
    it('shows Platform section', () => {
      renderSidebar('platform_administrator')
      expect(screen.getByText('Platform')).toBeInTheDocument()
    })

    it('shows Overview in tenant navigation', () => {
      renderSidebar('platform_administrator')
      expect(screen.getByText('Overview')).toBeInTheDocument()
    })

    it('shows Personal section', () => {
      renderSidebar('platform_administrator')
      expect(screen.getByText('Profile')).toBeInTheDocument()
    })
    // PR-1: Platform Connectors and Platform Agents were removed — neither
    // called an API and both exposed implementation detail (ADR ids, the
    // internal provider chain).
    // Asserted by href, not label: a platform administrator currently also
    // renders the tenant workspace nav, which has its own Connectors and
    // Agents entries. Only the /platform/* links are in PR-1 scope.
    it('does not show removed platform surfaces', () => {
      renderSidebar('platform_administrator')
      const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
      expect(hrefs).not.toContain('/platform/connectors')
      expect(hrefs).not.toContain('/platform/agents')
    })

    it('still shows the platform surfaces that are wired', () => {
      renderSidebar('platform_administrator')
      const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
      expect(hrefs).toContain('/platform/dashboard')
      expect(hrefs).toContain('/platform/tenants')
      expect(hrefs).toContain('/platform/users')
      expect(hrefs).toContain('/platform/observability')
    })
  })

  describe('operations user role', () => {
    // PR-1: Operations, Incidents and Activity were shells that called no
    // API and rendered internal build status (UX_SPEC §1). Incidents also
    // contradicted V2-ADR-021 and PRD §24. All three are gone from
    // navigation; the operations user keeps the surfaces that are wired.
    it('does not show removed non-functional surfaces in tenant navigation', () => {
      renderSidebar('operations_user')
      expect(screen.queryByText('Operations')).not.toBeInTheDocument()
      expect(screen.queryByText('Incidents')).not.toBeInTheDocument()
      expect(screen.queryByText('Activity')).not.toBeInTheDocument()
    })

    it('still shows the operational surfaces that are wired', () => {
      renderSidebar('operations_user')
      expect(screen.getByText('Company Brain')).toBeInTheDocument()
      expect(screen.getByText('Skills')).toBeInTheDocument()
      expect(screen.getByText('Agents')).toBeInTheDocument()
    })

    it('shows Personal section', () => {
      renderSidebar('operations_user')
      expect(screen.getByText('Profile')).toBeInTheDocument()
    })

    it('does not show Tools in tenant navigation', () => {
      renderSidebar('operations_user')
      expect(screen.queryByText('Tools')).not.toBeInTheDocument()
    })
  })
})
