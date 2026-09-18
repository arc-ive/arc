# Requirements — Issue #128: Company page profile fields show "—" despite data existing in DB

- **Date:** 2026-09-11
- **Asked by:** dev@zeru.finance
- **Status:** draft

## The ask, verbatim

> https://github.com/arc-ive/arc/issues/128 solve this bug go through the work flow and use grill me skill and kickass skill

Grilling answers that set scope (verbatim): **"b, b, a, branch + PR"**

- Q1 → (b) also fix the stale-cache defect, not backend-only
- Q2 → (b) extract a shared row→Tenant mapping rather than a third hand-written copy
- Q3 → (a) run tests against a separate `arc_test` database, plus a real regression test in the suite
- Q4 → branch + PR with `Closes #128`

## Goal

Tenant profile fields (industry, address, phone, website, logo URL) that exist in
the database must reach the Company page — both on first load and immediately
after they are changed in Settings.

## Requirements

| # | Requirement | How it would be proven unmet |
|---|---|---|
| R1 | `GET /users/{user_id}/tenants` returns the stored values of `industry`, `address`, `phone`, `website`, `logo_url` for each tenant in the list | Request the endpoint for a tenant whose DB row has those columns populated; any of the five comes back `null` |
| R2 | For the same tenant, the five profile values from the list endpoint are identical to those from `GET /tenants/{tenant_id}` | Fetch both for one tenant and diff the five fields; any mismatch |
| R3 | The Company page renders the stored profile values instead of `—` when the data exists | Sign in as a reference user whose tenant has profile data; the Company Profile card still shows `—` |
| R4 | After a successful save on the Settings page, the Company page shows the new values without a manual reload and without waiting for a cache expiry window | Save a changed industry in Settings, navigate to Company, observe the previous value |
| R5 | Existing behaviour of the list endpoint is unchanged: same response key set, same self-scoped authorization (403 for another user's ID), same tenant membership filtering | Existing endpoint tests fail, or the response key set differs from before |
| R6 | A regression test lives in the project's own suite and is capable of failing | The test passes when run against the pre-fix code |

## Constraints

- C1: No database schema changes. All five columns already exist on `tenants`.
- C2: Response contract stays backward compatible — no renamed, added, or removed keys.
- C3: Authorization and tenant-scoping semantics are untouched.
- C4: Verification must not destroy the local dev database's seeded reference
  environment. The suite's session fixture runs `DROP SCHEMA public CASCADE`
  against `DATABASE_URL`, which defaults to the dev database.
- C5: Delivered on a branch via pull request, never committed directly to `main`.
- C6: Every changed line traces to a requirement above.

## Non-goals

- **Repointing the Company page at `GET /tenants/{tenant_id}`.** Considered and
  rejected in grilling: it would mask the defect for one page while leaving the
  list endpoint's contract violated for every other consumer.
- **Auditing every other list endpoint** for the same class of column omission.
  Worth doing; belongs in its own issue.
- **Revisiting the caching strategy** (`staleTime` values, global query config).
  Only the missing invalidation for the affected key is in scope.
- **Changing what the Settings page saves** or how it validates.
- Backfilling or modifying any tenant data.

## Open questions

| # | Question | Why it matters | Resolution |
|---|---|---|---|
| Q1 | Is the stale-cache defect in scope? | Fixing only the SQL leaves half the reported symptom alive | Resolved: yes, in scope |
| Q2 | Shared row mapping, or a third hand-written copy? | The duplication is the mechanism that produced the bug | Resolved: shared mapping |
| Q3 | How to verify without wiping the dev database? | The suite drops the public schema | Resolved: separate `arc_test` database |
| Q4 | Delivery route? | Repo convention | Resolved: branch + PR, `Closes #128` |

## Current behaviour

Confirmed by reading the code, not assumed:

- `src/arc/db/connection.py:306-329` — `get_tenants_for_user()` selects only
  `t.id, t.name, t.status, t.created_at, t.updated_at` and constructs `Tenant`
  from those five. The five profile columns are never read.
- `src/arc/domain/models.py:121-134` — `Tenant` declares the profile fields as
  `Optional[...] = None`. Omitting them from the constructor is therefore
  silent: no `TypeError`, just `None`.
- `src/arc/api/controllers.py:604-608` — the endpoint response *does* include all
  five fields, so it publishes `null` for data that exists. The contract is
  violated at the source, not at the edge.
- `src/arc/repositories/tenancy.py:167-169` — `get_tenants_for_user` on the
  repository is a pure pass-through to the database layer; it holds no query of
  its own. One site serves the reported symptom.
- `src/arc/db/connection.py:136-157` and `:188-200` — two *other* sites build a
  `Tenant` from a row, each repeating the ten-column list and the ten-argument
  constructor by hand. Both are currently correct.
- **Correction, found by the independent verifier after this file was first
  written:** there is a *fourth* site.
  `src/arc/repositories/tenancy.py:33-50` — `PostgreSQLTenantRepository.list_all()`
  hand-writes `SELECT id, name, status, industry, created_at, updated_at` and its
  own `Tenant(...)`, omitting address, phone, website and logo_url. It reaches
  into `self.db._connection_pool` directly, unlike every sibling method, which is
  why a search of the database layer missed it. It is invisible today only
  because `/platform/tenants` publishes a narrower key set — widening that
  endpoint would reproduce this issue verbatim. The original claim here that
  there was "exactly one backend site to correct" was wrong.
- `frontend/src/pages/tenant/TenantCompanyPage.jsx:22-27,145-152` — the Company
  page reads the list query and renders `value || '—'` for each profile field.
- `frontend/src/pages/tenant/TenantSettingsPage.jsx:36-42` — on a successful save
  it writes and invalidates `queryKeys.tenant(tenantId)` only.
- `frontend/src/api/queryKeys.js:7-8` — `tenant(id)` is `['tenants', id]` while
  `userTenants(userId)` is `['users', userId, 'tenants']`. React Query
  invalidation is prefix-matched, and neither key is a prefix of the other, so
  the list cache is never invalidated by a save. With the Company page's
  `staleTime: 5 * 60 * 1000`, a saved change stays invisible there for up to
  five minutes.

## Definition of done

> Done means: for a tenant with profile data in the database, the list endpoint
> returns the same five profile values as the single-tenant endpoint; the Company
> page displays them; a save in Settings is reflected on the Company page without
> a reload; the existing endpoint behaviour is unchanged; and each of these is
> demonstrated by a check that was observed to run, including at least one test
> in the project suite that fails against the pre-fix code.
