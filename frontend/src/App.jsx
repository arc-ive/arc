import { Navigate, Outlet, Route, Routes, useParams } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth.jsx'
import { RequirePlatformAdmin } from './auth/RequirePlatformAdmin.jsx'
import { RequirePermission } from './auth/RequirePermission.jsx'
import { PERMISSIONS } from './auth/permissions.js'
import { useAuth } from './auth/useAuth.js'
import { useCapabilities } from './auth/capabilities.js'
import { AppShell } from './components/shell/AppShell.jsx'
import { LoginPage } from './pages/login/LoginPage.jsx'
import { WorkspaceDispatch } from './pages/workspace/WorkspaceDispatch.jsx'
import { ProfilePage } from './pages/profile/ProfilePage.jsx'
import { TenantLayout } from './pages/tenant/TenantLayout.jsx'
import { TenantOverviewPage } from './pages/tenant/TenantOverviewPage.jsx'
import { TenantCompanyPage } from './pages/tenant/TenantCompanyPage.jsx'
import { TenantUsagePage } from './pages/tenant/TenantUsagePage.jsx'
import { TenantSettingsPage } from './pages/tenant/TenantSettingsPage.jsx'
import { ConnectorsPage } from './pages/connectors/ConnectorsPage.jsx'
import { WebhooksPage } from './pages/webhooks/WebhooksPage.jsx'
import { ToolsPage } from './pages/tools/ToolsPage.jsx'
import { ObservabilityPage } from './pages/observability/ObservabilityPage.jsx'
import { TenantUsersPage } from './pages/tenant/TenantUsersPage.jsx'
import { ApprovalsPage } from './pages/approvals/ApprovalsPage.jsx'
import { EmployeeHomePage } from './pages/home/EmployeeHomePage.jsx'
import { AskArcPage } from './pages/tenant/AskArcPage.jsx'
import { CompanyBrainPage } from './pages/brain/CompanyBrainPage.jsx'
import { NewKnowledgePage } from './pages/brain/NewKnowledgePage.jsx'
import { KnowledgeDetailPage } from './pages/brain/KnowledgeDetailPage.jsx'
import { SkillsPage } from './pages/skills/SkillsPage.jsx'
import { PlatformDashboardPage } from './pages/platform/PlatformDashboardPage.jsx'
import { PlatformTenantsPage } from './pages/platform/PlatformTenantsPage.jsx'
import { PlatformTenantDetailPage } from './pages/platform/PlatformTenantDetailPage.jsx'
import { PlatformUsersPage } from './pages/platform/PlatformUsersPage.jsx'
import { PlatformObservabilityPage } from './pages/platform/PlatformObservabilityPage.jsx'
import { NotFoundPage } from './pages/NotFoundPage.jsx'
import { tenantLandingForCapabilities } from './components/shell/navigation.js'
import { AgentRunsPage } from './pages/agents/AgentRunsPage.jsx'

/**
 * ARC routing architecture.
 *
 * - `/login`            — authentication (dev JWT / demo mode)
 * - `/app`              — authenticated entry: dispatches to the correct
 *                         experience for the authorized context
 * - `/app/profile`      — personal profile & session
 * - `/app/t/:tenantId/*`— tenant workspace (persona-aware)
 * - `/platform/*`       — ARC platform console (platform administrators)
 *
 * Route guards are UX. The backend remains the authorization authority and
 * rejects any unauthorized request, including direct cross-tenant URLs.
 */

function RootRedirect() {
  const { isAuthenticated } = useAuth()
  return <Navigate to={isAuthenticated ? '/app' : '/login'} replace />
}

function TenantLandingRedirect() {
  const { tenantId } = useParams()
  const { can } = useCapabilities()
  if (!tenantId) return <Navigate to="/app" replace />
  const landing = tenantLandingForCapabilities(can)
  return <Navigate to={`/app/t/${encodeURIComponent(tenantId)}/${landing}`} replace />
}

/**
 * Redirect for a tenant surface that has been removed.
 *
 * Absolute by construction, for the same reason as the Company Brain
 * aliases below: a relative `to` resolves against the matched route and
 * lands on a nested path that does not exist.
 */
export function RemovedTenantRedirect({ to }) {
  const { tenantId } = useParams()
  if (!tenantId) return <Navigate to="/app" replace />
  return <Navigate to={`/app/t/${encodeURIComponent(tenantId)}/${to}`} replace />
}

export function LegacyBrainRedirect({ suffix = '' }) {
  const { tenantId } = useParams()
  return (
    <Navigate to={`/app/t/${encodeURIComponent(tenantId)}/knowledge${suffix}`} replace />
  )
}

export function LegacyBrainDocumentRedirect() {
  const { tenantId, documentId } = useParams()
  return (
    <Navigate
      to={`/app/t/${encodeURIComponent(tenantId)}/knowledge/${encodeURIComponent(documentId)}`}
      replace
    />
  )
}

function Protected() {
  return (
    <RequireAuth>
      <AppShell />
    </RequireAuth>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/session" element={<Navigate to="/login" replace />} />

      <Route element={<Protected />}>
        <Route path="/app" element={<Outlet />}>
          <Route index element={<WorkspaceDispatch />} />
          <Route path="profile" element={<ProfilePage />} />

          {/* Legacy aliases — preserved so existing bookmarks keep working */}
          <Route path="dashboard" element={<Navigate to="/platform/dashboard" replace />} />
          <Route path="home" element={<Navigate to="/app" replace />} />
          <Route path="tenants" element={<Navigate to="/platform/tenants" replace />} />
          <Route path="users" element={<Navigate to="/platform/users" replace />} />
          <Route path="connectors" element={<Navigate to="/platform/dashboard" replace />} />
          <Route path="agents" element={<Navigate to="/platform/dashboard" replace />} />
          <Route path="observability" element={<Navigate to="/platform/observability" replace />} />

          {/* Tenant workspace */}
          <Route path="t/:tenantId" element={<TenantLayout />}>
            <Route index element={<TenantLandingRedirect />} />
            <Route path="home" element={<EmployeeHomePage />} />

            {/* Every workspace route is gated on the permission its own
                controller declares via `require_tenant_permission(...)`,
                not on a role. The previous single `isEmployee` gate both
                failed open while the profile loaded and stood in for
                fourteen distinct permissions at once. */}
            <Route element={<RequirePermission permission={PERMISSIONS.KNOWLEDGE_READ} />}>
              {/* POST ~/intelligence/query requires KNOWLEDGE_READ, not
                  AGENT_EXECUTE — Ask Arc is gated on what it actually calls. */}
              <Route path="ask" element={<AskArcPage />} />
              <Route path="knowledge" element={<CompanyBrainPage />} />
              <Route path="knowledge/:documentId" element={<KnowledgeDetailPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.KNOWLEDGE_CREATE} />}>
              <Route path="knowledge/new" element={<NewKnowledgePage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.TENANT_READ} />}>
              <Route path="overview" element={<TenantOverviewPage />} />
              <Route path="company" element={<TenantCompanyPage />} />
              <Route path="users" element={<TenantUsersPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.TENANT_UPDATE} />}>
              <Route path="settings" element={<TenantSettingsPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.SKILL_READ} />}>
              <Route path="skills" element={<SkillsPage view="list" />} />
              <Route path="skills/:skillId" element={<SkillsPage view="detail" />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.SKILL_CREATE} />}>
              <Route path="skills/new" element={<SkillsPage view="new" />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.AGENT_EXECUTE} />}>
              <Route path="agents" element={<AgentRunsPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.TOOL_READ} />}>
              <Route path="tools" element={<ToolsPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.CONNECTOR_READ} />}>
              <Route path="connectors" element={<ConnectorsPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.WEBHOOK_READ} />}>
              <Route path="webhooks" element={<WebhooksPage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.OBSERVABILITY_READ} />}>
              <Route path="observability" element={<ObservabilityPage />} />
              <Route path="usage" element={<TenantUsagePage />} />
            </Route>

            <Route element={<RequirePermission permission={PERMISSIONS.APPROVAL_READ} />}>
              <Route path="approvals" element={<ApprovalsPage />} />
            </Route>

              {/* Removed tenant surfaces (V2-ADR-021, PRD §24, UX_SPEC §1).
                  Operations, Incidents and Activity were shells that called
                  no API and rendered internal build status. Operations and
                  Activity resolve to Observability — the operational
                  surface that is actually wired. Incidents has no live
                  equivalent by design, so it resolves to the workspace
                  landing page rather than implying one exists. */}
              <Route
                path="operations"
                element={<RemovedTenantRedirect to="observability" />}
              />
              <Route
                path="activity"
                element={<RemovedTenantRedirect to="observability" />}
              />
              <Route
                path="incidents"
                element={<RemovedTenantRedirect to="overview" />}
              />

              {/* Legacy Company Brain aliases. Issue #225: these must be
                  ABSOLUTE. A relative `to` resolves against the matched
                  route, so "knowledge" from /company-brain landed on
                  /knowledge/knowledge — a 404 document id. */}
              <Route path="company-brain" element={<LegacyBrainRedirect />} />
              <Route path="company-brain/new" element={<LegacyBrainRedirect suffix="/new" />} />
              <Route
                path="company-brain/:documentId"
                element={<LegacyBrainDocumentRedirect />}
              />
          </Route>
        </Route>

        {/* Platform console — restricted to platform administrators */}
        <Route
          path="/platform"
          element={
            <RequirePlatformAdmin>
              <Outlet />
            </RequirePlatformAdmin>
          }
        >
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<PlatformDashboardPage />} />
          <Route path="tenants" element={<PlatformTenantsPage />} />
          <Route path="tenants/:tenantId" element={<PlatformTenantDetailPage />} />
          <Route path="users" element={<PlatformUsersPage />} />
          <Route path="observability" element={<PlatformObservabilityPage />} />

          {/* Removed platform surfaces. Neither was backed by a usable
              workflow; both exposed implementation detail. Old links
              resolve to the console root rather than 404. */}
          <Route path="connectors" element={<Navigate to="/platform/dashboard" replace />} />
          <Route path="agents" element={<Navigate to="/platform/dashboard" replace />} />
        </Route>
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}