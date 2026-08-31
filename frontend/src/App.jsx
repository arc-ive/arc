import { Navigate, Outlet, Route, Routes, useParams } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth.jsx'
import { useAuth } from './auth/useAuth.js'
import { useCapabilities } from './auth/capabilities.js'
import { AppShell } from './components/shell/AppShell.jsx'
import { LoginPage } from './pages/login/LoginPage.jsx'
import { WorkspaceDispatch } from './pages/workspace/WorkspaceDispatch.jsx'
import { ProfilePage } from './pages/profile/ProfilePage.jsx'
import { TenantLayout } from './pages/tenant/TenantLayout.jsx'
import { TenantOverviewPage } from './pages/tenant/TenantOverviewPage.jsx'
import { TenantCompanyPage } from './pages/tenant/TenantCompanyPage.jsx'
import { TenantIncidentsPage } from './pages/tenant/TenantIncidentsPage.jsx'
import { TenantUsagePage } from './pages/tenant/TenantUsagePage.jsx'
import { TenantSettingsPage } from './pages/tenant/TenantSettingsPage.jsx'
import { TenantActivityPage } from './pages/tenant/TenantActivityPage.jsx'
import { ConnectorsPage } from './pages/connectors/ConnectorsPage.jsx'
import { WebhooksPage } from './pages/webhooks/WebhooksPage.jsx'
import { ToolsPage } from './pages/tools/ToolsPage.jsx'
import { ObservabilityPage } from './pages/observability/ObservabilityPage.jsx'
import { TenantUsersPage } from './pages/tenant/TenantUsersPage.jsx'
import { TenantOperationsPage } from './pages/tenant/TenantOperationsPage.jsx'
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
import { PlatformConnectorsPage } from './pages/platform/PlatformConnectorsPage.jsx'
import { PlatformAgentsPage } from './pages/platform/PlatformAgentsPage.jsx'
import { PlatformObservabilityPage } from './pages/platform/PlatformObservabilityPage.jsx'
import { NotFoundPage } from './pages/NotFoundPage.jsx'
import { tenantLandingForRole } from './components/shell/navigation.js'

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
  const { role } = useCapabilities()
  if (!tenantId) return <Navigate to="/app" replace />
  const landing = tenantLandingForRole(role)
  return <Navigate to={`/app/t/${encodeURIComponent(tenantId)}/${landing}`} replace />
}

function LegacyBrainDocumentRedirect() {
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
          <Route path="connectors" element={<Navigate to="/platform/connectors" replace />} />
          <Route path="agents" element={<Navigate to="/platform/agents" replace />} />
          <Route path="observability" element={<Navigate to="/platform/observability" replace />} />

          {/* Tenant workspace */}
          <Route path="t/:tenantId" element={<TenantLayout />}>
            <Route index element={<TenantLandingRedirect />} />
            <Route path="home" element={<EmployeeHomePage />} />
            <Route path="overview" element={<TenantOverviewPage />} />
            <Route path="company" element={<TenantCompanyPage />} />
            <Route path="knowledge" element={<CompanyBrainPage />} />
            <Route path="knowledge/new" element={<NewKnowledgePage />} />
            <Route path="knowledge/:documentId" element={<KnowledgeDetailPage />} />
            <Route path="skills" element={<SkillsPage view="list" />} />
            <Route path="skills/new" element={<SkillsPage view="new" />} />
            <Route path="skills/:skillId" element={<SkillsPage view="detail" />} />
            <Route path="tools" element={<ToolsPage />} />
            <Route path="connectors" element={<ConnectorsPage />} />
            <Route path="webhooks" element={<WebhooksPage />} />
            <Route path="operations" element={<TenantOperationsPage />} />
            <Route path="incidents" element={<TenantIncidentsPage />} />
            <Route path="users" element={<TenantUsersPage />} />
            <Route path="observability" element={<ObservabilityPage />} />
            <Route path="usage" element={<TenantUsagePage />} />
            <Route path="settings" element={<TenantSettingsPage />} />
            <Route path="approvals" element={<ApprovalsPage />} />
            <Route path="activity" element={<TenantActivityPage />} />
            <Route path="ask" element={<AskArcPage />} />

            {/* Legacy Company Brain aliases */}
            <Route path="company-brain" element={<Navigate to="knowledge" replace />} />
            <Route path="company-brain/new" element={<Navigate to="knowledge/new" replace />} />
            <Route
              path="company-brain/:documentId"
              element={<LegacyBrainDocumentRedirect />}
            />
          </Route>
        </Route>

        {/* Platform console */}
        <Route path="/platform" element={<Outlet />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<PlatformDashboardPage />} />
          <Route path="tenants" element={<PlatformTenantsPage />} />
          <Route path="tenants/:tenantId" element={<PlatformTenantDetailPage />} />
          <Route path="users" element={<PlatformUsersPage />} />
          <Route path="connectors" element={<PlatformConnectorsPage />} />
          <Route path="agents" element={<PlatformAgentsPage />} />
          <Route path="observability" element={<PlatformObservabilityPage />} />
        </Route>
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}