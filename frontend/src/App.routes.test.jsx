import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import {
  LegacyBrainDocumentRedirect,
  LegacyBrainRedirect,
  RemovedTenantRedirect,
} from './App.jsx'

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

/**
 * PR-1. Operations, Incidents and Activity were shells that called no API and
 * rendered internal build status (UX_SPEC §1); Incidents additionally
 * contradicted V2-ADR-021 and PRD §24. The pages are gone, but their URLs
 * must not 404 — existing bookmarks resolve to a live destination.
 */
function renderRemovedAt(initialPath) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/app/t/:tenantId/operations"
          element={<RemovedTenantRedirect to="observability" />}
        />
        <Route
          path="/app/t/:tenantId/activity"
          element={<RemovedTenantRedirect to="observability" />}
        />
        <Route
          path="/app/t/:tenantId/incidents"
          element={<RemovedTenantRedirect to="overview" />}
        />
        <Route path="/app/t/:tenantId/observability" element={<LocationProbe />} />
        <Route path="/app/t/:tenantId/overview" element={<LocationProbe />} />
        <Route path="*" element={<div data-testid="location">NO_MATCH</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('removed tenant surfaces redirect instead of 404', () => {
  it('redirects /operations to the observability surface that is actually wired', () => {
    renderRemovedAt('/app/t/acme/operations')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/observability')
  })

  it('redirects /activity to observability', () => {
    renderRemovedAt('/app/t/acme/activity')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/observability')
  })

  it('redirects /incidents to the workspace landing page', () => {
    // Deliberately NOT a "live incidents equivalent" — V2-ADR-021 means no
    // such surface exists, and the redirect must not imply otherwise.
    renderRemovedAt('/app/t/acme/incidents')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme/overview')
  })

  it('never leaves a removed surface unmatched', () => {
    for (const path of ['operations', 'activity', 'incidents']) {
      const { unmount } = renderRemovedAt(`/app/t/acme/${path}`)
      expect(screen.getByTestId('location')).not.toHaveTextContent('NO_MATCH')
      unmount()
    }
  })

  it('encodes tenant ids that need escaping', () => {
    renderRemovedAt('/app/t/acme%2Fops/operations')
    expect(screen.getByTestId('location')).toHaveTextContent('/app/t/acme%2Fops/observability')
  })
})
