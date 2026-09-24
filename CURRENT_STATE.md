# Arc — Current State

Last Updated: 2026-09-07

Current Phase: Foundation Phase — All foundation modules merged; product implementation pending Foundation acceptance.

Git Baseline: `63b527c` (origin/main, 2026-09-07)

---

## 1. Architecture Summary

Arc is an enterprise multi-tenant AI platform for IT Services organizations. The architecture follows a layered design:

```text
API Layer (FastAPI)
    ↓
Security Layer (JWT + RBAC)
    ↓
Service Layer (domain services, no auth)
    ↓
Repository Layer (Protocol-based, tenant-scoped SQL)
    ↓
Database Layer (PostgreSQL + pgvector)
```

Key architectural decisions (ADR-001 through ADR-008) are documented in `docs/architecture/decisions/`. The architecture is framework-agnostic at the domain layer (ADR-001) with explicit boundaries for connectors, webhooks, AI tools, and unified intelligence.

---

## 2. Implemented Capabilities

### 2.1 Authentication — IMPLEMENTED

JWT HS256 bearer authentication. Tokens carry only identity (`sub` claim). No roles, permissions, or tenant context in tokens. Algorithm allowlist enforced (`HS256` only). Issuer and audience validated. Minimum 16-character secret required; missing/short secret prevents authentication entirely (fail closed).

- Source: `src/arc/security/jwt.py`, `src/arc/security/settings.py`
- Dependency: `src/arc/security/dependencies.py` — `get_authenticated_principal`

### 2.2 Authorization / RBAC — IMPLEMENTED

26 permissions across 5 `ApplicationRole` values. Fail-closed default: unknown users, unknown roles, and unlisted permissions are always denied. Role assignments are environment-configured (`APPLICATION_ROLE_ASSIGNMENTS` JSON).

| Role | Permissions | Notable |
|------|-------------|---------|
| PLATFORM_ADMINISTRATOR | 26 | Full access including platform-level operations |
| COMPANY_ADMINISTRATOR | 20 | No TENANT_CREATE, TENANT_LIST, USER_CREATE, USER_READ, MEMBERSHIP_CREATE, OBSERVABILITY_PLATFORM_READ |
| OPERATIONS_USER | 12 | Read + execute, no create/delete for tenants/users/skills |
| EMPLOYEE | 1 | KNOWLEDGE_READ only (Ask Arc / Company Brain read) |
| WEBHOOK_PROCESSOR | 2 | skill:execute + tool:execute (system-only, never assigned to real users) |

- Source: `src/arc/security/authorization.py`

### 2.3 Multi-Tenancy — IMPLEMENTED

Every tenant-scoped table has a `tenant_id` column with `ON DELETE CASCADE` foreign key. Every repository query includes a `tenant_id` WHERE clause. The trusted `TenantContext` (derived from database membership verification) is the authoritative tenant boundary. Path-tenant consistency is defensively checked on every tenant-scoped endpoint.

- Tenant isolation: application-level SQL scoping (no PostgreSQL RLS)
- Cross-tenant access: denied at SQL level + application level + API level

### 2.4 Tenant Lifecycle — IMPLEMENTED

`POST /tenants` creates a tenant AND assigns the authenticated creator as OWNER, atomically via `create_tenant_with_owner`. `PUT /tenants/{tenant_id}` updates company configuration fields. Status mutation via PUT is explicitly rejected.

- Source: `src/arc/api/controllers.py`
- Atomic creation: `src/arc/services/domain.py`

### 2.5 Membership Model — IMPLEMENTED

**UserRole** (tenant membership): OWNER, MEMBER, VIEWER — stored in `memberships.role`, derived from database, never caller-supplied.

**ApplicationRole** (platform RBAC): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER, EMPLOYEE, WEBHOOK_PROCESSOR — configured via environment, independent of UserRole.

Per ADR-008: These two role systems are completely independent. No automatic mapping. Membership does not grant application permissions. ApplicationRole does not grant tenant access.

**Production endpoints:**
- `POST /tenants/{tenant_id}/memberships` — creates membership (PLATFORM_ADMINISTRATOR only)
- `DELETE /tenants/{tenant_id}/memberships/{user_id}` — removes membership (PLATFORM_ADMINISTRATOR only)

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

**AI Tools:** Platform-owned, code-defined catalog. Currently one tool: `check_service_health`. Per-tool authorization enforced fail-closed. Tool execution records stored with audit minimization (secrets redacted, summaries truncated).

**Skills:** Tenant-owned skill definitions stored as JSONB. PII sanitization on all textual fields. Execution engine validates proposals against `allowed_tools`, resolves through platform registry, enforces preconditions, and manages approval-required skills. Complete CRUD: create, read, list, update (`PUT /skills/{skill_id}`), delete. Each skill carries an optional `risk` field.

- Tool source: `src/arc/services/tools.py`
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
- Permissions: APPROVAL_READ, APPROVAL_DECIDE

### 2.12 Connectors — IMPLEMENTED

GitHub, Slack, and Linear provider integrations with SSRF protection (approved host allowlist, manual URL parsing, no redirects). Credentials are environment-injected, never tenant-supplied, persisted, or returned. Connector sync content passes through PII guard before ingestion.

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

React + React Query + React Router. Role-aware navigation with 4 persona levels. JWT authentication with session expiry handling. Tenant workspace (22 routes) and platform console (8 routes). Loading/error/empty states on all pages. Demo mode handling.

- Source: `frontend/src/`
- Routing: `frontend/src/App.jsx`
- Navigation: `frontend/src/components/shell/navigation.js`
- Capabilities: `frontend/src/auth/capabilities.js`

---

## 3. Database / Schema State

13 tables in `src/arc/db/schema.sql`:

| Table | Tenant-Scoped | Key Constraints |
|-------|--------------|-----------------|
| `tenants` | N/A (root) | PK id, company fields |
| `users` | N/A (root) | PK id, UNIQUE email |
| `memberships` | Yes | FK users+tenants CASCADE, UNIQUE(user, tenant) |
| `connector_configs` | Yes | FK tenants CASCADE, UNIQUE(tenant, provider, name) |
| `knowledge_documents` | Yes | FK tenants CASCADE, CHECK version/status, partial unique index on external_id |
| `skills` | Yes | FK tenants CASCADE, JSONB definition, UNIQUE(tenant, name, version) |
| `tool_execution_records` | Yes | FK tenants CASCADE, CHECK status/auth_outcome/risk_level |
| `knowledge_chunks` | Yes | FK documents+tenants CASCADE, vector(1536), HNSW index |
| `connector_sync_records` | Yes | FK tenants+connectors CASCADE, CHECK status |
| `webhook_events` | Yes | FK tenants CASCADE, UNIQUE(tenant, event_id), extended lifecycle states |
| `api_request_records` | Nullable | FK tenants CASCADE, CHECK status_code/duration |
| `approval_requests` | Yes | FK tenants CASCADE, CHECK status, CHECK digest regex, partial unique index on pending |
| `agent_run_records` | Yes | FK tenants CASCADE, CHECK status, JSONB steps |

Schema uses idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` for safe re-runs. No PostgreSQL Row-Level Security (RLS).

---

## 4. API Surface

42 production endpoints on `api_router`, 1 dev endpoint on `dev_router` (APP_ENV=development only).

| Category | Endpoints | Key Permissions |
|----------|-----------|-----------------|
| Health | GET /health | None (public) |
| Auth | GET /auth/me | Authenticated |
| Tenants | POST, GET, PUT /tenants | tenant:create, tenant:read, tenant:update |
| Platform Tenants | GET /platform/tenants | tenant:list (PLATFORM_ADMINISTRATOR only) |
| Users | POST /users, GET /platform/users, GET /tenants/{id}/users | user:create, user:read, tenant:read |
| Memberships | POST, DELETE /tenants/{id}/memberships | membership:create |
| User Tenants | GET /users/{id}/tenants | Self-scoped |
| Knowledge | POST, GET, GET list /tenants/{id}/knowledge | knowledge:create, knowledge:read |
| Search | GET /tenants/{id}/knowledge/search | knowledge:read |
| Intelligence | POST /tenants/{id}/intelligence/query | knowledge:read |
| Skills | POST, GET, GET by id, PUT, DELETE, POST execute /tenants/{id}/skills | skill:create/read/update/delete/execute |
| Skill Resume | POST /skills/{skill_id}/resume | skill:execute |
| Agent | POST /agent/runs | agent:execute |
| Agent Resume | POST /agent/runs/resume | agent:execute |
| Tools | GET, POST execute /tenants/{id}/tools | tool:read, tool:execute |
| Connectors | GET, POST, POST sync /tenants/{id}/connectors | connector:create/read/sync |
| Webhooks | POST /webhooks/{id}/events, GET /tenants/{id}/webhooks/events, POST /tenants/{id}/webhooks/process | HMAC auth, webhook:read, webhook:process |
| Observability | GET /tenants/{id}/observability/usage-summary, GET /platform/observability/summary, GET /observability/health, GET /tenants/{id}/observability/agent-runs | observability:read, observability:platform_read |
| Approvals | GET, GET by id, POST decide /tenants/{id}/approvals | approval:read (tenant-wide) or self-scoped to the caller's own requests per ADR-012; approval:decide |

**API contract note:** Request bodies use `Dict[str, Any]` rather than Pydantic models. Domain models validate via `__post_init__`. This is technical debt — it weakens automatic validation and OpenAPI documentation.

---

## 5. Testing State

71 test files (`test_*.py`) in `tests/` plus `conftest.py`. All backend tests run against real PostgreSQL (not mocked). Schema is dropped and recreated per test session.

- CI: `.github/workflows/ci.yml` — GitHub Actions on ubuntu-latest: `docker compose build arc`, `ruff check`, `ruff format --check`, `python -m pytest -q`
- Test infrastructure: `tests/conftest.py` — env pinning, TestClient lifecycle, DB fixtures, authorization overrides

**Last verified test count:** 1299 tests collected (Docker + real PostgreSQL), verified against `origin/main` at `63b527c`.

**Test coverage observations:**
- Exhaustive permission matrix test (4 roles × 26 permissions, parametrized)
- 18 API surface tests verifying production vs development OpenAPI
- 12 tenant isolation tests (cross-tenant, missing membership, self-scoping)
- Regression tests for Issues #58, #60, #70, #76
- No frontend component/routing tests beyond basic rendering
- No concurrent test isolation (manual cleanup, unique IDs mitigate)

---

## 6. Security Posture

| Control | Status | Evidence |
|---------|--------|----------|
| JWT algorithm allowlist | HS256 only | `jwt.py` — `ALLOWED_ALGORITHMS = ["HS256"]` |
| JWT carries identity only | No roles/permissions/tenant in tokens | `jwt.py` docstring |
| RBAC fail-closed | Unknown users/roles/permissions denied | `authorization.py` |
| Tenant isolation at SQL level | Every query has tenant_id WHERE | All repositories verified |
| Path-tenant consistency check | Defensive 403 on mismatch | `controllers.py` |
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

**No PostgreSQL RLS.** Tenant isolation relies entirely on application-layer SQL scoping. This is a defense-in-depth gap, not a vulnerability — the application layer consistently enforces isolation.

---

## 7. Known Technical Debt

| Item | Priority | Description |
|------|----------|-------------|
| Dict[str, Any] API bodies | P2 | Endpoints accept `Dict[str, Any]` instead of Pydantic models — weakens validation and OpenAPI docs |
| Naive datetime.now() | P2 | Used in knowledge.py, connectors.py, connector_sync.py — inconsistent with `datetime.now(timezone.utc)` used elsewhere |
| Generic exception re-raise | P2 | `raise Exception(f"...: {e}")` in knowledge.py, connectors.py, skills.py loses original exception type |
| No RLS | P3 | No PostgreSQL Row-Level Security — defense-in-depth gap |
| print() for init logging | P3 | `app.py` — should use logger |
| Deprecated startup event | P3 | `@app.on_event("startup")` — functional, migrate to lifespan later |
| PlatformTenantsPage scope | P3 | Shows user's own tenants, not all platform tenants |
| TenantUsersPage permission UI | P3 | Add/Remove buttons only disabled in demo mode, not by permission |

---

## 8. Known Limitations

- Production LLM provider not available (deterministic only)
- No pagination, search, or filtering on list endpoints
- No frontend component/routing test coverage
- No migration tests (schema evolution)
- No performance/load tests
- macOS cross-platform verification pending (Joe)
- ApplicationRole provisioning remains environment-configured (no runtime API)
- Last-owner deletion prevention not implemented
- Delete race-condition hardening not implemented
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

---

## 11. Next Recommended Development Priorities

Ordered by dependency and risk:

1. **Migrate API endpoints to Pydantic models** — Replace `Dict[str, Any]` with typed request/response models for validation and OpenAPI documentation.
2. **Standardize datetime handling** — Replace `datetime.now()` with `datetime.now(timezone.utc)` for consistency.
3. **Fix generic exception re-raise** — Preserve exception types in knowledge.py, connectors.py, skills.py.
4. **Replace print() with logger** — Use structured logging for initialization.
5. **Migrate to lifespan context manager** — Replace deprecated `@app.on_event("startup")`.
6. **Add frontend component tests** — Critical user flows (membership management, tenant creation, skill execution) need regression protection.
7. **Production LLM provider** — Platform is architecturally ready but can only use deterministic local LLM.
8. **Consider PostgreSQL RLS** — Defense-in-depth for tenant isolation.
9. **Foundation completion review** — Verify all three developers can independently clone, configure, start, test, lint, and use the AI development workflow.

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
