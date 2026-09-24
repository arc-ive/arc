# ARC Test Strategy (Phase 0)

## Principles

1. Tenant isolation is tested at every layer that enforces it (SQL, service, API, UI), never assumed.
2. Controlled failures are valid outcomes — assert `status`/`error_kind`, not exceptions.
3. Best-effort writes (telemetry, traces) must never break responses — test the swallow.
4. No live external calls in CI: simulated providers, mock transports, key-gated eval skips.
5. Disposable `arc_test` DB only (`UnsafeTestDatabaseError` guard); each CI shard owns its database.
6. Deterministic providers by default; production-LLM paths are key-gated and skippable.

## Layers and when to use them

- **UNIT:** pure domain rules, validation, parsing, pricing math, prompt construction, state machines. No DB, no HTTP.
- **INTEGRATION:** real PostgreSQL (+pgvector) via `db`/`repositories` fixtures; service stacks wired really. For every repository contract, lifecycle (approval consume races, webhook claim races), and persistence semantics.
- **API:** `TestClient(app)` + `seeded`/`make_token`/`authorization_override`. RBAC matrices, tenant mismatch 403s, cross-tenant ≡ 404, envelope shapes, validation 422s, error mapping (generic 500s).
- **E2E (new, Playwright):** only cross-page journeys that unit/integration/API cannot prove: login → workspace → Ask Arc answer with citations; skill create → execute → result; approval queue → decide → resume → consumed; agent run → trace; member add/remove. Browsers against preview server + `arc_test` backend.
- **SECURITY:** dedicated cross-tenant and boundary suites (not just assertions inside happy-path tests): every tenant-scoped resource × every role.
- **ACCESSIBILITY:** extend existing jsdom a11y scans (SkipLink/headings/controls) with keyboard-flow E2E on dialogs (Execute, Add member, Create tenant).
- **PERFORMANCE:** budgets first (prompt char budget exists; add API p95 + RAG latency budgets), then targeted tests. No framework yet.
- **MANUAL/EXPLORATORY:** OIDC round-trip with real Google, live provider spot-checks, webhook sender interop, upgrade/migration dry-runs.

## Fixtures/factories policy

Reuse `conftest.py` (`seeded`, `make_token`, `authorization_override`, `unique_id`) and `golden_datasets.py` (5-case eval fixtures). New factories only for missing entities (approval rows need service calls, not raw SQL, to preserve lifecycle validity). Mocks allowed only at external boundaries ( provider HTTP, OIDC, clock); never mock the security decision under test.

## CI integration (future QA pipeline)

1. Keep: lint, 4 pytest shards, production-config, schema-bootstrap, frontend job.
2. Add: Playwright job (install browsers once with cache, seed via API, run E2E against compose stack, upload traces on failure).
3. Add: coverage gate (fail under threshold on changed files only — never a global ratchet that blocks unrelated work).
4. Add: nightly live-provider smoke (sandbox key, eval subset) — never on PRs.
5. Keep Docker builds uncached-correct; add npm/pip caching where the Dockerfile allows.

## What NOT to do

No live network in PR CI. No production credentials in fixtures. No asserting on log text as behavior. No sleep-based synchronization in E2E (use web-first assertions). No testing third-party SDK internals.
