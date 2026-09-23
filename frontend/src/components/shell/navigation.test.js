import { describe, it, expect } from 'vitest'
import {
  tenantNavForCapabilities,
  tenantRoutesForCapabilities,
} from './navigation.js'
import { PERMISSIONS } from '../../auth/permissions.js'

const ALL = Object.values(PERMISSIONS)
const canOf = (perms) => (p) => perms.includes(p)

const routesOf = (nav) =>
  nav.flatMap((a) => (a.children ? a.children.map((c) => c.to) : [a.to]))

describe('tenant navigation areas', () => {
  it('fails closed when capabilities are unknown', () => {
    // ARC_V2_PRD.md P4. The previous default case returned the FULL
    // product surface for an unresolved role; the minimum is what a
    // principal with nothing should see.
    expect(tenantNavForCapabilities(undefined)).toEqual([])

    // With no permissions the only offer is Home — self-scoped, and
    // reachable only by an actual member since RequireTenant blocks
    // non-members outright. Nothing from the product surface leaks in.
    const none = tenantNavForCapabilities(canOf([]))
    expect(none.map((a) => a.to)).toEqual(['home'])
    expect(routesOf(none)).not.toContain('knowledge')
    expect(routesOf(none)).not.toContain('settings')
  })

  it('groups a full-permission user into the five areas of UX_SPEC §8', () => {
    const nav = tenantNavForCapabilities(canOf(ALL))
    expect(nav.map((a) => a.label)).toEqual([
      'Ask Arc',
      'Company Brain',
      'AI Workflows',
      'Operations',
      'Administration',
    ])
  })

  it('collapses an area with one visible child to a single item', () => {
    // Employee holds knowledge:read and agent:execute only.
    const nav = tenantNavForCapabilities(
      canOf([PERMISSIONS.KNOWLEDGE_READ, PERMISSIONS.AGENT_EXECUTE]),
    )
    const brain = nav.find((a) => a.to === 'knowledge')
    expect(brain).toBeDefined()
    expect(brain.children).toBeUndefined()
  })

  it('keeps the AREA label when the survivor is the primary child', () => {
    // "Company Brain" is the product concept; "Knowledge" is a worse name
    // for the same destination.
    const nav = tenantNavForCapabilities(canOf([PERMISSIONS.KNOWLEDGE_READ]))
    expect(nav.find((a) => a.to === 'knowledge').label).toBe('Company Brain')
  })

  it('keeps the CHILD label when a later child is the survivor', () => {
    // "Agents" beats "AI Workflows" when agents are all you can reach.
    const nav = tenantNavForCapabilities(canOf([PERMISSIONS.AGENT_EXECUTE]))
    expect(nav.find((a) => a.to === 'agents').label).toBe('Agents')
  })
})

/**
 * Fixes requested in review on #282.
 */
describe('review fixes (#282)', () => {
  const nav = tenantNavForCapabilities(canOf(ALL))
  const routes = routesOf(nav)

  it('labels the webhook route Webhooks, not Activity', () => {
    // The route serves GET ~/webhooks/events. "Activity" promises every
    // kind of workspace activity and delivers one slice of it.
    const ops = nav.find((a) => a.label === 'Operations')
    expect(ops.children.find((c) => c.to === 'webhooks').label).toBe('Webhooks')
    expect(ops.children.some((c) => c.label === 'Activity')).toBe(false)
  })

  it('offers no second view of the usage-summary endpoint', () => {
    // Observability was labelled "Health" but called the same
    // getTenantUsageSummary endpoint as Usage and rendered a card titled
    // "Usage Summary". The two are merged.
    expect(routes).not.toContain('observability')
    expect(nav.some((a) => a.children?.some((c) => c.label === 'Health'))).toBe(false)
    expect(routes).toContain('usage')
  })

  it('keeps Tools out of the sidebar', () => {
    // PRD §13: platform-owned, and the tenant API has no create/update/
    // delete. Nothing to manage at the top level.
    expect(routes).not.toContain('tools')
  })

  it('but still offers Tools in the command palette', () => {
    // Removing it from navigation should not make a live executable
    // capability reachable only by typing a URL.
    const palette = tenantRoutesForCapabilities(canOf(ALL)).map((r) => r.to)
    expect(palette).toContain('tools')
  })

  it('does not offer Tools in the palette without tool:read', () => {
    const palette = tenantRoutesForCapabilities(
      canOf([PERMISSIONS.KNOWLEDGE_READ]),
    ).map((r) => r.to)
    expect(palette).not.toContain('tools')
  })

  it('makes the palette a superset of the sidebar, never a subset', () => {
    const palette = tenantRoutesForCapabilities(canOf(ALL)).map((r) => r.to)
    for (const route of routes) expect(palette).toContain(route)
    expect(palette.length).toBeGreaterThan(routes.length)
  })
})
