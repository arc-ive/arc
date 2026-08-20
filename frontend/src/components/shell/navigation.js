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
  Gauge,
  AlertTriangle,
  BarChart3,
  Settings,
  History,
  Sparkles,
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
  { to: '/platform/connectors', label: 'Connectors', icon: Plug },
  { to: '/platform/agents', label: 'Agents', icon: Bot },
  { to: '/platform/observability', label: 'Observability', icon: Activity },
]

const companyAdminTenantNav = [
  { to: 'overview', label: 'Overview', icon: Globe },
  { to: 'company', label: 'Company', icon: Building2 },
  { to: 'knowledge', label: 'Company Brain', icon: BookOpen },
  { to: 'skills', label: 'Skills', icon: Workflow },
  { to: 'operations', label: 'Operations', icon: Gauge },
  { to: 'incidents', label: 'Incidents', icon: AlertTriangle },
  { to: 'users', label: 'Users', icon: UserCog },
  { to: 'usage', label: 'Usage', icon: BarChart3 },
  { to: 'settings', label: 'Settings', icon: Settings },
]

const operationsTenantNav = [
  { to: 'overview', label: 'Overview', icon: Globe },
  { to: 'operations', label: 'Operations', icon: Gauge },
  { to: 'incidents', label: 'Incidents', icon: AlertTriangle },
  { to: 'knowledge', label: 'Company Brain', icon: BookOpen },
  { to: 'skills', label: 'Skills', icon: Workflow },
  { to: 'activity', label: 'Activity', icon: History },
]

const employeeTenantNav = [
  { to: 'home', label: 'Home', icon: Home },
  { to: 'ask', label: 'Ask Arc', icon: Sparkles },
  { to: 'knowledge', label: 'Company Knowledge', icon: BookOpen },
  { to: 'skills', label: 'Procedures', icon: Workflow },
  { to: 'activity', label: 'My Activity', icon: History },
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
        { to: 'operations', label: 'Operations', icon: Gauge },
        { to: 'incidents', label: 'Incidents', icon: AlertTriangle },
        { to: 'users', label: 'Users', icon: UserCog },
        { to: 'usage', label: 'Usage', icon: BarChart3 },
        { to: 'activity', label: 'Activity', icon: History },
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
  operations: 'Operations',
  incidents: 'Incidents',
  users: 'Users',
  usage: 'Usage',
  settings: 'Settings',
  activity: 'Activity',
  ask: 'Ask Arc',
}