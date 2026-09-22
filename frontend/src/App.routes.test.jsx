import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { LegacyBrainDocumentRedirect, LegacyBrainRedirect } from './App.jsx'

/**
 * Issue #225 AC 3. The aliases previously used relative `to` values, which
 * React Router resolves against the MATCHED ROUTE — so "knowledge" from
 * /company-brain landed on /company-brain/knowledge -> /knowledge/knowledge,
 * a 404 document id that then rendered a permanent skeleton.
 */
function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderAt(initialPath) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/app/t/:tenantId/company-brain" element={<LegacyBrainRedirect />} />
        <Route
          path="/app/t/:tenantId/company-brain/new"
          element={<LegacyBrainRedirect suffix="/new" />}
        />
        <Route
          path="/app/t/:tenantId/company-brain/:documentId"
          element={<LegacyBrainDocumentRedirect />}
        />
        <Route path="/app/t/:tenantId/knowledge" element={<LocationProbe />} />
        <Route path="/app/t/:tenantId/knowledge/new" element={<LocationProbe />} />
        <Route path="/app/t/:tenantId/knowledge/:documentId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('legacy Company Brain aliases', () => {
  it('redirects /company-brain to the knowledge list', () => {
    renderAt('/app/t/acme/company-brain')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/knowledge')
  })

  it('redirects /company-brain/new to the new-document route', () => {
    renderAt('/app/t/acme/company-brain/new')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/knowledge/new')
  })

  it('redirects a legacy document alias to the knowledge document route', () => {
    renderAt('/app/t/acme/company-brain/doc-42')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/knowledge/doc-42')
  })

  it('never resolves to the doubled /knowledge/knowledge path', () => {
    renderAt('/app/t/acme/company-brain')
    expect(screen.getByTestId('location')).not.toHaveTextContent('knowledge/knowledge')
  })

  it('encodes tenant ids that need escaping', () => {
    renderAt('/app/t/acme%2Fops/company-brain')
    expect(screen.getByTestId('location').textContent).toContain('/knowledge')
  })
})
