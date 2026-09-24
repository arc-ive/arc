# Phase 3 Findings

## Application defects

None found. All exercised workflows behave per the documented authorization model.

## Validation (2026-09-24, branch `phase3/critical-workflows-e2e`)

- Phase 3 E2E: 4/4 pass (`approval-lifecycle`, `agent-run`, 2× `rbac-matrix`) + auth setup.
- Regressions: Phase 1 smoke 6/6, Phase 2 tenant E2E 2/2, backend matrix+RBAC+approval suites 135 passed, Vitest 396 passed / 3 pre-existing failures (see below).
- One test-only strengthening during review: `agent-run.spec.js` now also asserts `trace.goal`, `trace.status === 'failed'`, and `trace.steps === []` (header comment already claimed zero tool executions).

## Test-infrastructure findings (TEST-INFRA, resolved in-test)

- `authorization_override` replaces (not merges) the role map — matrix tests register both users in one call.
- Cookie-authed API calls require explicit `X-CSRF-Token` from stored cookies (`e2e/helpers/api.js`).
- Skill names render PII-redacted; E2E locators use stable numeric suffixes.
- `authorization_override` + second company-admin: reference data provides only one company-admin per tenant, so four-eyes E2E pairs ops-user (requester) with company-admin (decider).
- Local runs need `POSTGRES_DB=arc_test` (Issue #232 guard) and the dev `APPLICATION_ROLE_ASSIGNMENTS` mapping.

## Pre-existing failures (not caused by Phase 3)

- Vitest `customerFacingLanguage`, `designFoundation`, `accessibility` scan failures reproduce on clean `origin/main` **on Windows only** (forward-slash path comparisons against `node:path.join()` output; Linux CI on `main` is green). Fixed in Phase 4 by normalising separators at the scan ingestion boundary.
