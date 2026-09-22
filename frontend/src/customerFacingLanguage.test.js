import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { KNOWLEDGE_SOURCES } from './api/endpoints/knowledge.js'
import { sourceLabels } from './lib/sources.js'

/**
 * PR-1 regression guard for ARC_UX_SPEC.md §1.
 *
 * "Never expose internal engineering state as customer-facing UX. Do not
 * display: backend contract pending, telemetry not wired, internal service
 * names, database terminology, implementation TODOs."
 *
 * This is a source-level scan rather than a render test on purpose: the
 * requirement is that these terms appear on NO customer-facing surface, and
 * rendering every page in every permission state to prove a negative would
 * be both slower and less complete. Comments are excluded — the prohibition
 * is on what a customer can read, not on how the code explains itself.
 */

const SRC = dirname(fileURLToPath(import.meta.url))

function sourceFiles(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      sourceFiles(full, acc)
    } else if (/\.jsx?$/.test(entry) && !/\.test\.jsx?$/.test(entry)) {
      acc.push(full)
    }
  }
  return acc
}

/** Strip block and line comments so JSDoc/rationale never trips the scan. */
function strippedOfComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

const FORBIDDEN = [
  // Internal build status — the PendingContract family.
  { term: 'Backend contract pending', why: 'UX_SPEC §1 — internal build status' },
  { term: 'not wired yet', why: 'UX_SPEC §1 — internal build status' },
  { term: 'Contract pending', why: 'UX_SPEC §1 — internal build status' },
  { term: 'has not been implemented', why: 'UX_SPEC §1 — implementation TODO' },
  // Internal service / runtime names.
  { term: 'OmniRoute', why: 'UX_SPEC §1 — internal service name' },
  { term: 'Unified Intelligence', why: 'UX_SPEC §1 — internal service name' },
  // Internal documentation identifiers.
  { term: 'ADR-', why: 'UX_SPEC §1 — internal documentation identifier' },
  // Database / tenancy terminology leaking into product copy.
  { term: 'tenant-scoped', why: 'UX_SPEC §1 — database terminology' },
  { term: 'Tenant-scoped', why: 'UX_SPEC §1 — database terminology' },
]

/** Raw permission identifiers, e.g. `knowledge:read`, rendered to a customer. */
const PERMISSION_STRING = /\b(knowledge|skill|tool|agent|approval|observability|connector|webhook|tenant|user|membership|capability):[a-z_]+/

describe('customer-facing language (ARC_UX_SPEC §1)', () => {
  const files = sourceFiles(SRC)

  it('scans a meaningful number of source files', () => {
    // Guards the guard: a broken walk would make every assertion below vacuous.
    expect(files.length).toBeGreaterThan(40)
  })

  for (const { term, why } of FORBIDDEN) {
    it(`never renders "${term}" — ${why}`, () => {
      const offenders = files.filter((f) =>
        strippedOfComments(readFileSync(f, 'utf8')).includes(term),
      )
      expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
    })
  }

  it('never renders a raw permission identifier to a customer', () => {
    const offenders = []
    for (const file of files) {
      const body = strippedOfComments(readFileSync(file, 'utf8'))
      for (const line of body.split('\n')) {
        // Permission checks in code are correct and expected; only copy is in scope.
        if (/can\(|hasRole|APPLICATION_ROLES|requiredPermissions|permissions/.test(line)) continue
        if (PERMISSION_STRING.test(line)) {
          offenders.push(`${file.replace(SRC, 'src')}: ${line.trim().slice(0, 80)}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})

describe('incident_report knowledge source (PR-1 decision B1)', () => {
  /**
   * The dedicated Incidents entity is out of scope (V2-ADR-021, PRD §24) and
   * its route, page and nav entries were removed. `incident_report` is a
   * different thing: one of six backend KnowledgeSource values, creatable
   * today. Removing its filter would hide real documents, so the tab was
   * renamed rather than deleted.
   */
  it('remains a supported knowledge source', () => {
    expect(KNOWLEDGE_SOURCES).toContain('incident_report')
  })

  it('still has a human label', () => {
    expect(sourceLabels.incident_report).toBe('Incident report')
  })

  it('is labelled "Incident reports" in the Company Brain filter, not "Incidents"', () => {
    const page = readFileSync(join(SRC, 'pages/brain/CompanyBrainPage.jsx'), 'utf8')
    expect(page).toContain("{ value: 'incident_report', label: 'Incident reports' }")
    expect(page).not.toContain("{ value: 'incident_report', label: 'Incidents' }")
  })
})
