import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const mockUseCapabilities = vi.fn()
const mockGetUserTenants = vi.fn()

vi.mock('../../auth/capabilities.js', () => ({ useCapabilities: () => mockUseCapabilities() }))
vi.mock('../../auth/useAuth.js', () => ({ useAuth: () => ({ principal: { sub: 'u-1' } }) }))
vi.mock('../../tenant/useTenant.js', () => ({ useTenant: () => ({ tenantId: 'acme' }) }))
vi.mock('../../api/endpoints/tenants.js', () => ({
  getUserTenants: (...a) => mockGetUserTenants(...a),
}))

import { ContextHeader } from './ContextHeader.jsx'

function renderAt(path, { role = 'company_administrator', memberOf = ['acme'] } = {}) {
  mockUseCapabilities.mockReturnValue({
    isPlatformAdministrator: role === 'platform_administrator',
    isMemberOf: (id) => memberOf.includes(id),
  })
  mockGetUserTenants.mockResolvedValue([{ id: 'acme', name: 'Acme Technologies' }])

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ContextHeader />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/**
 * V2-ADR-003 keeps platform administration and tenant workspace
 * administration distinct. Before this, both contexts rendered identical
 * chrome and the only signal was an 11px uppercase section label.
 */
describe('ContextHeader', () => {
  beforeEach(() => vi.clearAllMocks())

  describe('platform console', () => {
    it('names the console, not a workspace', async () => {
      renderAt('/platform/dashboard', { role: 'platform_administrator', memberOf: [] })
      expect(await screen.findByText('Platform Console')).toBeInTheDocument()
      expect(screen.getByText('Arc')).toBeInTheDocument()
    })

    it('does not offer a return link — it is already the console', () => {
      renderAt('/platform/dashboard', { role: 'platform_administrator', memberOf: [] })
      expect(screen.queryByRole('link', { name: /platform console/i })).not.toBeInTheDocument()
    })
  })

  describe('workspace', () => {
    it('names the workspace the user is actually in', async () => {
      renderAt('/app/t/acme/knowledge')
      expect(await screen.findByText('Acme Technologies')).toBeInTheDocument()
      expect(screen.getByText('Workspace')).toBeInTheDocument()
    })

    it('does not claim a workspace context without membership', async () => {
      // A platform administrator holds every permission but, per ADR-003,
      // no membership. They are not "in" this workspace.
      renderAt('/app/t/acme/knowledge', {
        role: 'platform_administrator',
        memberOf: [],
      })
      expect(await screen.findByText('Arc')).toBeInTheDocument()
      expect(screen.queryByText('Workspace')).not.toBeInTheDocument()
    })
  })

  describe('crossing between contexts', () => {
    it('gives a platform administrator inside a workspace a way back', async () => {
      renderAt('/app/t/acme/knowledge', {
        role: 'platform_administrator',
        memberOf: ['acme'],
      })
      const back = await screen.findByRole('link', { name: /platform console/i })
      expect(back).toHaveAttribute('href', '/platform/dashboard')
    })

    it('does not show the return link to a non-platform user', async () => {
      renderAt('/app/t/acme/knowledge', { role: 'company_administrator' })
      await screen.findByText('Acme Technologies')
      expect(screen.queryByRole('link', { name: /platform console/i })).not.toBeInTheDocument()
    })
  })
})
