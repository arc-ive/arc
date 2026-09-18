# Changelog entry — issue #128

Kept out of the repository by decision at the Phase 2 gate: this repo has no
`CHANGELOG.md`, and introducing one inside a bug-fix PR adds a file the reviewer
did not ask for. This content goes into the pull request description instead.

---

## 2026-09-11 — Tenant profile fields missing from the user-tenants list

Branch `fix/tenant-list-missing-profile-fields`. Not deployed; local verification only.

### 1. The Company page showed "—" for Industry, Address, Phone, Website and Logo URL even though the values were in the database

`GET /users/{user_id}/tenants` selected five of the tenants table's ten columns.
`Tenant` declares its profile fields as `Optional[...] = None`, so omitting them
from the constructor raised nothing — the fields simply arrived as `None` and the
endpoint published `null` for data that existed. The column list and the
constructor were hand-written separately at three call sites in
`db/connection.py`; two stayed correct and the third drifted. The duplication is
the mechanism, so repairing only the third copy would leave the next drift free
to happen.

`_TENANT_COLUMNS`, `_tenant_select_list(alias)` and `_tenant_from_row(row)` now
single-source the projection and the mapping, and every call site goes through
them. A column can no longer be selected without being mapped, or mapped without
being selected.

A **fourth** mapping site was found by the independent verifier after the first
implementation was already passing:
`PostgreSQLTenantRepository.list_all()` hand-wrote a six-column SELECT and its own
`Tenant(...)`, dropping address, phone, website and logo_url. It escaped the
original search because it reaches into `self.db._connection_pool` from the
repository layer rather than delegating like every sibling method. It was
invisible only because `/platform/tenants` publishes a narrower key set — adding
one field to that endpoint would have reproduced this issue verbatim. It now
delegates to a new `ArcDatabase.list_tenants()`, which uses the shared helpers,
matching the delegation pattern the rest of that class already follows.

- **Impact:** the list endpoint returns the same profile values as
  `GET /tenants/{tenant_id}`. Every consumer of the list — Company page and
  Overview page today — sees real data.
- **Verified:** live against the running stack, reproducing the issue's own
  evidence command. `GET /users/ref-acme-technologies-company-admin/tenants`
  returned `"industry": null, "website": null` before; it now returns
  `"industry": "Technology", "website": "https://acme-tech.example.com"` —
  byte-identical to `GET /tenants/ref-acme-technologies`. The Company page
  renders "Technology" where it rendered "—".
- **Known limitation:** only the tenants projection is single-sourced. Users,
  memberships and knowledge still hand-write theirs and can drift the same way.
  A *new* field added to `Tenant` but not to `_TENANT_COLUMNS` would still
  default silently — the mapper prevents query/constructor drift, not
  model/query drift. The claim that this makes the bug class "unrepeatable"
  was an overstatement: four sites existed where three were assumed, and only a
  reviewer's search found the fourth.

### 2. A company profile saved in Settings stayed invisible on the Company page for up to five minutes

Not reported in the issue's root-cause section, but it produces the issue's own
Impact line "Settings page save works but changes aren't visible on Company
page". The save handler invalidated `['tenants', id]` only. The Company and
Overview pages read the tenant from `['users', uid, 'tenants']`, and React Query
invalidation is prefix-matched — neither key is a prefix of the other, so the
list cache was never refreshed. With the Company page's `staleTime` of five
minutes, the stale value survived navigation.

The save handler now also invalidates `queryKeys.userTenants(principal?.sub)`.

- **Impact:** a saved change appears on the Company page on next navigation, with
  no reload and no waiting out the stale window.
- **Verified:** in the browser against the running stack. Changed Industry from
  "Technology" to "Cloud Infrastructure" in Settings, clicked Save, navigated to
  Company — the new value was displayed immediately. Test data restored to
  "Technology" afterwards.
- **Known limitation:** scoped to this one save handler. Other mutations that
  affect tenant data were not audited for the same gap.

### Testing

- `tests/test_tenant_company_config.py::TestUserTenantListCompanyFields` — five
  tests pinning: stored profile values are returned; they equal the single-tenant
  endpoint's, and are asserted non-null so the comparison cannot hold vacuously
  between two nulls; the platform-wide listing carries the profile too, asserted
  at the repository boundary because `/platform/tenants` publishes a narrower key
  set; the response key set is unchanged; an unset profile still reports `null`
  rather than inventing a value.
- `frontend/src/pages/tenant/TenantSettingsPage.test.jsx` — two tests using the
  real `queryKeys` module rather than a mock of it. The first seeds the
  user-tenants cache and asserts the saved mutation actually marks that cache
  entry invalidated — cache state, not a spy call. The second asserts the
  single-tenant query refetches, since the Settings page observes that key itself.
- **Every new test was run against the pre-fix code** in a detached git worktree
  at `f3f3095`, with `PYTHONPATH` confirmed to resolve `arc` to the worktree copy
  rather than the edited one. They failed as designed:
  `assert None == 'Technology'` for the list endpoint,
  `assert None == '1 Market Street'` for the platform listing, and a timeout on
  the frontend invalidation assertion. **3 of 5 backend tests and 1 of 2 frontend
  tests go red pre-fix.** The remaining three are regression guards that pass
  both before and after by design, and prove nothing about the fix on their own.
- **Baseline comparison:** the tenant-relevant subset went 60 passed → 74 passed
  (the count rises partly because `tests/test_platform_tenant_listing.py` joined
  the subset once the fourth site was found). Frontend: 107 passed across 11
  files → 109 across 12.
- **One pre-existing failure exists and is not fixed by this change.** The full
  backend suite is `1 failed, 1590 passed, 1 skipped`:
  `tests/test_dev_auth.py::TestDevAuthNotMountedInProduction::test_dev_login_endpoint_works_in_dev_mode`
  returns 404 where it expects 403, depending on `APP_ENV`. It fails identically
  in a clean worktree at `f3f3095`, so it predates this branch — but CI running
  the whole suite will go red, and that red is not this PR's doing. An earlier
  draft of this entry claimed zero pre-existing failures; that was true only of
  the 60-test subset originally used as the baseline.
- All test runs were pinned to a dedicated `arc_test` database, because the
  suite's session fixture runs `DROP SCHEMA public CASCADE` on whatever
  `DATABASE_URL` names. The seeded dev database was confirmed intact afterwards.
- `ruff check` and `ruff format --check` clean on both changed Python files.
  `oxlint` reports one warning, pre-existing, in `src/auth/AuthContext.jsx`,
  which this change does not touch.

### Known open items, deliberately not addressed

- **Other list endpoints may omit columns the same way** — not audited beyond the
  tenants table. Declared a non-goal at the requirements gate; worth its own
  issue, and the fourth site found late here is an argument for doing it.
- **The frontend test mocks `useAuth` and hardcodes `principal: {sub: 'user-1'}`**
  — the established pattern for page tests in this repo. If the principal's shape
  ever changed, the test would keep passing while production invalidated the
  wrong key. Closing that gap needs an integration test that renders the real
  auth context, which is broader than this fix.
- **`CHANGELOG.md` was not added to the repository** — decided at the Phase 2
  gate, to keep the PR free of files the reviewer did not ask for.
- **Repointing the Company page at `GET /tenants/{id}`** — considered and
  rejected: it would hide the defect for one page while leaving the list
  endpoint's contract violated for every other consumer.
