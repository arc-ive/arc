import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const mockUseCapabilities = vi.fn()
vi.mock('./capabilities.js', () => ({
  useCapabilities: () => mockUseCapabilities(),
}))

import { RequireWorkspaceRole } from './RequireWorkspaceRole.jsx'

function Wrapper({ initialEntries = ['/app/t/test-tenant/overview'] }) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route
          path="/app/t/:tenantId/*"
          element={
            <Routes>
              <Route
                path="overview"
                element={
                  <RequireWorkspaceRole>
                    <div>Admin Content</div>
                  </RequireWorkspaceRole>
                }
              />
              <Route path="home" element={<div>Employee Home</div>} />
            </Routes>
          }
        />
      </Routes>
    </MemoryRouter>
  )
}

describe('RequireWorkspaceRole', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children for company administrator', () => {
    mockUseCapabilities.mockReturnValue({
      isEmployee: false,
      isDemo: false,
    })

    render(<Wrapper />)

    expect(screen.getByText('Admin Content')).toBeInTheDocument()
  })

  it('renders children for platform administrator', () => {
    mockUseCapabilities.mockReturnValue({
      isEmployee: false,
      isDemo: false,
    })

    render(<Wrapper />)

    expect(screen.getByText('Admin Content')).toBeInTheDocument()
  })

  it('renders children for demo mode', () => {
    mockUseCapabilities.mockReturnValue({
      isEmployee: true,
      isDemo: true,
    })

    render(<Wrapper />)

    expect(screen.getByText('Admin Content')).toBeInTheDocument()
  })

  it('redirects employee to tenant home', () => {
    mockUseCapabilities.mockReturnValue({
      isEmployee: true,
      isDemo: false,
    })

    render(<Wrapper />)

    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument()
    expect(screen.getByText('Employee Home')).toBeInTheDocument()
  })

  it('preserves tenant ID in redirect', () => {
    mockUseCapabilities.mockReturnValue({
      isEmployee: true,
      isDemo: false,
    })

    render(
      <MemoryRouter initialEntries={['/app/t/my-company/tools']}>
        <Routes>
          <Route
            path="/app/t/:tenantId/*"
            element={
              <Routes>
                <Route
                  path="tools"
                  element={
                    <RequireWorkspaceRole>
                      <div>Tools Content</div>
                    </RequireWorkspaceRole>
                  }
                />
                <Route path="home" element={<div>Employee Home</div>} />
              </Routes>
            }
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.queryByText('Tools Content')).not.toBeInTheDocument()
    expect(screen.getByText('Employee Home')).toBeInTheDocument()
  })
})
