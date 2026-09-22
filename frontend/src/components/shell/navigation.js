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
import { PERMISSIONS } from '../../auth/permissions.js'

/**
 * Permission-derived navigation.
 *
 * Every item declares the permission the backend actually requires for the
 * surface it links to — read from `require_tenant_permission(...)` on the
 * corresponding controller, not inferred from the role. An item is rendered
 * only when `GET /auth/me` reports that permission, so navigation can no
 * longer offer a page that answers 403.
 *
 * Navigation is UX only. The backend remains the authorization authority
 * and independently rejects every unauthorized operation.
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

/**
 * The tenant workspace catalogue, in display order.
 *
 * `permission` is the backend requirement for that surface:
 *
 *   ask           POST ~/intelligence/query   KNOWLEDGE_READ
 *   knowledge     GET  ~/knowledge            KNOWLEDGE_READ
 *   overview      GET  ~                      TENANT_READ
 *   company       GET  ~                      TENANT_READ
 *   users         GET  ~/users                TENANT_READ
 *   skills        GET  ~/skills               SKILL_READ
 *   agents        POST /agent/runs            AGENT_EXECUTE
 *   tools         GET  ~/tools                TOOL_READ
 *   connectors    GET  ~/connectors           CONNECTOR_READ
 *   webhooks      GET  ~/webhooks/events      WEBHOOK_READ
 *   observability GET  ~/observability/*      OBSERVABILITY_READ
 *   usage         GET  ~/observability/*      OBSERVABILITY_READ
 *   approvals     GET  ~/approvals            APPROVAL_READ
 *   settings      PUT  ~                      TENANT_UPDATE
 *
 * `settings` is gated on the WRITE permission deliberately: it is a
 * configuration surface, and read-only configuration a user cannot change
 * is not a job anyone has.
 */
const TENANT_NAV = [
  { to: 'ask', label: 'Ask Arc', icon: Sparkles, permission: PERMISSIONS.KNOWLEDGE_READ },
  { to: 'overview', label: 'Overview', icon: Globe, permission: PERMISSIONS.TENANT_READ },
  { to: 'company', label: 'Company', icon: Building2, permission: PERMISSIONS.TENANT_READ },
  { to: 'knowledge', label: 'Company Brain', icon: BookOpen, permission: PERMISSIONS.KNOWLEDGE_READ },
  { to: 'skills', label: 'Skills', icon: Workflow, permission: PERMISSIONS.SKILL_READ },
  { to: 'agents', label: 'Agents', icon: Bot, permission: PERMISSIONS.AGENT_EXECUTE },
  { to: 'tools', label: 'Tools', icon: Wrench, permission: PERMISSIONS.TOOL_READ },
  { to: 'connectors', label: 'Connectors', icon: Plug, permission: PERMISSIONS.CONNECTOR_READ },
  { to: 'webhooks', label: 'Webhooks', icon: Webhook, permission: PERMISSIONS.WEBHOOK_READ },
  { to: 'users', label: 'Users', icon: UserCog, permission: PERMISSIONS.TENANT_READ },
  { to: 'observability', label: 'Observability', icon: Activity, permission: PERMISSIONS.OBSERVABILITY_READ },
  { to: 'approvals', label: 'Approvals', icon: ShieldCheck, permission: PERMISSIONS.APPROVAL_READ },
  { to: 'usage', label: 'Usage', icon: BarChart3, permission: PERMISSIONS.OBSERVABILITY_READ },
  { to: 'settings', label: 'Settings', icon: Settings, permission: PERMISSIONS.TENANT_UPDATE },
]

/** Self-scoped landing page for members without workspace-level read access. */
const HOME_ITEM = { to: 'home', label: 'Home', icon: Home }

/**
 * Tenant navigation for the authenticated user's actual permissions.
 *
 * `can` is the predicate from `useCapabilities()`, which reads the backend's
 * own permission matrix out of `GET /auth/me`. An unresolved profile reports
 * no permissions, so this returns an empty list rather than the full product
 * surface — navigation fails closed (ARC_V2_PRD.md P4).
 */
export function tenantNavForCapabilities(can) {
  if (typeof can !== 'function') return []

  const items = TENANT_NAV.filter((item) => can(item.permission))

  // Home is the landing page for a member who cannot read the workspace
  // itself — today that is the Employee. Anyone with TENANT_READ lands on
  // Overview instead, so offering both would be two names for one job.
  return can(PERMISSIONS.TENANT_READ) ? items : [HOME_ITEM, ...items]
}

/** Landing route within a tenant for the authenticated user. */
export function tenantLandingForCapabilities(can) {
  if (typeof can !== 'function') return 'home'
  return can(PERMISSIONS.TENANT_READ) ? 'overview' : 'home'
}

/** Label shown for the tenant workspace's root in breadcrumbs. */
export const tenantBreadcrumbLabels = {
  overview: 'Overview',
  company: 'Company',
  home: 'Home',
  knowledge: 'Company Brain',
  skills: 'Skills',
  agents: 'Agents',
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
