import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const mockUseCapabilities = vi.fn()

vi.mock('./capabilities.js', () => ({
  useCapabilities: () => mockUseCapabilities(),
}))

import { RequirePermission } from './RequirePermission.jsx'

/**
 * Replaces RequireWorkspaceRole.test.jsx.
 *
 * The guard it covered had two defects, both reproduced as tests here:
 *
 *  1. It failed OPEN while `GET /auth/me` was in flight. `role` was null,
 *     so `isEmployee` was false, so an employee was admitted to admin
 *     routes; the page mounted, fired its queries and collected 403s
 *     before the redirect landed. Observed live as nondeterministic
 *     behaviour — the same navigation produced 403s on 2 of 3 cold runs.
 *
 *  2. One role check stood in for fourteen distinct permissions, so it
 *     denied an Employee the Company Brain they hold `knowledge:read` for.
 */

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function caps({ permissions = [], isPending = false, isLoaded = true } = {}) {
  const set = new Set(permissions)
  return {
    can: (p) => set.has(p),
    permissions: set,
    isPending,
    isLoaded,
  }
}

function renderGuard(capabilities, permission = 'knowledge:read') {
  mockUseCapabilities.mockReturnValue(capabilities)
  return render(
    <MemoryRouter initialEntries={['/app/t/acme/knowledge']}>
      <Routes>
        <Route
          path="/app/t/:tenantId/knowledge"
          element={
            <RequirePermission permission={permission}>
              <div data-testid="protected">Company Brain</div>
            </RequirePermission>
          }
        />
        <Route path="/app/t/:tenantId/overview" element={<LocationProbe />} />
        <Route path="/app/t/:tenantId/home" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequirePermission', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('fails closed while the profile is unresolved (PRD P4, TRD §6)', () => {
    it('does not render the protected route while the profile is pending', () => {
      renderGuard(caps({ isPending: true, isLoaded: false }))
      expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    })

    it('does not redirect while the profile is pending', () => {
      // Redirecting here would bounce a legitimate user on a slow network.
      // The guard must hold, not guess in either direction.
      renderGuard(caps({ isPending: true, isLoaded: false }))
      expect(screen.queryByTestId('location')).not.toBeInTheDocument()
    })

    it('does not render the protected route when the profile failed to load', () => {
      // isPending false, isLoaded false — the query settled with no data.
      // An unknown principal holds nothing.
      renderGuard(caps({ isPending: false, isLoaded: false }))
      expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    })
  })

  describe('gates on the permission, not the role', () => {
    it('renders the route when the principal holds the permission', () => {
      renderGuard(caps({ permissions: ['knowledge:read'] }))
      expect(screen.getByTestId('protected')).toBeInTheDocument()
    })

    it('admits an employee to Company Brain — they hold knowledge:read', () => {
      // The old binary role gate redirected every employee away from this
      // route even though the backend serves them GET /knowledge with 200.
      renderGuard(caps({ permissions: ['knowledge:read', 'agent:execute'] }))
      expect(screen.getByTestId('protected')).toBeInTheDocument()
    })

    it('redirects when the principal lacks the permission', () => {
      renderGuard(caps({ permissions: ['agent:execute'] }))
      expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
      expect(screen.getByTestId('location')).toBeInTheDocument()
    })

    it('redirects a principal who holds a different permission entirely', () => {
      renderGuard(caps({ permissions: ['tenant:read'] }), 'approval:read')
      expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    })
  })

  describe('redirect destination follows the principal capabilities', () => {
    it('sends a principal with tenant:read to the workspace overview', () => {
      renderGuard(caps({ permissions: ['tenant:read'] }), 'approval:read')
      expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/overview')
    })

    it('sends a principal without tenant:read to home', () => {
      renderGuard(caps({ permissions: ['agent:execute'] }), 'approval:read')
      expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/home')
    })
  })
})
