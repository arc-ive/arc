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
  })

  describe('operations user role', () => {
    it('shows Operations in tenant navigation', () => {
      renderSidebar('operations_user')
      expect(screen.getByText('Operations')).toBeInTheDocument()
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
