# Arc — Current State

Last Updated: 2026-09-24

Current Phase: Foundation — ADR-001 through ADR-014 accepted and implemented (ADR-014 merged via main after this reconciliation's baseline); QA Phases 0–4 complete and merged (PR #320). Product implementation proceeds under approved ADRs.

Git Baseline: `41f32fd` (origin/main, 2026-09-24 — Merge PR #320)

> CI note: GitHub Actions CI (including the Playwright `e2e` job) **runs on PRs but is not a required check**. Branch `main` is guarded by an active ruleset (PR + 1 approval, no force-push, no deletion, no bypass actors) with **no required-status-checks rule**. A red CI job therefore reports but does not block merging.

---

## 1. Architecture Summary

Arc is an enterprise multi-tenant AI platform for IT Services organizations. The architecture follows a layered design:

```text
API Layer (FastAPI: api_router + auth_router, dev-only dev_router)
    ↓
Security Layer (Google OIDC + JWT + server sessions; AuthorizationService RBAC)
    ↓
Service Layer (domain services, no auth)
    ↓
Repository Layer (Protocol-based, tenant-scoped SQL)
    ↓
Database Layer (PostgreSQL + pgvector)
```

Key architectural decisions (ADR-001 through ADR-014) are documented in `docs/architecture/decisions/`. The architecture is framework-agnostic at the domain layer (ADR-001) with explicit boundaries for connectors, webhooks, AI tools, and unified intelligence. Recent decisions cover tenant-scoped membership administration (ADR-009), platform observability attribution (ADR-010), tenant suspension (ADR-011), self-scoped approval reads (ADR-012), external actions through connectors (ADR-013), and local OCR off by default (ADR-014).

---

## 2. Implemented Capabilities

### 2.1 Authentication — IMPLEMENTED

Google OIDC login (`GET /auth/google`, `/auth/callback`, `/auth/workspaces`) with server-side sessions (`sessions` table), plus JWT HS256 bearer authentication. Tokens carry only identity (`sub` claim). No roles, permissions, or tenant context in tokens. Algorithm allowlist enforced (`HS256` only). Issuer and audience validated. Minimum 16-character secret required; missing/short secret prevents authentication entirely (fail closed). Dev-only reference login (`dev_router`, `APP_ENV=development` only) for local/E2E use.

- Source: `src/arc/security/jwt.py`, `src/arc/security/settings.py`, `src/arc/security/google.py`, `src/arc/security/session.py`, `src/arc/api/auth_routes.py`, `src/arc/api/dev_auth.py`
- Dependency: `src/arc/security/dependencies.py` — `get_authenticated_principal`

### 2.2 Authorization / RBAC — IMPLEMENTED

33 permissions across 5 `ApplicationRole` values, enforced centrally by `AuthorizationService`. Fail-closed default: unknown users, unknown roles, and unlisted permissions are always denied. Role assignments are environment-configured (`APPLICATION_ROLE_ASSIGNMENTS` JSON).

| Role | Permissions | Notable |
|------|-------------|---------|
| PLATFORM_ADMINISTRATOR | 33 | Full access including platform-level operations |
| COMPANY_ADMINISTRATOR | 25 | No TENANT_CREATE, TENANT_LIST, TENANT_SUSPEND, USER_CREATE, USER_READ, MEMBERSHIP_CREATE, OBSERVABILITY_PLATFORM_READ |
| OPERATIONS_USER | 13 | Read + execute, no create/delete for tenants/users/skills; no approval read/decide |
| EMPLOYEE | 2 | KNOWLEDGE_READ (Ask Arc / Company Brain read) + AGENT_EXECUTE (workflows via Agent only, no direct skill/tool execution) |
| WEBHOOK_PROCESSOR | 2 | skill:execute + tool:execute (system-only, never assigned to real users) |

- Source: `src/arc/security/authorization.py` (`ROLE_PERMISSIONS`)

### 2.3 Multi-Tenancy — IMPLEMENTED

Every tenant-scoped table has a `tenant_id` column with `ON DELETE CASCADE` foreign key. Every repository query includes a `tenant_id` WHERE clause. The trusted `TenantContext` (derived from database membership verification) is the authoritative tenant boundary. Path-tenant consistency is defensively checked on every tenant-scoped endpoint.

- Tenant isolation: application-level SQL scoping (no PostgreSQL RLS)
- Cross-tenant access: denied at SQL level + application level + API level

### 2.4 Tenant Lifecycle — IMPLEMENTED

`POST /tenants` creates a tenant AND assigns the authenticated creator as OWNER, atomically via `create_tenant_with_owner`. `PUT /tenants/{tenant_id}` updates company configuration fields. Status mutation via PUT is explicitly rejected.

Suspension (ADR-011, Issue #295): `POST /tenants/{tenant_id}/status` sets `active` or `suspended` and requires the platform-only `tenant:suspend` permission (deliberately separate from `tenant:update`, which company administrators hold). Enforcement is fail-closed at the tenant-context boundary: a non-`active` tenant (suspended, unknown, or unreadable status) cannot establish a trusted context, so every tenant-scoped route denies access. Platform routes (listing, record read, observability) still see suspended tenants. Suspension is reversible and lossless; no delete endpoint exists.

- Source: `src/arc/api/controllers.py`, `src/arc/services/domain.py` (`TenantSuspendedError`)
- Atomic creation: `src/arc/services/domain.py`

### 2.5 Membership Model — IMPLEMENTED

**UserRole** (tenant membership): OWNER, MEMBER, VIEWER — stored in `memberships.role`, derived from database, never caller-supplied.

**ApplicationRole** (platform RBAC): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER, EMPLOYEE, WEBHOOK_PROCESSOR — configured via environment, independent of UserRole.

Per ADR-008: These two role systems are completely independent. No automatic mapping. Membership does not grant application permissions. ApplicationRole does not grant tenant access.

Per ADR-009 (Issue #298): a company administrator may administer membership **within their own tenant** via the tenant-scoped `membership:manage` permission (held by COMPANY_ADMINISTRATOR and PLATFORM_ADMINISTRATOR). The endpoints accept either the global `membership:create` or tenant-scoped `membership:manage` in the trusted-context tenant. Two invariants are enforced server-side: removing the last OWNER is refused (`remove_preserving_last_owner`), and self-removal is refused. User creation (`user:create`) stays platform-only.

**Production endpoints:**
- `POST /tenants/{tenant_id}/memberships` — creates membership (PLATFORM_ADMINISTRATOR via `membership:create`, or COMPANY_ADMINISTRATOR via `membership:manage` in own tenant)
- `DELETE /tenants/{tenant_id}/memberships/{user_id}` — removes membership (same authority; last-owner and self-removal refused)

**Dev endpoint** (APP_ENV=development only):
- `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships`

- Source: `src/arc/api/controllers.py`, `src/arc/api/dev_controllers.py`

### 2.6 Knowledge / Company Brain — IMPLEMENTED

Tenant-scoped knowledge document storage with PII sanitization (Microsoft Presidio). Documents have identity via `(tenant_id, source, external_id)` per ADR-003. Re-ingestion of identical content is idempotent; changed content triggers version bump with chunk replacement.

- Schema: `knowledge_documents` (10 data columns, CHECK constraints, partial unique index on external_id)
- Source: `src/arc/services/knowledge.py`
- PII guard: always applied, including on re-ingestion (fail closed)
- Legacy duplicate archival: status-only transition, dry-run required

### 2.7 RAG / Retrieval — IMPLEMENTED

pgvector extension with HNSW cosine index on `knowledge_chunks.embedding vector(1536)`. Semantic search via `RetrievalService.search` and `RetrievalService.approved_search`. Source-type filtering supported.

- Schema: `knowledge_chunks` (embedding, HNSW index)
- Chunking: `src/arc/services/chunking.py` — deterministic, whitespace-aware
- Embeddings: `src/arc/services/embeddings.py` — DeterministicProvider (dev) + OpenAIProvider (production, ADR-007)
- Retrieval: `src/arc/services/retrieval.py` — fail-closed, tenant-scoped at SQL level
- Approved Context: `ApprovedContext` contract with security metadata, the ONLY representation for LLM consumption

### 2.8 Unified Intelligence — PARTIALLY IMPLEMENTED

`UnifiedIntelligenceService` answers queries using only `approved_search` results. The prompt contains only sanitized content + citation references (no tenant/principal IDs, vectors, or authorization state). No approved context → LLM never invoked, answer is `None`.

**What is implemented:**
- LLM abstraction (`LlmProvider` protocol)
- Deterministic local provider (for development/testing)
- Prompt construction from approved context only
- Answer with citations

**What is NOT implemented (deferred):**
- Production LLM provider (OpenRouter per TRD §34)
- Production model selection/routing

- Source: `src/arc/services/intelligence.py`, `src/arc/services/llm.py`

### 2.9 AI Agents — PARTIALLY IMPLEMENTED

`AgentExecutionService` runs bounded workflows with skill selection. `MAX_AGENT_STEPS = 3`. The agent holds no tool registry, no handlers — all actions flow through `SkillExecutionService`.

**What is implemented:**
- Agent execution with skill selection via LLM
- Step limit enforcement
- Structured outcome (succeeded, failed, approval_required, max_steps_reached)
- Skill-based execution (no direct tool access)
- Approval re-execution path (resume after human approval via `/agent/runs/resume`)
- Agent execution trace persistence and observability

**What is NOT implemented (deferred):**
- Production LLM provider for decision-making

- Source: `src/arc/services/agent.py`

### 2.10 AI Tools / Skills — IMPLEMENTED

**AI Tools:** Platform-owned, code-defined catalog: `check_service_health` and `grant_temporary_access` (HIGH risk, `REQUIRE_HUMAN_APPROVAL`), plus the external-action tool `post_channel_message` (Slack, ADR-013). Per-tool authorization enforced fail-closed. Tool execution records stored with audit minimization (secrets redacted, summaries truncated).

**External actions (ADR-013, Issue #304):** `ExternalActionService` is the only route from a tool to the outside world, passing five gates — tenant capability (`external_action`), caller `connector:act` permission (PLATFORM/COMPANY_ADMINISTRATOR, OPERATIONS_USER; never EMPLOYEE or WEBHOOK_PROCESSOR), single-use human approval bound to tenant/tool/version/argument digest, administrator-configured ACTIVE connector destination matched in SQL, and scope-separated `act` credential (no ENV fallback, no read-credential fallback). The write side uses a separate `ProviderActionAdapter` protocol; handlers cannot open their own channels (source-level `httpx`/`socket` guard extended to action handlers).

**Skills:** Tenant-owned skill definitions stored as JSONB. PII sanitization on all textual fields. Execution engine validates proposals against `allowed_tools`, resolves through platform registry, enforces preconditions, and manages approval-required skills. Complete CRUD: create, read, list, update (`PUT /skills/{skill_id}`), delete. Each skill carries an optional `risk` field.

- Tool source: `src/arc/services/tools.py`
- External-action source: `src/arc/services/external_actions.py`
- Skill source: `src/arc/services/skills.py`, `src/arc/services/skill_execution.py`
- Schema: `skills` (JSONB definition), `tool_execution_records` (audit)

### 2.11 Human Approval / Intervention — IMPLEMENTED

Approval gate for high-risk tool executions. Lifecycle: pending → approved | rejected | expired (terminal); approved → consumed exactly once. Self-approval prevented. Lazy expiry at read time. Race-safe unique partial index on pending bindings.

Full end-to-end approval consumption cycle:
1. Tool execution triggers `REQUIRE_HUMAN_APPROVAL` policy → pending approval created → `APPROVAL_REQUIRED` result returned with `approval_id`
2. Human approves via `/approvals/{id}/decisions`
3. Client resumes via `/skills/{id}/resume` or `/agent/runs/resume` with `approval_id`
4. Approval is atomically consumed → execution resumes from the gated step

Background expiry sweep: stale pending approvals past their 24-hour TTL are automatically expired every 5 minutes via `ApprovalSweepRunner`. This is persistence-level maintenance only — it does NOT execute tools, grant/consume approvals, or modify authorization state.

- Source: `src/arc/services/approvals.py`, `src/arc/services/approval_sweep.py`
- Schema: `approval_requests` (14 columns, CHECK constraints, partial unique index)
- Permissions: APPROVAL_READ (tenant-wide), APPROVAL_DECIDE; plus self-scoped read (ADR-012, Issue #318)

**Self-scoped approval reads (ADR-012):** a caller with a trusted tenant context but without `approval:read` may read only rows where `requester_user_id` is their own — narrowed **in SQL** in both list (`SELECT` + `COUNT`) and single-row read (out-of-scope ID returns 404, not 403). `approval:decide` is untouched: a self-scoped caller attempting a decision still receives 403 (four-eyes preserved). This makes the approval resume path reachable by the requester roles (e.g., OPERATIONS_USER) that actually create approval requests.

### 2.12 Connectors — IMPLEMENTED

GitHub, Slack, and Linear provider integrations with SSRF protection (approved host allowlist, manual URL parsing, no redirects). Credentials are environment-injected, never tenant-supplied, persisted, or returned. Connector sync content passes through PII guard before ingestion.

Read and act credentials are separate: `connector_credentials` carries a `scope` column (`read` default; uniqueness on tenant/provider/scope). Full credential lifecycle (`POST`/`GET`/`PUT`/`DELETE …/connectors/credentials/{provider}` with `?scope=read|act`) requires `connector:manage_credentials`; taking an external action requires `connector:act` (ADR-013).

- Providers: `src/arc/services/connector_providers/` (GitHub, Slack, Linear, Fake, base, registry, targets)
- Sync: `src/arc/services/connector_sync.py`
- Schema: `connector_configs`, `connector_sync_records`
- Permissions: CONNECTOR_CREATE, CONNECTOR_READ, CONNECTOR_SYNC

### 2.13 Webhooks — IMPLEMENTED

Inbound webhook ingestion with HMAC-SHA256 authentication. Constant-time signature comparison. Timestamp-window replay resistance (±300s). Streaming body cap (64KB) before authentication. Idempotent duplicate handling. Raw payloads never persisted.

Downstream processing pipeline: received events can be routed through a Skill execution pipeline. Environment-configured endpoints specify a Skill to trigger on each event. Processing is atomic (at most one processor claims an event), flows through the existing Skill/Tool execution boundary, and transitions the event to processed/failed with safe error categories. The system principal `system:webhook` has minimal permissions (`skill:execute` + `tool:execute` only).

- Ingestion: `src/arc/services/webhook_ingestion.py`
- Config: `src/arc/services/webhook_config.py`
- Pipeline: `src/arc/services/webhook_pipeline.py`
- Schema: `webhook_events` (metadata only, UNIQUE on tenant+event_id, extended lifecycle states)
- Permissions: WEBHOOK_READ, WEBHOOK_PROCESS

### 2.14 Observability / Telemetry — IMPLEMENTED

Best-effort HTTP telemetry with correlation IDs. Success-gated path-param tenant attribution. Structured logging with stdlib. Usage summary aggregation from authoritative subsystem tables. Component health probes.

Platform observability attribution (ADR-010, Issue #297): `GET /platform/observability/tenants` returns per-tenant request count, error count, and error rate for the window (requires `observability:platform_read`, PLATFORM_ADMINISTRATOR only). Attribution covers counts only — no paths, payloads, prompts, documents, or user identifiers. Unattributed (null-tenant) traffic appears as its own bucket. The existing `GET /platform/observability/summary` is unchanged and remains strictly tenant-agnostic.

Agent execution trace: every bounded Agent run produces a persisted execution trace record (goal, steps, skill selections, outcomes). Traces are queryable per-tenant. Human escalation counts are aggregated from approval request decisions.

- Source: `src/arc/services/observability.py`, `src/arc/repositories/observability.py`
- Schema: `api_request_records` (metadata only, nullable tenant_id), `agent_run_records` (agent execution traces)
- Permissions: OBSERVABILITY_READ, OBSERVABILITY_PLATFORM_READ

### 2.15 Platform Administration — IMPLEMENTED

Platform-wide tenant administration for PLATFORM_ADMINISTRATOR. `GET /platform/tenants` lists all tenants across the platform. Frontend platform console routes are UX-guarded via `RequirePlatformAdmin`.

- Source: `src/arc/api/controllers.py` (`list_platform_tenants`)
- Frontend: `frontend/src/components/platform/PlatformTenantsPage.jsx`
- Route guard: `frontend/src/auth/RequirePlatformAdmin.jsx`

### 2.16 Frontend — IMPLEMENTED

React + React Query + React Router. Role-aware navigation with 4 persona levels. JWT/session authentication with session expiry handling. Tenant workspace, platform console, auth, and redirect routes (63 `<Route>` elements in `App.jsx`, including legacy/removed-shell redirects). Loading/error/empty states on all pages. Demo mode handling.

Browser E2E (QA Phases 1–4, PR #320): Playwright, Chromium-only, 7 spec files covering login smoke, Ask Arc, skill execution, tenant isolation, RBAC matrix, approval lifecycle, and agent runs — enforced by the CI `e2e` job (runs on PRs; advisory, not a required check).

- Source: `frontend/src/`
- Routing: `frontend/src/App.jsx`
- Navigation: `frontend/src/components/shell/navigation.js`
- Capabilities: `frontend/src/auth/capabilities.js`

---

## 3. Database / Schema State

20 tables in `src/arc/db/schema.sql`:

| Table | Tenant-Scoped | Key Constraints |
|-------|--------------|-----------------|
| `tenants` | N/A (root) | PK id, company fields, `status` (active/suspended, ADR-011) |
| `users` | N/A (root) | PK id, UNIQUE email |
| `memberships` | Yes | FK users+tenants CASCADE, UNIQUE(user, tenant) |
| `connector_configs` | Yes | FK tenants CASCADE, UNIQUE(tenant, provider, name) |
| `knowledge_documents` | Yes | FK tenants CASCADE, CHECK version/status, partial unique index on external_id |
| `skills` | Yes | FK tenants CASCADE, JSONB definition, UNIQUE(tenant, name, version) |
| `tool_execution_records` | Yes | FK tenants CASCADE, CHECK status/auth_outcome/risk_level |
| `knowledge_chunks` | Yes | FK documents+tenants CASCADE, vector(1536), HNSW index |
| `connector_sync_records` | Yes | FK tenants+connectors CASCADE, CHECK status |
| `connector_credentials` | Yes | FK tenants CASCADE, `scope` (read/act, ADR-013), UNIQUE(tenant, provider, scope) |
| `connector_credential_audit` | Yes | FK tenants+credentials CASCADE, scoped audit trail |
| `webhook_events` | Yes | FK tenants CASCADE, UNIQUE(tenant, event_id), extended lifecycle states |
| `api_request_records` | Nullable | FK tenants CASCADE, CHECK status_code/duration, indexed tenant_id (ADR-010 attribution) |
| `approval_requests` | Yes | FK tenants CASCADE, CHECK status, CHECK digest regex, partial unique index on pending |
| `agent_run_records` | Yes | FK tenants CASCADE, CHECK status, JSONB steps |
| `skill_execution_records` | Yes | FK skills (+agent_run_id unenforced) |
| `sessions` | N/A (user) | Server-side OIDC/JWT session state |
| `llm_usage_records` | Nullable | Tenant-attributed LLM usage telemetry |
| `platform_capabilities` | N/A (global) | Platform capability flags |
| `tenant_capabilities` | Yes | Composite PK, dual CASCADE (per-tenant capability gates, e.g. `external_action`) |

Schema uses idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` for safe re-runs. No PostgreSQL Row-Level Security (RLS).

---

## 4. API Surface

65 production endpoints + 4 dev-only endpoints, by route-decorator census at the baseline commit (60 `@api_router` decorators in `controllers.py` — exactly 60 unique method+path combinations, including the HMAC webhook-ingest route — plus 5 `auth_router` routes in `auth_routes.py`; plus 1 `dev_router` route in `dev_controllers.py` and 3 `dev_auth_router` routes in `dev_auth.py`, all under `/internal/dev` and mounted only when `APP_ENV=development`).

| Category | Endpoints | Key Permissions |
|----------|-----------|-----------------|
| Health | GET /health | None (public) |
| Auth | GET /auth/google, /auth/callback, /auth/workspaces; POST /auth/logout, /auth/logout-all; GET /auth/me | OIDC flow / session / authenticated |
| Tenants | POST, GET, PUT /tenants; POST /tenants/{id}/status | tenant:create, tenant:read, tenant:update, tenant:suspend (ADR-011) |
| Platform Tenants | GET /platform/tenants | tenant:list (PLATFORM_ADMINISTRATOR only) |
| Users | POST /users, GET /platform/users, GET /tenants/{id}/users | user:create, user:read, tenant:read |
| Memberships | POST, DELETE /tenants/{id}/memberships | membership:create (global) or membership:manage (own tenant, ADR-009) |
| User Tenants | GET /users/{id}/tenants | Self-scoped |
| Knowledge | POST, GET, GET by id, PUT, DELETE /tenants/{id}/knowledge; POST /tenants/{id}/knowledge/upload (text, Markdown, PDF, Word; images and scanned PDFs when OCR is configured per ADR-014) | knowledge:create/read/update/delete |
| Search | GET /tenants/{id}/knowledge/search | knowledge:read |
| Intelligence | POST /tenants/{id}/intelligence/query | knowledge:read |
| Skills | POST, GET, GET by id, PUT, DELETE, POST execute, POST resume /tenants/{id}/skills | skill:create/read/update/delete/execute |
| Agent | POST /agent/runs, POST /agent/runs/resume | agent:execute |
| Tools | GET, POST execute /tenants/{id}/tools | tool:read, tool:execute |
| Connectors | GET, POST, POST sync /tenants/{id}/connectors; GET/POST/PUT/DELETE credentials (`?scope=read\|act`); GET credentials audit | connector:create/read/sync, connector:manage_credentials, connector:act (ADR-013 external actions) |
| Webhooks | POST /webhooks/{id}/events (HMAC ingest), GET /tenants/{id}/webhooks/events, POST /tenants/{id}/webhooks/process | HMAC auth, webhook:read, webhook:process |
| Observability | GET /tenants/{id}/observability/usage-summary, llm-usage, llm-usage/records, agent-runs, agent-runs/{id}; GET /platform/observability/summary, /platform/observability/tenants (ADR-010); GET /observability/health | observability:read, observability:platform_read |
| Approvals | GET, GET by id, POST decide /tenants/{id}/approvals | approval:read (tenant-wide) or self-scoped to the caller's own requests per ADR-012; approval:decide |
| Capabilities | GET /platform/capabilities(+/{id}), PUT /platform/capabilities/{id}; tenant capability reads/updates | capability:manage; external_action tenant gate (ADR-013) |

**API contract note:** Request bodies use `Dict[str, Any]` rather than Pydantic models. Domain models validate via `__post_init__`. This is technical debt — it weakens automatic validation and OpenAPI documentation.

---

## 5. Testing State

111 test files (`test_*.py`) in `tests/` plus `conftest.py` and `tests/evaluation/` (golden/LLM-behavior suites). All backend tests run against real PostgreSQL (not mocked). Schema is dropped and recreated per test session.

- CI: `.github/workflows/ci.yml` (sole workflow) — GitHub Actions on ubuntu-latest: `lint` (ruff), `test` (4 `pytest-split` shards, per-shard throwaway `arc_test` pgvector), `production-config` (`APP_ENV=production` boundary), `schema-bootstrap` (fresh-DB `ensure_schema`), `frontend` (`npm ci` → oxlint → vitest → build, Node 22.19), `e2e` (Playwright Chromium suite via compose stack). CI runs on PRs but is **not a required check** (see header note).
- Test infrastructure: `tests/conftest.py` — env pinning, TestClient lifecycle, DB fixtures, authorization overrides

**QA program Phases 0–4 (merged via PR #320):** Playwright foundation (auth setup, API/CSRF helpers, browser-health watcher, login/Ask Arc/skill-execution smoke); tenant-isolation matrix (`tests/test_tenant_isolation_matrix.py`, 16 tests over 9 resource families, plus 2 browser isolation specs); critical-workflow E2E (approval lifecycle with four-eyes/consume/replay/reject, agent run → trace, RBAC matrix — 7 spec files, Chromium-only); CI `e2e` quality gate; 3 Windows-only Vitest scan-test fixes (path-separator normalization, no assertions weakened).

**Last session-verified baselines (from the merged QA sessions, not freshly executed in this documentation update):** 418 Vitest files-green (43 files), 14/14 Playwright, 16/16 isolation matrix. Backend totals were last counted before the ADR-009–013 merges; do not quote a total test count as current without a fresh collection run.

**Test coverage observations:**
- Exhaustive permission matrix test (5 roles × 33 permissions, parametrized)
- API surface tests verifying production vs development OpenAPI
- 12+ tenant isolation tests (cross-tenant, missing membership, self-scoping) plus the 16-test isolation matrix
- Regression tests for Issues #58, #60, #70, #76
- Untested by E2E (Phase 5 candidates): ADR-009 membership scoping, ADR-010 attribution, ADR-011 suspension lifecycle, ADR-012 self-scoped reads, ADR-013 external-action gating
- No frontend component/routing tests beyond rendering + scans
- No concurrent test isolation (manual cleanup, unique IDs mitigate)

---

## 6. Security Posture

| Control | Status | Evidence |
|---------|--------|----------|
| Google OIDC + server sessions | Code/state login, callback, workspaces; logout/logout-all | `auth_routes.py`, `security/google.py`, `security/session.py`, `sessions` table |
| JWT algorithm allowlist | HS256 only | `jwt.py` — `ALLOWED_ALGORITHMS = ["HS256"]` |
| JWT carries identity only | No roles/permissions/tenant in tokens | `jwt.py` docstring |
| RBAC fail-closed | Unknown users/roles/permissions denied; 33-permission central matrix | `authorization.py` (`AuthorizationService`, `ROLE_PERMISSIONS`) |
| Tenant isolation at SQL level | Every query has tenant_id WHERE | All repositories verified |
| Suspended tenants denied | Non-`active` status cannot establish trusted context (ADR-011) | `services/domain.py` (`TenantSuspendedError`) |
| Path-tenant consistency check | Defensive 403 on mismatch | `controllers.py` |
| Self-scoped approval reads | SQL narrowing; 404 out-of-scope; decide still 403 (ADR-012) | `repositories/approvals.py`, `controllers.py` |
| Read/act credential separation | Distinct scopes; no ENV or read fallback for act (ADR-013) | `services/external_actions.py`, credential endpoints |
| PII guard on all content paths | Always applied, including re-ingestion | `knowledge.py` |
| Webhook HMAC auth | Constant-time, timestamp window, body cap | `webhook_ingestion.py` |
| SSRF protection on connectors | Approved host allowlist, no redirects | `connector_providers/targets.py` |
| Dev endpoint gating | APP_ENV=development at mount time | `main.py` |
| Self-scoped identity | user_id must match JWT sub | `controllers.py` |
| Secrets never in responses | Credentials masked in repr | `base.py`, `webhook_config.py` |
| Audit minimization | Sensitive keys redacted, summaries truncated | `tools.py:_redact` |
| Telemetry is metadata-only | No bodies, prompts, answers, tokens, secrets | `middleware.py`, `schema.sql` comments |
| Fail-closed defaults | Empty APPLICATION_ROLE_ASSIGNMENTS denies all | `settings.py` |
| Approval lifecycle safety | Atomic conditional UPDATEs, single-use consumption, background sweep | `approvals.py`, `approval_sweep.py` |
| Platform attribution counts-only | Request/error counts + rate per tenant; no content; summary unchanged (ADR-010) | `controllers.py` (`/platform/observability/tenants`), `services/observability.py` |

**No PostgreSQL RLS.** Tenant isolation relies entirely on application-layer SQL scoping. This is a defense-in-depth gap, not a vulnerability — the application layer consistently enforces isolation.

---

## 7. Known Technical Debt

| Item | Priority | Description |
|------|----------|-------------|
| Dict[str, Any] API bodies | P2 | Endpoints accept `Dict[str, Any]` instead of Pydantic models — weakens validation and OpenAPI docs |
| Naive datetime.now() | P2 | Residual `datetime.now()` uses remain in knowledge/connectors/sync paths — inconsistent with `datetime.now(timezone.utc)` used elsewhere |
| Generic exception re-raise | P2 | `raise Exception(f"...: {e}")` in knowledge.py, connectors.py, skills.py loses original exception type |
| No RLS | P3 | No PostgreSQL Row-Level Security — defense-in-depth gap |
| print() for init logging | P3 | `app.py` — should use logger |
| Deprecated startup event | P3 | `@app.on_event("startup")` — functional, migrate to lifespan later |
| PlatformTenantsPage scope | P3 | Shows user's own tenants, not all platform tenants |
| TenantUsersPage permission UI | P3 | Add/Remove buttons only disabled in demo mode, not by permission |
| `error_kind` pinning on replay/reject | P3 | Approval-lifecycle E2E asserts `status` only; pin `error_kind` (Phase 5 candidate) |
| `_two_tenants` unused param | P3 | Isolation-matrix helper takes unused `client` (Phase 5 candidate) |
| `pytest-results.txt` un-ignored | P3 | Test output file not covered by `.gitignore` |
| CI gates advisory-only | P2 | No required-status-checks rule: red CI reports but does not block merging (needs admin action) |

---

## 8. Known Limitations

- Production LLM provider not available (deterministic only)
- No pagination, search, or filtering on list endpoints
- No frontend component/routing test coverage
- No migration tests (schema evolution)
- No performance/load tests; no coverage, type-check, or dependency-scan gates
- No extra-browser E2E (Chromium only); no keyboard-flow a11y E2E
- No live-provider E2E: OIDC round-trip with real Google, live webhook-sender interop, and live connector actions are manual-only by design
- CI jobs (including E2E) are advisory — no required-check enforcement on `main`
- macOS cross-platform verification pending (Joe)
- ApplicationRole provisioning remains environment-configured (no runtime API)
- Last-owner removal prevention implemented (ADR-009); delete race-condition hardening not implemented
- Membership audit trail not implemented (existing API request logging sufficient)

---

## 9. Merged PRs / Issues (verified against git history)

| PR | Description | Status |
|----|-------------|--------|
| #56 | Final architecture/product specification | MERGED |
| #68 | Tenant creation input focus fix | MERGED |
| #72 | Production membership provisioning (Issue #59) | MERGED |
| #74 | Tenant onboarding owner auto-assignment (Issue #58) | MERGED |
| #78 | RBAC role independence clarification (Issue #60, ADR-008) | MERGED |
| #79 | Platform user listing (Issue #61) | MERGED |
| #81 | Skill duplicate conflict (Issue #62) | MERGED |
| #82 | Skill execution control (Issue #63) | MERGED |
| #83 | Approval column mismatch fix (Issue #64) | MERGED |
| #84 | Usage field mapping fix (Issue #65) | MERGED |
| #85 | User form focus fix (Issue #69) | MERGED |
| #86 | tldextract cache fix (Issue #73) | MERGED |
| #87 | Employee Ask Arc access fix (Issue #76) | MERGED |
| #88 | Employee Ask Arc access fix (Issue #66) | MERGED |
| #89 | Observability page fix (Issue #71) | MERGED |
| #90 | Tenant company configuration (Issue #70) | MERGED |
| #91 | Connector target field (Issue #75) | MERGED |
| #92 | Retrieval docstring fix (Issue #67) | MERGED |
| #93 | Knowledge API external_id wiring | MERGED |
| #97 | Platform route guard | MERGED |
| #105 | Platform admin tenants (Issue #94) | MERGED |
| #106 | Skill management — PUT endpoint + risk field (Issues #98-99) | MERGED |
| #107 | Approval consumption path / Agent-Skill approval re-execution (Issue #104) | MERGED |
| #108 | Observability agent execution trace | MERGED |
| #109 | Webhook downstream processing pipeline (Issue #102) | MERGED |
| #110 | Background approval expiry sweep (Issue #100) | MERGED |
| #315 | Tenant-scoped membership administration — `membership:manage` for company admins, last-owner/self-removal guards (Issue #298, ADR-009) | MERGED |
| #316 | Platform observability tenant attribution — per-tenant request/error counts endpoint (Issue #297, ADR-010) | MERGED |
| #317 | Tenant suspension and restore — `tenant:suspend`, fail-closed context enforcement (Issue #295, ADR-011) | MERGED |
| #319 | Self-scoped approval reads — requesters read own rows in SQL (Issue #318, ADR-012) | MERGED |
| #320 | QA Phases 0–4 — Playwright E2E suite + CI `e2e` quality gate + Windows scan-test fixes | MERGED |
| #321 | External actions through connectors — `post_channel_message` via five gates, `connector:act` (Issue #304, ADR-013) | MERGED |

---

## 10. Architecture Decision Records

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | Arc Unified Intelligence and Secure Application Architecture | Accepted |
| ADR-002 | Connector Provider Selection | Accepted |
| ADR-003 | Company Brain Document Identity and Re-ingestion Semantics | Accepted |
| ADR-004 | Unified Intelligence Tool-Calling Execution Contract | Accepted |
| ADR-005 | Human Intervention Approval Gate | Proposed |
| ADR-006 | Bounded Agent Skill Orchestration | Draft / Proposed |
| ADR-007 | Production Embedding Provider and Vector Representation | Proposed |
| ADR-008 | Tenant Membership Roles and Application RBAC Roles — Independent Role Systems | Accepted |
| ADR-009 | Tenant-Scoped Membership Administration (`membership:manage`, last-owner/self-removal guards) | Accepted |
| ADR-010 | Per-Tenant Attribution in Platform Observability (counts-only endpoint; summary unchanged) | Accepted |
| ADR-011 | Tenant Lifecycle — Suspension, Not Deletion (`tenant:suspend`, fail-closed context enforcement) | Accepted |
| ADR-012 | Self-Scoped Approval Reads (own rows in SQL; decide untouched) | Accepted |
| ADR-013 | External Actions Through the Connector Architecture (five gates, `connector:act`, scoped act credentials) | Accepted |
| ADR-014 | Optical Character Recognition — Local Engine, Off By Default (Issue #299; scanned-document/image text extraction for knowledge upload) | Accepted |

---

## 11. Next Recommended Development Priorities

Ordered by dependency and risk:

1. **Phase 5 QA (ADR-009–013 E2E)** — Extend the isolation-matrix + workflow proof standard to membership scoping, suspension lifecycle, self-scoped approval reads, observability attribution, and external-action gating; plus `error_kind` pinning and `_two_tenants` cleanup. Behaviors verified FROZEN_FOR_QA at `41f32fd`.
2. **Enforce CI as required checks** — Add a required-status-checks rule to the `main` ruleset (admin action); until then all CI jobs are advisory.
3. **Migrate API endpoints to Pydantic models** — Replace `Dict[str, Any]` with typed request/response models for validation and OpenAPI documentation.
4. **Standardize datetime handling** — Replace residual `datetime.now()` with `datetime.now(timezone.utc)` for consistency.
5. **Fix generic exception re-raise** — Preserve exception types in knowledge.py, connectors.py, skills.py.
6. **Replace print() with logger** — Use structured logging for initialization.
7. **Migrate to lifespan context manager** — Replace deprecated `@app.on_event("startup")`.
8. **Add frontend component tests** — Critical user flows (membership management, tenant creation, skill execution) need regression protection.
9. **Production LLM provider** — Platform is architecturally ready but can only use deterministic local LLM.
10. **Consider PostgreSQL RLS** — Defense-in-depth for tenant isolation.
11. **Foundation completion review** — Verify all three developers can independently clone, configure, start, test, lint, and use the AI development workflow.

---

## 12. DO NOT TOUCH

These areas are correct and should not be unnecessarily refactored:

- Tenant isolation pattern (trusted context + path check + SQL scoping)
- Fail-closed defaults in authorization
- PII guard integration (always applied)
- JWT minimal token design (identity only)
- HMAC webhook authentication
- SSRF allowlist for connectors
- Atomic tenant+membership creation
- Approval gate lifecycle management
- Permission matrix (exhaustively tested)
- Approved Context contract (the ONLY LLM consumption boundary)
- Suspension fail-closed enforcement at the tenant-context boundary (ADR-011)
- Self-scoped approval reads narrowed in SQL (ADR-012)
- Read/act credential separation with no fallback (ADR-013)
