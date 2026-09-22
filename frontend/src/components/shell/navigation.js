import {
  LayoutDashboard,
  Building2,
  Users,
  Plug,
  Bot,
  Activity,
  BookOpen,
  Globe,
  UserCog,
  Workflow,
  Home,
  UserCircle2,
  BarChart3,
  Settings,
  Sparkles,
  Webhook,
  Wrench,
  ShieldCheck,
} from 'lucide-react'
import { APPLICATION_ROLES } from '../../auth/useMe.js'

/**
 * Capability-aware navigation.
 *
 * Navigation is derived from the authenticated user's authorized profile
 * (`GET /auth/me`): the platform console is only offered to platform
 * administrators, and tenant navigation adapts to the tenant persona
 * (company administrator / operations user / employee).
 *
 * Route guards and navigation are UX only. The backend remains the
 * authorization authority and independently rejects unauthorized
 * operations.
 */

export const personalNav = [
  { to: '/app/profile', label: 'Profile', icon: UserCircle2 },
]

export const platformNav = [
  { to: '/platform/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/platform/tenants', label: 'Tenants', icon: Building2 },
  { to: '/platform/users', label: 'Users', icon: Users },
  { to: '/platform/observability', label: 'Observability', icon: Activity },
]

const companyAdminTenantNav = [
  { to: 'overview', label: 'Overview', icon: Globe },
  { to: 'company', label: 'Company', icon: Building2 },
  { to: 'knowledge', label: 'Company Brain', icon: BookOpen },
  { to: 'skills', label: 'Skills', icon: Workflow },
  { to: 'agents', label: 'Agents', icon: Bot },
  { to: 'tools', label: 'Tools', icon: Wrench },
  { to: 'connectors', label: 'Connectors', icon: Plug },
  { to: 'webhooks', label: 'Webhooks', icon: Webhook },
  { to: 'users', label: 'Users', icon: UserCog },
  { to: 'observability', label: 'Observability', icon: Activity },
  { to: 'approvals', label: 'Approvals', icon: ShieldCheck },
  { to: 'usage', label: 'Usage', icon: BarChart3 },
  { to: 'settings', label: 'Settings', icon: Settings },
]

const operationsTenantNav = [
  { to: 'overview', label: 'Overview', icon: Globe },
  { to: 'knowledge', label: 'Company Brain', icon: BookOpen },
  { to: 'skills', label: 'Skills', icon: Workflow },
  { to: 'agents', label: 'Agents', icon: Bot },
]

/**
 * Employee navigation is intentionally minimal.
 *
 * EMPLOYEE holds knowledge:read (authorization.py) for Ask Arc (Unified
 * Intelligence) and Company Brain read access per PRD §7.4. Backend
 * endpoints for skills, tools, connectors, webhooks, observability,
 * approvals, and knowledge management (create) require permissions the
 * employee role does not hold. Showing those nav items would present
 * pages that return 403 on every API call. Only Home (self-scoped) and
 * Ask Arc (knowledge:read authorization boundary) are accessible.
 */
const employeeTenantNav = [
  { to: 'home', label: 'Home', icon: Home },
  { to: 'ask', label: 'Ask Arc', icon: Sparkles },
]

/**
 * Tenant navigation for a given application role.
 *
 * The tenant persona is derived from the user's application role:
 * platform and company administrators get the full tenant workspace,
 * operations users get the operational workspace, employees get the
 * employee workspace. Unknown roles (and Demo Mode) get the full surface
 * for inspection — the backend still enforces every operation.
 */
export function tenantNavForRole(role) {
  switch (role) {
    case APPLICATION_ROLES.PLATFORM_ADMINISTRATOR:
    case APPLICATION_ROLES.COMPANY_ADMINISTRATOR:
      return companyAdminTenantNav
    case APPLICATION_ROLES.OPERATIONS_USER:
      return operationsTenantNav
    case APPLICATION_ROLES.EMPLOYEE:
      return employeeTenantNav
    default:
      return [
        { to: 'home', label: 'Home', icon: Home },
        { to: 'ask', label: 'Ask Arc', icon: Sparkles },
        { to: 'overview', label: 'Overview', icon: Globe },
        { to: 'company', label: 'Company', icon: Building2 },
        { to: 'knowledge', label: 'Company Brain', icon: BookOpen },
        { to: 'skills', label: 'Skills', icon: Workflow },
        { to: 'tools', label: 'Tools', icon: Wrench },
        { to: 'connectors', label: 'Connectors', icon: Plug },
        { to: 'webhooks', label: 'Webhooks', icon: Webhook },
                    { to: 'users', label: 'Users', icon: UserCog },
        { to: 'observability', label: 'Observability', icon: Activity },
        { to: 'approvals', label: 'Approvals', icon: ShieldCheck },
        { to: 'usage', label: 'Usage', icon: BarChart3 },
              { to: 'settings', label: 'Settings', icon: Settings },
      ]
  }
}

/** Landing page within a tenant for the given role. */
export function tenantLandingForRole(role) {
  return role === APPLICATION_ROLES.EMPLOYEE ? 'home' : 'overview'
}

/** Label shown for the tenant workspace's root in breadcrumbs. */
export const tenantBreadcrumbLabels = {
  overview: 'Overview',
  company: 'Company',
  home: 'Home',
  knowledge: 'Company Brain',
  skills: 'Skills',
  tools: 'Tools',
  connectors: 'Connectors',
  webhooks: 'Webhooks',
  users: 'Users',
  observability: 'Observability',
  usage: 'Usage',
  settings: 'Settings',
  approvals: 'Approvals',
  ask: 'Ask Arc',
}