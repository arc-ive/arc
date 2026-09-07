# Arc — Current State

Last Updated: 2026-09-07

Current Phase: Foundation Phase — All foundation modules merged; product implementation pending Foundation acceptance.

Git Baseline: `9b8b117` (origin/main, 2026-09-06)

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

Key architectural decisions (ADR-001 through ADR-008) are approved and documented in `docs/architecture/decisions/`. The architecture is framework-agnostic at the domain layer (ADR-001) with explicit boundaries for connectors, webhooks, AI tools, and unified intelligence.

---

## 2. Implemented Capabilities

### 2.1 Authentication — IMPLEMENTED

JWT HS256 bearer authentication. Tokens carry only identity (`sub` claim). No roles, permissions, or tenant context in tokens. Algorithm allowlist enforced (`HS256` only). Issuer and audience validated. Minimum 16-character secret required; missing/short secret prevents authentication entirely (fail closed).

- Source: `src/arc/security/jwt.py`, `src/arc/security/settings.py`
- Dependency: `src/arc/security/dependencies.py` — `get_authenticated_principal`

### 2.2 Authorization / RBAC — IMPLEMENTED

24 permissions across 4 `ApplicationRole` values. Fail-closed default: unknown users, unknown roles, and unlisted permissions are always denied. Role assignments are environment-configured (`APPLICATION_ROLE_ASSIGNMENTS` JSON).

| Role | Permissions | Notable |
|------|-------------|---------|
| PLATFORM_ADMINISTRATOR | 24 | Full access including platform-level operations |
| COMPANY_ADMINISTRATOR | 19 | No TENANT_CREATE, USER_CREATE, USER_READ, OBSERVABILITY_PLATFORM_READ |
| OPERATIONS_USER | 11 | Read + execute, no create/delete for tenants/users/skills |
| EMPLOYEE | 1 | KNOWLEDGE_READ only (Ask Arc / Company Brain read) |

- Source: `src/arc/security/authorization.py`
- Permissions defined at lines 99-122, matrix at lines 125-198

### 2.3 Multi-Tenancy — IMPLEMENTED

Every tenant-scoped table has a `tenant_id` column with `ON DELETE CASCADE` foreign key. Every repository query includes a `tenant_id` WHERE clause. The trusted `TenantContext` (derived from database membership verification) is the authoritative tenant boundary. Path-tenant consistency is defensively checked on every tenant-scoped endpoint.

- Tenant isolation: application-level SQL scoping (no PostgreSQL RLS)
- Cross-tenant access: denied at SQL level + application level + API level

### 2.4 Tenant Lifecycle — IMPLEMENTED

`POST /tenants` creates a tenant AND assigns the authenticated creator as OWNER, atomically via `create_tenant_with_owner`. `PUT /tenants/{tenant_id}` updates company configuration fields. Status mutation via PUT is explicitly rejected.

- Source: `src/arc/api/controllers.py:267-367`
- Atomic creation: `src/arc/services/domain.py:31-65`
- DB atomicity: `src/arc/db/connection.py:85-106`

### 2.5 Membership Model — IMPLEMENTED

**UserRole** (tenant membership): OWNER, MEMBER, VIEWER — stored in `memberships.role`, derived from database, never caller-supplied.

**ApplicationRole** (platform RBAC): PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER, EMPLOYEE — configured via environment, independent of UserRole.

Per ADR-008: These two role systems are completely independent. No automatic mapping. Membership does not grant application permissions. ApplicationRole does not grant tenant access.

**Production endpoints:**
- `POST /tenants/{tenant_id}/memberships` — creates membership (PLATFORM_ADMINISTRATOR only)
- `DELETE /tenants/{tenant_id}/memberships/{user_id}` — removes membership (PLATFORM_ADMINISTRATOR only)

**Dev endpoint** (APP_ENV=development only):
- `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships`

- Source: `src/arc/api/controllers.py:454-519`, `src/arc/api/dev_controllers.py:32-69`

### 2.6 Knowledge / Company Brain — IMPLEMENTED

Tenant-scoped knowledge document storage with PII sanitization (Microsoft Presidio). Documents have identity via `(tenant_id, source, external_id)` per ADR-003. Re-ingestion of identical content is idempotent; changed content triggers version bump with chunk replacement.

- Schema: `knowledge_documents` (12 columns, CHECK constraints, partial unique index on external_id)
- Source: `src/arc/services/knowledge.py` (312 lines)
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

- Source: `src/arc/services/intelligence.py` (257 lines), `src/arc/services/llm.py` (220 lines)

### 2.9 AI Agents — PARTIALLY IMPLEMENTED

`AgentExecutionService` runs bounded workflows with skill selection. `MAX_AGENT_STEPS = 3`. The agent holds no tool registry, no handlers — all actions flow through `SkillExecutionService`.

**What is implemented:**
- Agent execution with skill selection via LLM
- Step limit enforcement
- Structured outcome (succeeded, failed, approval_required, max_steps_reached)
- Skill-based execution (no direct tool access)

**What is NOT implemented (deferred):**
- Production LLM provider for decision-making
- Agent execution metrics/observability

- Source: `src/arc/services/agent.py` (287 lines)

### 2.10 AI Tools / Skills — IMPLEMENTED

**AI Tools:** Platform-owned, code-defined catalog. Currently one tool: `check_service_health`. Per-tool authorization enforced fail-closed. Tool execution records stored with audit minimization (secrets redacted, summaries truncated).

**Skills:** Tenant-owned skill definitions stored as JSONB. PII sanitization on all textual fields. Execution engine validates proposals against `allowed_tools`, resolves through platform registry, enforces preconditions, and manages approval-required skills.

- Tool source: `src/arc/services/tools.py` (807 lines)
- Skill source: `src/arc/services/skills.py` (122 lines), `src/arc/services/skill_execution.py` (378 lines)
- Schema: `skills` (JSONB definition), `tool_execution_records` (audit)

### 2.11 Human Approval / Intervention — IMPLEMENTED

Approval gate for high-risk tool executions. Lifecycle: pending → approved | rejected | expired (terminal); approved → consumed exactly once. Self-approval prevented. Lazy expiry at read time. Race-safe unique partial index on pending bindings.

- Source: `src/arc/services/approvals.py` (266 lines)
- Schema: `approval_requests` (13 columns, CHECK constraints, partial unique index)
- Permissions: APPROVAL_READ, APPROVAL_DECIDE

### 2.12 Connectors — IMPLEMENTED

GitHub, Slack, and Linear provider integrations with SSRF protection (approved host allowlist, manual URL parsing, no redirects). Credentials are environment-injected, never tenant-supplied, persisted, or returned. Connector sync content passes through PII guard before ingestion.

- Providers: `src/arc/services/connector_providers/` (GitHub, Slack, Linear, Fake, base, registry, targets)
- Sync: `src/arc/services/connector_sync.py` (201 lines)
- Schema: `connector_configs`, `connector_sync_records`
- Permissions: CONNECTOR_CREATE, CONNECTOR_READ, CONNECTOR_SYNC

### 2.13 Webhook Ingestion — IMPLEMENTED

Inbound-only webhook ingestion with HMAC-SHA256 authentication. Constant-time signature comparison. Timestamp-window replay resistance (±300s). Streaming body cap (64KB) before authentication. Idempotent duplicate handling. Raw payloads never persisted.

- Source: `src/arc/services/webhook_ingestion.py` (224 lines), `src/arc/services/webhook_config.py` (131 lines)
- Schema: `webhook_events` (metadata only, UNIQUE on tenant+event_id)
- Permission: WEBHOOK_READ

### 2.14 Observability / Telemetry — IMPLEMENTED

Best-effort HTTP telemetry with correlation IDs. Success-gated path-param tenant attribution. Structured logging with stdlib. Usage summary aggregation from authoritative subsystem tables. Component health probes.

- Source: `src/arc/services/observability.py` (181 lines), `src/arc/repositories/observability.py` (237 lines)
- Schema: `api_request_records` (metadata only, nullable tenant_id)
- Permissions: OBSERVABILITY_READ, OBSERVABILITY_PLATFORM_READ

### 2.15 Frontend — IMPLEMENTED

React + React Query + React Router. Role-aware navigation with 4 persona levels. JWT authentication with session expiry handling. Tenant workspace (17 routes) and platform console (7 routes). Loading/error/empty states on all pages. Demo mode handling.

- Source: `frontend/src/` (~100 files)
- Routing: `frontend/src/App.jsx` (156 lines)
- Navigation: `frontend/src/components/shell/navigation.js` (159 lines)
- Capabilities: `frontend/src/auth/capabilities.js` (47 lines)

---

## 3. Database / Schema State

12 tables in `src/arc/db/schema.sql` (267 lines):

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
| `webhook_events` | Yes | FK tenants CASCADE, UNIQUE(tenant, event_id) |
| `api_request_records` | Nullable | FK tenants CASCADE, CHECK status_code/duration |
| `approval_requests` | Yes | FK tenants CASCADE, CHECK status, CHECK digest regex, partial unique index on pending |

Schema uses idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` for safe re-runs. No PostgreSQL Row-Level Security (RLS).

---

## 4. API Surface

30+ production endpoints on `api_router`, 1 dev endpoint on `dev_router` (APP_ENV=development only).

| Category | Endpoints | Key Permissions |
|----------|-----------|-----------------|
| Health | GET /health | None (public) |
| Auth | GET /auth/me | Authenticated |
| Tenants | POST, GET, PUT /tenants | tenant:create, tenant:read, tenant:update |
| Users | POST /users, GET /platform/users, GET /tenants/{id}/users | user:create, user:read, tenant:read |
| Memberships | POST, DELETE /tenants/{id}/memberships | membership:create |
| User Tenants | GET /users/{id}/tenants | Self-scoped |
| Knowledge | POST, GET, GET list /tenants/{id}/knowledge | knowledge:create, knowledge:read |
| Search | GET /tenants/{id}/knowledge/search | knowledge:read |
| Intelligence | POST /tenants/{id}/intelligence/query | knowledge:read |
| Skills | POST, GET, GET by id, DELETE, POST execute /tenants/{id}/skills | skill:create/read/delete/execute |
| Agent | POST /agent/runs | agent:execute |
| Tools | GET, POST execute /tenants/{id}/tools | tool:read, tool:execute |
| Connectors | GET, POST, POST sync /tenants/{id}/connectors | connector:create/read/sync |
| Webhooks | POST /webhooks/{id}/events, GET /tenants/{id}/webhooks/events | HMAC auth, webhook:read |
| Observability | GET /tenants/{id}/observability/usage-summary, GET /platform/observability/summary, GET /observability/health | observability:read, observability:platform_read |
| Approvals | GET, GET by id, POST decide /tenants/{id}/approvals | approval:read, approval:decide |

**API contract note:** Request bodies use `Dict[str, Any]` rather than Pydantic models. Domain models validate via `__post_init__`. This is technical debt — it weakens automatic validation and OpenAPI documentation.

---

## 5. Testing State

68 test files in `tests/`. All backend tests run against real PostgreSQL (not mocked). Schema is dropped and recreated per test session.

- CI: `.github/workflows/ci.yml` — GitHub Actions on ubuntu-latest: `docker compose build arc`, `ruff check`, `ruff format --check`, `python -m pytest -q`
- Test infrastructure: `tests/conftest.py` — env pinning, TestClient lifecycle, DB fixtures, authorization overrides

**Last verified test count:** 1238 tests pass (Docker + real PostgreSQL), documented at time of PR #72 merge. Docker is available in this environment but containers are not running; full suite re-execution was not performed during this synchronization.

**Test coverage observations:**
- Exhaustive permission matrix test (4 roles × 24 permissions, parametrized)
- 18 API surface tests verifying production vs development OpenAPI
- 12 tenant isolation tests (cross-tenant, missing membership, self-scoping)
- Regression tests for Issues #58, #60, #70, #76
- No frontend component/routing tests beyond basic rendering
- No concurrent test isolation (manual cleanup, unique IDs mitigate)

---

## 6. Security Posture

| Control | Status | Evidence |
|---------|--------|----------|
| JWT algorithm allowlist | HS256 only | `jwt.py:23` — `ALLOWED_ALGORITHMS = ["HS256"]` |
| JWT carries identity only | No roles/permissions/tenant in tokens | `jwt.py:49` docstring |
| RBAC fail-closed | Unknown users/roles/permissions denied | `authorization.py:221-230` |
| Tenant isolation at SQL level | Every query has tenant_id WHERE | All repositories verified |
| Path-tenant consistency check | Defensive 403 on mismatch | `controllers.py:917-929` |
| PII guard on all content paths | Always applied, including re-ingestion | `knowledge.py:49,114` |
| Webhook HMAC auth | Constant-time, timestamp window, body cap | `webhook_ingestion.py` |
| SSRF protection on connectors | Approved host allowlist, no redirects | `connector_providers/targets.py` |
| Dev endpoint gating | APP_ENV=development at mount time | `main.py:55` |
| Self-scoped identity | user_id must match JWT sub | `controllers.py:536` |
| Secrets never in responses | Credentials masked in repr | `base.py`, `webhook_config.py` |
| Audit minimization | Sensitive keys redacted, summaries truncated | `tools.py:_redact` |
| Telemetry is metadata-only | No bodies, prompts, answers, tokens, secrets | `middleware.py`, `schema.sql` comments |
| Fail-closed defaults | Empty APPLICATION_ROLE_ASSIGNMENTS denies all | `settings.py:97` |

**No PostgreSQL RLS.** Tenant isolation relies entirely on application-layer SQL scoping. This is a defense-in-depth gap, not a vulnerability — the application layer consistently enforces isolation.

---

## 7. Known Technical Debt

| Item | Priority | Description |
|------|----------|-------------|
| Dict[str, Any] API bodies | P2 | Endpoints accept `Dict[str, Any]` instead of Pydantic models — weakens validation and OpenAPI docs |
| Naive datetime.now() | P2 | Used in knowledge.py (lines 137-138, 170), connectors.py, connector_sync.py — inconsistent with `datetime.now(timezone.utc)` used elsewhere |
| Generic exception re-raise | P2 | `raise Exception(f"...: {e}")` in knowledge.py:70-71, connectors.py:49-50, skills.py:99-100 loses original exception type |
| No RLS | P3 | No PostgreSQL Row-Level Security — defense-in-depth gap |
| print() for init logging | P3 | `app.py:59,214` — should use logger |
| Deprecated startup event | P3 | `@app.on_event("startup")` — functional, migrate to lifespan later |
| `"validated" not in locals()` | P3 | `tools.py:691` — fragile scoping pattern |
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
| #56 | Final architecture/product specification | MERGED (`76536fd`) |
| #68 | Tenant creation input focus fix | MERGED (`abed2d0`) |
| #72 | Production membership provisioning (Issue #59) | MERGED (`ce4ccbc`) |
| #74 | Tenant onboarding owner auto-assignment (Issue #58) | MERGED (`d513d7e`) |
| #78 | RBAC role independence clarification (Issue #60, ADR-008) | MERGED (`128b334`) |
| #79 | Platform user listing (Issue #61) | MERGED (`5909da6`) |
| #81 | Skill duplicate conflict (Issue #62) | MERGED (`4b2ffd9`) |
| #82 | Skill execution control (Issue #63) | MERGED (`971f0bb`) |
| #83 | Approval column mismatch fix (Issue #64) | MERGED (`37f9180`) |
| #84 | Usage field mapping fix (Issue #65) | MERGED (`231ca68`) |
| #85 | User form focus fix (Issue #69) | MERGED (`7f4c730`) |
| #86 | tldextract cache fix (Issue #73) | MERGED (`e39e970`) |
| #87 | Employee Ask Arc access fix (Issue #76) | MERGED (`25b4475`) |
| #88 | Employee Ask Arc access fix (Issue #66) | MERGED (`acb665f`) |
| #89 | Observability page fix (Issue #71) | MERGED (`c211841`) |
| #90 | Tenant company configuration (Issue #70) | MERGED (`8ba9aa1`) |
| #91 | Connector target field (Issue #75) | MERGED (`c46ef5c`) |
| #92 | Retrieval docstring fix (Issue #67) | MERGED (`37069ba`) |
| #93 | Knowledge API external_id wiring | MERGED (`9b8b117`) |

---

## 10. Approved Architecture Decisions

| ADR | Title | Status |
|-----|-------|--------|
| ADR-001 | Arc Unified Intelligence Architecture | Approved |
| ADR-002 | Connector Provider Selection | Approved |
| ADR-003 | Company Brain Document Identity and Re-ingestion | Approved |
| ADR-004 | Unified Intelligence Tool Calling Execution Contract | Approved |
| ADR-005 | Human Intervention Approval Gate | Approved |
| ADR-006 | Agent Skill Orchestration | Approved |
| ADR-007 | Production Embedding Provider and Vector Representation | Approved |
| ADR-008 | Tenant Membership and Application RBAC Roles | Approved |

---

## 11. Next Recommended Development Priorities

Ordered by dependency and risk:

1. **Update CURRENT_STATE.md** — This document (completed).
2. **Migrate API endpoints to Pydantic models** — Replace `Dict[str, Any]` with typed request/response models for validation and OpenAPI documentation.
3. **Standardize datetime handling** — Replace `datetime.now()` with `datetime.now(timezone.utc)` for consistency.
4. **Add frontend component tests** — Critical user flows (membership management, tenant creation, skill execution) need regression protection.
5. **Migrate to lifespan context manager** — Replace deprecated `@app.on_event("startup")`.
6. **Replace print() with logger** — Use structured logging for initialization.
7. **Fix generic exception re-raise** — Preserve exception types in knowledge.py, connectors.py, skills.py.
8. **Production LLM provider** — Platform is architecturally ready but can only use deterministic local LLM.
9. **Consider PostgreSQL RLS** — Defense-in-depth for tenant isolation.
10. **Foundation completion review** — Verify all three developers can independently clone, configure, start, test, lint, and use the AI development workflow.

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
