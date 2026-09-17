# Plan — Issue #128: tenant profile fields missing from the list endpoint

- **Requirements:** `./requirements.md`
- **Approved:** 2026-09-11, by dev@zeru.finance ("approved, go ahead")
- **Status:** in progress

## Approach

Single-source the tenant column list and the row→`Tenant` mapping in
`db/connection.py`, then route all three construction sites through it. The five
missing columns arrive in the list query as a consequence of sharing the
definition, rather than as a hand-patched special case — which is what makes the
bug class unrepeatable rather than merely repaired.

On the frontend, add the missing `userTenants` invalidation to the Settings save
handler so the list cache the Company page reads is refreshed by a save.

Rejected alternatives:

- **Add the five columns only to the list query.** Repairs the symptom, leaves a
  third hand-maintained copy of the same ten-column list in place — the exact
  condition that produced the defect.
- **Repoint the Company page at `GET /tenants/{id}`.** Hides the defect for one
  page; every other consumer of the list endpoint keeps receiving `null` for
  populated data.
- **Derive the mapping from `dataclasses.fields(Tenant)`.** Couples the SQL
  projection to the domain model's field order and would silently pick up any
  future non-persisted field.

## Baseline

Run before any edit, against the dedicated `arc_test` database.

| Check | Command | Result before the change |
|---|---|---|
| Backend, tenant-relevant subset | `DATABASE_URL=postgresql://postgres@localhost:5432/arc_test .venv-demo/bin/pytest tests/test_tenant_company_config.py tests/test_tenant_authorization.py tests/test_tenant_onboarding.py tests/test_repository_integration.py tests/test_authentication.py -q` | **60 passed**, 6 deprecation warnings |
| Frontend suite | `npm test` (in `frontend/`) | **107 passed**, 11 files |
| Dev DB reference data | `SELECT count(*) FROM tenants` on `arc` | 4 tenants, `ref-acme-technologies` has `industry='Technology'` |

Pre-existing failures **in the subset above: none.**

**Correction after the verifier ran the whole suite:** the full backend suite is
`1 failed, 1590 passed, 1 skipped`. The failure is
`tests/test_dev_auth.py::TestDevAuthNotMountedInProduction::test_dev_login_endpoint_works_in_dev_mode`
(404 vs 403, depends on `APP_ENV`). Confirmed pre-existing by running that file
in a detached worktree at `f3f3095`, where it fails identically — it is not
caused by this change. The original baseline was scoped to 60 tenant-relevant
tests, so "no pre-existing failures" was only ever true of that subset; stating
it unqualified was wrong.

Environment note: `arc_test` was created with `OWNER arc`, and `vector` was
installed into it by the `postgres` superuser. Test runs connect as `postgres`
because the suite's session fixture drops and recreates the `public` schema,
which the `arc` role cannot do (it cannot re-create the `vector` extension).

## Steps

| # | Step | Files | Who | Verified by |
|---|---|---|---|---|
| S1 | Add `_TENANT_COLUMNS`, `_tenant_select_list(alias)`, `_tenant_from_row(row)`; route `get_tenant`, `update_tenant`, `get_tenants_for_user` through them | `src/arc/db/connection.py` | self | S3 + the 60 baseline tests |
| S2 | Invalidate `queryKeys.userTenants(principal.sub)` in the save handler alongside the existing tenant key | `frontend/src/pages/tenant/TenantSettingsPage.jsx` | self | S4 |
| S3 | Backend regression test: list endpoint returns the five profile values, and they equal the single-tenant endpoint's; response key set unchanged | `tests/test_tenant_company_config.py` | self | run against pre-fix code via `git stash` — must fail |
| S4 | Frontend test: a successful save invalidates both query keys | `frontend/src/pages/tenant/TenantSettingsPage.test.jsx` | self | run against pre-fix code — must fail |
| S5 | Live end-to-end check in the running local app: sign in, read Company page, edit in Settings, return to Company | — | self | observed browser state |

## Requirement coverage

| Requirement | Covered by | Proven by |
|---|---|---|
| R1 — list endpoint returns profile values | S1 | S3 asserts each of the five is the stored value, not `null` |
| R2 — list matches single-tenant endpoint | S1 | S3 fetches both and compares the five fields |
| R3 — Company page shows values, not `—` | S1 | S5 live browser observation |
| R4 — save is reflected without reload | S2 | S4 asserts the invalidation; S5 observes it end-to-end |
| R5 — no behaviour regression | S1 | 60 baseline tests rerun; S3 asserts the response key set |
| R6 — test can fail | S3, S4 | Both executed against stashed (pre-fix) code |

## Verification strategy

- **Backend test** — `tests/test_tenant_company_config.py`. Asserts, from the
  requirements: the list entry for a tenant carries the five stored profile
  values; those values equal `GET /tenants/{id}`'s; the key set is unchanged.
  - Goes red when: the profile columns are dropped from the list query
    (i.e. against today's code).
- **Frontend test** — `frontend/src/pages/tenant/TenantSettingsPage.test.jsx`.
  Asserts a successful save invalidates both the tenant key and the user-tenants
  key.
  - Goes red when: the `userTenants` invalidation line is removed.
- **Independent verifier:** opus subagent, fresh context (never a fork),
  adversarial brief — given `requirements.md` and the diff, asked to find where
  it fails to meet each requirement.
- **Self-review:** cold line-by-line read of `git diff`, not from memory of intent.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Shared mapper breaks the two currently-correct paths (`get_tenant`, `update_tenant`) | Medium | Those paths are covered by the 60 baseline tests, rerun after the change |
| Table alias handling wrong in the JOIN query (`t.id` vs `id`) | Medium | `_tenant_select_list` takes an explicit alias; asyncpg keys rows by output name, so both shapes yield identical keys — covered by S3 |
| Test run wipes the seeded dev database | Low | All runs pinned to `arc_test`; dev DB row count re-checked after |
| Frontend invalidation fires but the page still reads stale data for another reason | Low | S5 observes the actual rendered page, not just the mock |

## Rollback

Single revert of the feature branch; no schema or data migration is involved, so
nothing persists after a revert. `arc_test` is disposable and separate from the
dev database.
