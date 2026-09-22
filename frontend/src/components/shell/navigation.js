import {
  LayoutDashboard,
  Building2,
  Users,
  Activity,
  BookOpen,
  Gauge,
  Workflow,
  Home,
  UserCircle2,
  Settings,
  Sparkles,
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
/**
 * The five product areas from ARC_UX_SPEC.md §8.
 *
 * Fourteen flat items became five areas with sub-navigation. §8 asks for
 * primary navigation to be "intentionally small", with detailed
 * capabilities in sub-navigation; ARC_PRODUCT_MODEL.md §4 adds that a
 * backend endpoint does not automatically deserve a top-level slot.
 *
 * Grouping only — no route was renamed. The URLs are stable, so nothing
 * that links to them breaks and no redirect table is needed. Where a
 * surface belongs is an information-architecture question; what its path
 * string is, is not.
 *
 * Two items are gone rather than regrouped:
 *
 *   Company   Its data is duplicated by Overview (name, id, status, member
 *             and document counts) and its editable fields live in
 *             Settings — the page said so itself, twice. A page that tells
 *             you to go elsewhere for the real version is not earning a
 *             navigation slot.
 *
 *   Tools     PRD §13: "Tools are platform-owned executable capabilities."
 *             The tenant API is GET ~/tools and POST ~/tools/{name}/execute
 *             — no create, update or delete. There is nothing for a tenant
 *             administrator to manage, so §3's "expose tool management only
 *             where an actual workflow requires it" resolves to: not as a
 *             top-level area. The route stays reachable; PR-6 moves it
 *             inside a skill's allowed-tools configuration.
 *
 * An area renders only if the user can reach at least one thing inside it,
 * and an area with exactly one visible child renders as a single item
 * rather than a group of one.
 */
const AREAS = [
  {
    id: 'ask',
    label: 'Ask Arc',
    icon: Sparkles,
    to: 'ask',
    permission: PERMISSIONS.KNOWLEDGE_READ,
  },
  {
    id: 'brain',
    label: 'Company Brain',
    icon: BookOpen,
    children: [
      { to: 'knowledge', label: 'Knowledge', permission: PERMISSIONS.KNOWLEDGE_READ },
      { to: 'connectors', label: 'Sources', permission: PERMISSIONS.CONNECTOR_READ },
    ],
  },
  {
    id: 'workflows',
    label: 'AI Workflows',
    icon: Workflow,
    children: [
      { to: 'skills', label: 'Skills', permission: PERMISSIONS.SKILL_READ },
      { to: 'agents', label: 'Agents', permission: PERMISSIONS.AGENT_EXECUTE },
    ],
  },
  {
    id: 'operations',
    label: 'Operations',
    icon: Gauge,
    children: [
      { to: 'approvals', label: 'Approvals', permission: PERMISSIONS.APPROVAL_READ },
      { to: 'webhooks', label: 'Activity', permission: PERMISSIONS.WEBHOOK_READ },
      { to: 'usage', label: 'Usage', permission: PERMISSIONS.OBSERVABILITY_READ },
      { to: 'observability', label: 'Health', permission: PERMISSIONS.OBSERVABILITY_READ },
    ],
  },
  {
    id: 'admin',
    label: 'Administration',
    icon: Settings,
    children: [
      { to: 'users', label: 'People', permission: PERMISSIONS.TENANT_READ },
      { to: 'overview', label: 'Workspace', permission: PERMISSIONS.TENANT_READ },
      { to: 'settings', label: 'Settings', permission: PERMISSIONS.TENANT_UPDATE },
    ],
  },
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

  const areas = []
  for (const area of AREAS) {
    if (area.children) {
      const children = area.children.filter((c) => can(c.permission))
      if (children.length === 0) continue
      // A group of one is just an item wearing a group's clothes. When it
      // collapses, keep the AREA label if the survivor is the area's primary
      // child — "Company Brain" is the product concept a user should learn,
      // and "Knowledge" is a worse name for the same destination. If a
      // later child is the survivor, its own label is the specific one
      // ("Agents" beats "AI Workflows" when agents are all you can reach).
      if (children.length === 1) {
        const [only] = children
        const isPrimary = only.to === area.children[0].to
        areas.push({
          ...area,
          to: only.to,
          label: isPrimary ? area.label : only.label,
          children: undefined,
        })
      } else {
        areas.push({ ...area, children })
      }
    } else if (can(area.permission)) {
      areas.push(area)
    }
  }

  // Home is the landing page for a member who cannot read the workspace
  // itself — today that is the Employee. Anyone with TENANT_READ lands on
  // Workspace instead, so offering both would be two names for one job.
  return can(PERMISSIONS.TENANT_READ)
    ? areas
    : [{ ...HOME_ITEM, id: 'home' }, ...areas]
}

/** Flat list of every reachable route, for the command palette. */
export function tenantRoutesForCapabilities(can) {
  return tenantNavForCapabilities(can).flatMap((area) =>
    area.children
      ? area.children.map((c) => ({ ...c, icon: area.icon }))
      : [area],
  )
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
