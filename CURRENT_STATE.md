# Arc — Current State

Last Updated:

2026-09-04

Current Phase:

Foundation Phase — X-10, X-11, and X-13 merged; ADR-002 through ADR-008 accepted; CI baseline established; Company Brain — Knowledge Storage & Ingestion Foundation merged (PR #26); Secure RAG — Semantic Retrieval Foundation merged (PR #29); Approved Context Contract + Unified Intelligence foundation merged (PR #33); AI Tools foundation merged (PR #31); Connector Provider Integrations merged (PR #32); Webhooks inbound foundation merged (PR #34); Company Brain document identity & re-ingestion merged per ADR-003 (PR #38); Company Brain legacy duplicate archival merged (PR #42); Webhook ingestion body-cap hardening merged (PR #43); Human Intervention Approval Gate V1 merged (PR #50); Approval observability slice merged (PR #51); ADR-007 production embedding architecture accepted; Production embedding provider + 64→1536 migration merged (PR #53); Frontend foundation + security hardening merged (PR #52); Secure RAG source-type filtering merged (PR #54); Issue #58 tenant onboarding owner auto-assignment merged (PR #74); Issue #60 RBAC role independence clarified (ADR-008)

## Completed

### GitHub Foundation

- GitHub organization created: `arc-ive`
- Private repository created: `arc`
- Local repository cloned
- Git remote configured
- `main` branch created and pushed
- Foundation branch created:
  `chore/repository-foundation`
- Repository foundation commit created:
  `d858bee`

### Repository Structure

Created:

```text
.devcontainer/
.github/
.github/ISSUE_TEMPLATE/
docs/
docs/product/
docs/requirements/
docs/architecture/
docs/architecture/decisions/
docs/engineering/
docs/operations/
scripts/
tests/
```

### Repository Governance

Created:

- `README.md`
- `.gitignore`
- `.env.example`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `CURRENT_STATE.md`

### GitHub Templates

Created:

- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/ISSUE_TEMPLATE/engineering_task.md`
- `.github/ISSUE_TEMPLATE/architecture_decision.md`

### Architecture Documentation

Created:

- `docs/architecture/decisions/ADR_TEMPLATE.md`

### Branch Protection

A GitHub ruleset has been configured for `main`.

The current GitHub organization/repository plan does not enforce the configured ruleset for this private repository.

The team will continue following the documented Pull Request workflow by policy.

CI-specific required status checks will be added after the platform and CI foundation is established.

The team may revisit repository visibility or GitHub plan options later if enforced branch protection becomes necessary.

## X-10: Tenant Membership Boundary (Complete)

**Commit:** `b85c06a feat(security): enforce tenant membership boundary`
**Branch:** `feat/platform-security-foundation`

X-10 enforces that every `TenantContext` is backed by a persisted `Membership` row. The membership role (OWNER / MEMBER / VIEWER) is derived from the database, never supplied by the caller.

### What changed

- **Repository contracts aligned.** Three concrete PostgreSQL repos (`PostgreSQLTenantRepository`, `PostgreSQLUserRepository`, `PostgreSQLMembershipRepository`) in `src/arc/repositories/tenancy.py` implement exact Protocol signatures from `src/arc/repositories/__init__.py`. The old `PostgreSQLTenancyRepository` was removed.
- **Domain services are membership-aware.** `TenantContextService.create_tenant_context(tenant_id, user_id)` has no role parameter; `validate_context` verifies persisted membership and role. Defined in `src/arc/services/domain.py`.
- **API validate endpoint fixed.** `GET /tenant-contexts/validate` (development-only, in `src/arc/api/dev_controllers.py`) fetches the real tenant via `tenant_service.get_tenant` and catches `NotFoundError` → `{"is_valid": False}`.
- **Integration tests added.** `tests/test_repository_integration.py` — 10 real-PostgreSQL tests (repo contracts, `create_tenant_context` valid/cross-tenant/missing-membership, role derived from persisted membership, `validate_context` valid/role-mismatch/missing).
- **Dependencies added.** `asyncpg>=0.30,<1.0` (runtime), `pytest-asyncio>=0.23,<1.0` (dev), `asyncio_mode = "auto"` in `pyproject.toml`.

### What was NOT changed

- PRD, TRD, ADRs — read-only, not modified.
- Source code outside X-10 scope — not modified.
- `app.py` composition root — already does its own wiring (not via `RepositoryFactory`).
- `httpx2` dependency — left as original (pre-existing separate issue).

### Verification

- 33 tests pass (Docker + real PostgreSQL).
- ruff check and format pass on X-10 files.
- Security review passed — all invariants confirmed.

### Review fix: API boundary isolation (merged)

Merged to `main` as `fa82369` via PR #15 (merge commit `63b36bf`).

Bharath's X-10 PR review raised two API-boundary concerns; both are
addressed without implementing authentication or RBAC:

- Membership provisioning (`POST /users/{user_id}/tenants/{tenant_id}/memberships`)
  was a public, unauthenticated endpoint capable of granting OWNER. It is
  now isolated in a development-only router under `/internal/dev/...`,
  mounted only when `APP_ENV=development`. The service and repository
  provisioning capability (`UserService.associate_user_with_tenant`,
  `MembershipService.create_membership`) is preserved for X-11.
- Tenant-context endpoints accepted a caller-supplied `user_id`. They are
  now development-only scaffolding. The service boundary
  (`Authenticated Principal -> trusted user identity -> TenantContextService
  -> TenantContext`) is unchanged; X-11 will supply the trusted identity.

Regression tests in `tests/test_api_surface.py` verify the public API
surface, the development-only isolation, and the intended identity flow.

### Known gaps (pre-existing, not X-10 defects)

- Membership provisioning is development-only (no public endpoint) and is now protected by X-11 authentication + the `membership:create` permission.
- `httpx2>=2.0,<3.0` is the original dependency; real `httpx` has no 2.x releases. `tests/test_health.py` uses FastAPI's `TestClient` which requires real `httpx`. Pre-existing separate dependency defect.
- The repo-wide lint/format gate passes on current `main`, verified locally against a freshly rebuilt application image.

## X-11: Authentication and Application RBAC (Merged)

**Branch:** `feat/authentication`
**Issue:** GitHub #14 — "feat: implement authentication and RBAC foundation"
**Merge:** PR #19 (commit `987ae33`)

X-11 adds JWT HS256 bearer authentication and application RBAC, integrated
with the X-10 tenant membership boundary.

### What changed

- **New `src/arc/security/` package:**
  - `models.py` — `ApplicationRole` (platform_administrator, company_administrator,
    operations_user, employee), `AuthenticatedPrincipal` (user_id ONLY, from JWT
    `sub`), `Permission` (resource:action).
  - `settings.py` — `SecuritySettings` from environment, `JWT_SECRET` (min 16
    chars, fail closed), `APPLICATION_ROLE_ASSIGNMENTS` JSON (user_id -> role,
    fail closed on invalid input).
  - `jwt.py` — `JwtService` HS256 only, required/validated `sub`/`exp`/`iss`/`aud`,
    tokens never carry roles/permissions/tenant claims.
  - `authorization.py` — minimal permission matrix (`tenant:create`,
    `user:create`, `membership:create` = PLATFORM_ADMINISTRATOR only;
    `tenant:read` = platform/company admin + operations; EMPLOYEE has none).
    Default DENY. `ApplicationRole` is completely independent of the X-10
    `UserRole` (no mapping).
  - `dependencies.py` — `get_authenticated_principal`, `get_trusted_tenant_context`
    (X-10 boundary, lazy app_context import), `require_permission`,
    `require_tenant_permission`.
- **Public endpoints protected** in `src/arc/api/controllers.py`:
  `POST /tenants` (tenant:create), `POST /users` (user:create),
  `GET /tenants/{tenant_id}` and `GET /tenants/{tenant_id}/users`
  (tenant:read + trusted context), `GET /users/{user_id}/tenants`
  (authenticated + self-scoped: client-supplied user_id differing from the
  JWT identity is denied 403; identity never silently substituted).
- **Dev router** (`src/arc/api/dev_controllers.py`): membership provisioning
  now requires `membership:create` (PLATFORM_ADMINISTRATOR). The two
  caller-supplied-identity tenant-context scaffolding endpoints
  (`POST /internal/dev/tenant-contexts`,
  `GET /internal/dev/tenant-contexts/validate`) were REMOVED.
- **Config:** `PyJWT>=2.9,<3.0` added; `JWT_*` and `APPLICATION_ROLE_ASSIGNMENTS`
  documented in `.env.example` (dev placeholder, not a secret) and wired through
  `docker-compose.yml`.
- **Tests:** new `tests/conftest.py` (env pinning, TestClient lifecycle,
  DB/repo/seeded fixtures, `authorization_override`),
  `tests/test_authentication.py` (401s, expired/wrong-issuer/audience,
  no-sub, alg allow-list, identity cannot be injected),
  `tests/test_rbac.py` (permission matrix, fail-closed, endpoint-level 403s),
  `tests/test_tenant_authorization.py` (real PG: trusted context, cross-tenant
  denial, missing membership/tenant denial, membership role never grants
  application permissions, self-scope). `tests/test_api_surface.py` updated:
  dev surface is membership-only; removed scaffolding absent everywhere.

### Implementation decisions (not in the issue)

- `AuthorizationService` is built lazily in `security/dependencies.py` (not
  registered in `app.py`) so `/health` works when `JWT_SECRET` is unset.
- Generic 401 for all credential failures; 403 for permission/tenant denials
  (fail closed, no existence leakage for missing tenants).

### Verification

- 87 tests pass (Docker + real PostgreSQL), repeated runs deterministic.
- `ruff check` passes on all X-11 files; `ruff format --check` clean.
- Smoke-tested over real HTTP: /health public; protected endpoints 401
  without token; valid platform-administrator token creates a tenant; tenant
  read without membership denied 403.
- Pre-existing ruff violations remain in unmodified X-10 files
  (`src/arc/db/connection.py`, `src/arc/domain/__init__.py`,
  `src/arc/setup/init.py`). Not part of X-11 scope.

### Status

- Merged to `main` via PR #19 (commit `987ae33`).
- `.env` (local, gitignored) contains a development-only JWT secret and
  `demo-user` as platform_administrator for the simulated environment.

## Company Brain — Knowledge Storage & Ingestion Foundation (Merged)

**Branch:** `feat/company-brain-foundation`
**Base:** `origin/main` (reconciled with current main)
**Merge:** PR #26 (merge commit `d65b57f`)
**Scope:** authorized slice of the Company Brain module — tenant-scoped
knowledge document storage and PII-boundary ingestion. Reuses the merged
X-10 (tenancy), X-11 (auth/RBAC), and PII Guard foundations.

### What changed

- **Schema** (`src/arc/db/schema.sql`): new `knowledge_documents` table
  (id PK, tenant FK ON DELETE CASCADE, source, provenance, version >= 1,
  status in active/archived, content, created/updated timestamps) with
  CHECK constraints and a tenant index. No embedding/vector columns, no
  chunking tables, no retrieval indexes (out of scope by authorization).
- **Domain** (`src/arc/domain/models.py`): `KnowledgeDocument` dataclass
  with `__post_init__` validation; `KnowledgeSource` (policy, procedure,
  incident_report, troubleshooting, internal_knowledge, solution — maps to
  TRD 9.2 knowledge categories); `KnowledgeStatus` (active, archived).
  `version` is stored as document metadata (TRD 9.1): this foundation does
  NOT implement document revision/update semantics, and no logical document
  identity or uniqueness relationship between documents and versions is
  claimed. Future document lifecycle/version-management work (out of scope
  for this slice) may define the identity and uniqueness model; ADR-001
  keeps the Company Brain schema open.
- **Repository** (`src/arc/repositories/knowledge.py`):
  `PostgreSQLKnowledgeRepository` implementing the `KnowledgeRepository`
  Protocol (`src/arc/repositories/__init__.py`). Every query includes a
  `tenant_id` condition — cross-tenant access is impossible at the SQL
  level. `NotFoundError`/`DuplicateKeyError` on missing/duplicate.
- **Service** (`src/arc/services/knowledge.py`): `KnowledgeService` with
  `ingest_document`/`get_document`/`list_documents`. The tenant boundary
  comes exclusively from a trusted X-10 `TenantContext`. Ingestion runs
  raw content through the existing `PiiGuardService` (Microsoft Presidio)
  BEFORE persistence; on `PiiGuardError` nothing is persisted (fail
  closed). The PII guard is reused, not reimplemented.
- **Authorization** (`src/arc/security/authorization.py`): new permissions
  `knowledge:create` and `knowledge:read`. PLATFORM_ADMINISTRATOR and
  COMPANY_ADMINISTRATOR: both; OPERATIONS_USER: `knowledge:read`;
  EMPLOYEE: none. Default DENY.
- **API** (`src/arc/api/controllers.py`): `POST /tenants/{tenant_id}/knowledge`
  (create, sanitized), `GET /tenants/{tenant_id}/knowledge/{document_id}`
  (404 for missing/inaccessible — no existence leakage), and
  `GET /tenants/{tenant_id}/knowledge` (list). All behind
  `require_tenant_permission`. The path `tenant_id` is validated for
  consistency against the trusted `TenantContext` (403 on mismatch) but the
  tenant boundary is always derived from the trusted context. Only
  sanitized content is ever persisted or returned.
- **Composition root** (`src/arc/app.py`): `PostgreSQLKnowledgeRepository`
  and `KnowledgeService` registered alongside existing services.
- **Tests** (new): `tests/test_knowledge_domain.py`,
  `tests/test_knowledge_repository.py` (real PG, SQL-level tenant
  isolation), `tests/test_knowledge_service.py` (PII boundary,
  fail-closed no-persistence, real PiiGuardService integration),
  `tests/test_knowledge_api.py` (401/403, permission matrix, cross-tenant
  denial, raw PII sanitized before persistence and response, path-tenant
  consistency 403, explicit nonexistent-document 404, list-endpoint PII
  sanitization).
  `tests/test_rbac.py` updated for the knowledge permission matrix.

### What was NOT changed

- Embeddings, pgvector extension/columns, chunking, retrieval/RAG, Skills,
  AI Agent, Unified Intelligence, webhooks, observability, connector
  ingestion — all explicitly out of scope for this slice.
- PII Guard implementation (`src/arc/services/pii.py`) — reused, untouched.

### Verification

- 249 tests pass (Docker + real PostgreSQL), 4 warnings, 0 failures — the
  43 original knowledge tests plus 5 tests added by the PR #26 review
  fixes.
- `ruff check` and `ruff format --check` pass on `src` and `tests`.
- Mandatory `docker compose build arc` completed (arc service has no volume
  mount; image rebuilt with the new code before verification).
- The branch was reconciled with the merged Skills Engine foundation
  (`origin/main`) before the final verification.

### Status

- Merged to `main` via PR #26 (merge commit `d65b57f`).

## Secure RAG — Semantic Retrieval Foundation (Merged)

**Branch:** `feat/secure-rag-foundation`
**Base:** `origin/main` (Company Brain foundation + Skills Engine)
**Merge:** PR #29 (merge commit `a5b892b`)

Author: Bharath. Implements the documented semantic half of the approved
Secure RAG proposal (`docs/` + `C:\Users\subra\Downloads\Arc_Secure_RAG_Proposal.pdf`).

### What changed

- **Schema** (`src/arc/db/schema.sql`): `CREATE EXTENSION IF NOT EXISTS vector`;
  new `knowledge_chunks` table (id PK, document FK ON DELETE CASCADE, tenant FK
  ON DELETE CASCADE, content, sequence >= 0, `embedding vector(1536)`) with tenant
  and document indexes and an HNSW cosine index on the embedding column.
- **Chunking** (`src/arc/services/chunking.py`): deterministic,
  whitespace-aware `KnowledgeChunker` (max_chars/overlap_chars, no content loss).
- **Embeddings** (`src/arc/services/embeddings.py`): `EmbeddingProvider`
  protocol, `DeterministicEmbeddingProvider` (L2-normalized, word-hash
  histogram), `EmbeddingError` (fail closed). Production provider: `OpenAIEmbeddingProvider`
  (ADR-007, text-embedding-3-small, 1536-dim, gateway-routable via configurable `base_url`).
- **Repository** (`src/arc/repositories/retrieval.py`):
  `PostgreSQLKnowledgeChunkRepository` — atomic `create_many` (one transaction),
  tenant-scoped `search` at the SQL level (similarity at the PostgreSQL/pgvector
  layer, never fetch-all-and-filter in Python).
- **Service** (`src/arc/services/retrieval.py`): `RetrievalService` with
  `prepare_index`/`persist_index`/`search` — fail-closed ordering (embeddings
  computed before any persistence), trusted `TenantContext` is the only tenant
  boundary, `EMBEDDING_DIMENSIONS` validation against provider output.
- **API** (`src/arc/api/controllers.py`): `GET /tenants/{tenant_id}/knowledge/search`
  behind the existing `knowledge:read` permission (retrieval is not a new
  capability); path-tenant consistency 403; generic 500 on `EmbeddingError`.
- **Tests** (net +63): chunking, embeddings, real-PostgreSQL chunk repository
  (SQL-level tenant isolation, ranking, cascade, atomicity), retrieval service
  (fail-closed embedding/dimension), retrieval API (401/403/400/500, cross-tenant
  denial, PII-sanitized results).

### Verification

- 333 tests pass (Docker + real PostgreSQL), 4 warnings, 0 failures.
- `ruff check` / `ruff format --check` clean; `docker compose build arc` OK;
  `docker compose config --quiet` exit 0; `git diff --check` clean.

### Status

- Merged to `main` via PR #29 (merge commit `a5b892b`).

## Secure RAG — Approved Context Contract (Merged)

**Branch:** `feat/approved-context-contract`
**Base:** `origin/main` (Secure RAG Semantic Retrieval Foundation, PR #29)

Next slice after the merged Secure RAG foundation: establishes the secure
retrieval boundary up to the **Approved Context Contract** (proposal §9). No
LLM/Agent/Unified Intelligence/Skills/tooling/PageIndex integration.

### What changed

- **Domain** (`src/arc/domain/models.py`): `RetrievalMethod` enum
  (dense_semantic only; lexical/fusion/reranking/modular are later enum values);
  `KnowledgeMatch.sequence` (chunk position, required for citation);
  `ApprovedContextItem` (sanitized content + document/chunk ids, source,
  provenance, document_version, sequence, relevance_score, citation_reference);
  `ApprovedContextSecurityMetadata` (tenant_id, authorization_status,
  pii_status); `ApprovedContext` (request_id, tenant_id, principal_id, query,
  retrieval_method, items, security_metadata) — the ONLY representation a future
  Unified Intelligence/LLM layer may consume.
- **Repository** (`src/arc/repositories/retrieval.py`,
  `src/arc/repositories/knowledge.py`): `search` now returns `c.sequence`;
  defensive tenant-consistency guards in `create_many` (all chunks one tenant)
  and `create_document_with_chunks` (all chunks match the document tenant) —
  both fail closed with `ValueError` before any write.
- **Embeddings** (`src/arc/services/embeddings.py`): `EmbeddingSettings`
  (provider/model/dimensions) read from `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`,
  `EMBEDDING_DIMENSION`; `EmbeddingConfigurationError` on invalid config;
  `build_embedding_provider` factory — unknown providers fail closed at startup.
  Dimension is locked to the storage dimension `vector(1536)` (schema change is a
  deferred decision). Supported providers: `deterministic` (dev/tests) and
  `openai` (production, ADR-007). Gateway routing via configurable `base_url`.
  Documented in `.env.example`.
- **Service** (`src/arc/services/retrieval.py`): `RetrievalService.approved_search`
  builds the contract from tenant-scoped retrieval; re-validates every match
  against the trusted tenant (cross-tenant match → `RuntimeError`, fail closed);
  no-match → safe empty contract.
- **API** (`src/arc/api/controllers.py`): search response adds the additive
  `sequence` key. No new endpoint; the contract is a service/domain-level
  boundary (proposal §9: keep it a domain/service-level contract).
- **Composition root** (`src/arc/app.py`): embedding provider wired through
  `build_embedding_provider(get_embedding_settings())`.

### Tests (net +22)

- `tests/test_approved_context.py` (new): contract domain validation; contract
  build from matches; provenance/citation; ordering/scores preserved; trusted
  tenant only; cross-tenant match fails closed; embedding failure produces no
  contract; empty result safe.
- `tests/test_embeddings.py`: embedding settings defaults/env reading,
  invalid/mismatched dimension fails closed, empty provider fails closed,
  provider factory (deterministic built, unknown fails closed).
- `tests/test_retrieval_repository.py`: `sequence` returned from search,
  mixed-tenant `create_many` rejected atomically.
- `tests/test_knowledge_repository.py`: document/chunk tenant mismatch rejected
  atomically.
- `tests/test_retrieval_service.py` / `tests/test_retrieval_api.py`: updated for
  `KnowledgeMatch.sequence` and the additive `sequence` response key.

### Verification

- 355 tests pass (Docker + real PostgreSQL), 4 warnings, 0 failures.
- `ruff check` / `ruff format --check` clean; `docker compose config --quiet`
  exit 0; `git diff --check` clean; no secrets/conflict markers.
- Runtime smoke: built image imports `ApprovedContext` and constructs the
  configured `DeterministicEmbeddingProvider`.

### Merged to main

- Merged to `main`.

## AI Tools — AI Tools Foundation (Merged)

**Branch:** `feat/ai-tools-foundation`
**Base:** `origin/main` (reconciled with current main)
**Scope:** authorized slice of the AI Tools module (PRD 15, TRD 14) —
platform-owned, code-defined AI Tool catalog and controlled execution,
integrated with the merged X-10 (tenancy), X-11 (auth/RBAC), and ADR-001
framework-agnostic boundaries.

### Platform-owned catalog statement (recorded per review)

- Tenants cannot register arbitrary tools, upload executable code, or
  execute arbitrary Python/JS/shell.
- Tenants gain tenant-scoped access to the platform-owned AI Tool catalog
  exclusively through the existing authorization model
  (`tool:read`, `tool:execute`, and each tool's declared required
  permissions).
- Tenant-level enable/disable configuration may come later.
- Dynamic tenant-defined tools are explicitly deferred.

### What changed

- **Catalog** (`src/arc/services/tools.py`): static, versioned,
  platform-owned whitelist (`check_service_health` v1). The registry
  exposes only read operations; no runtime registration or mutation API.
  `ToolDefinition` fails closed at construction: non-empty
  `required_permissions` of `Permission` objects, and high-risk tools
  must declare `REQUIRE_HUMAN_APPROVAL` or `DENY` (never `ALLOW`).
- **Execution policy** (`ToolExecutionPolicyMode`): ALLOW / DENY /
  REQUIRE_HUMAN_APPROVAL are explicitly represented. REQUIRE_HUMAN_APPROVAL
  and DENY fail closed with a controlled, audited denial; the Human
  Intervention approval gate itself is not implemented in this slice.
- **Per-tool authorization**: execution requires `tool:execute` AND every
  permission declared by the tool, enforced fail-closed inside
  `ToolExecutionService` using the existing `AuthorizationService`
  (defense in depth under the controller's `tool:execute` dependency).
  Unknown tool, missing/invalid permission metadata, and insufficient
  permissions are denied before any handler runs and are audited.
- **Tenant isolation**: the tenant boundary comes exclusively from the
  trusted X-10 `TenantContext`; the path `tenant_id` is request input
  only and is validated for consistency (403 on mismatch). An invalid
  context fails closed with no audit record.
- **Audit contract** (`tool_execution_records`): now explicitly records
  who (user_id), tenant, tool name/version, authorization outcome
  (granted/denied), risk level, status, error kind, execution id, and
  timestamp. Data minimization: summaries are redacted for sensitive
  keys (password/token/secret/api_key/...) and truncated; secrets,
  credentials, raw sensitive payloads, and stack traces never reach
  records.
- **API** (`src/arc/api/controllers.py`): `GET /tenants/{tenant_id}/tools`
  (`tool:read`) and `POST /tenants/{tenant_id}/tools/{name}/execute`
  (`tool:execute` + per-tool permissions). Catalog responses expose only
  safe metadata (`required_permissions`, schemas, risk level) and never
  handlers. No registration/modification/upload surface exists.
- **Schema** (`src/arc/db/schema.sql`): `tool_execution_records` extended
  with `user_id` and `authorization_outcome` (idempotent bootstrap via
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- **Tests**: `tests/test_tool_api.py`, `test_tool_domain.py`,
  `test_tool_registry.py`, `test_tool_repository.py`,
  `test_tool_service.py` — per-tool authorization matrix, tenant
  isolation (A→A, A→B 403, mismatch no side effects, missing context),
  read-only registry API (405/404 on mutation attempts), code-execution
  guards, audit minimization (secrets absent from records), and the
  fail-closed metadata/policy cases (real PostgreSQL).

### What was NOT changed

- Agent/LLM calling, Skills execution, Webhooks, Connectors, Secure RAG,
  Human Intervention, production/external integrations — explicitly out
  of scope for this slice.
- No new ADR: ADR-001 already keeps the tool layer framework/agent
  agnostic, and this slice implements only platform-owned definitions.

### Review response (security review round 2)

- **Legacy audit migration** (`src/arc/db/schema.sql`): the idempotent
  bootstrap columns `user_id` and `authorization_outcome` are added
  NULLABLE so pre-audit-contract databases are upgraded without
  fabricating audit facts: historical rows keep NULL `user_id` (no
  invented identity) and NULL `authorization_outcome` (no invented
  GRANTED). New records still require a real trusted `user_id` and a
  real GRANTED/DENIED outcome through `ToolExecutionService`; fresh
  installs additionally keep NOT NULL columns at table creation. Proven
  by `tests/test_tool_audit_migration.py` (real PostgreSQL: old schema +
  historical rows -> current bootstrap -> history preserved -> new
  records strict).
- **Audit ownership boundary**: central authentication/RBAC failure
  (403 from the FastAPI security dependencies before the service runs,
  e.g. missing `tool:execute`) is owned by the central security/audit
  boundary: `ToolExecutionService` is NOT invoked and no
  `tool_execution_records` row is written. Per-tool authorization
  failure (holds `tool:execute`, lacks a tool-declared permission) is
  owned by the service and recorded with `authorization_outcome=DENIED`.
  Documented in `src/arc/services/tools.py`; proven by
  `test_user_without_tool_execute_never_invokes_service_or_handler`
  (403, handler never runs, zero records) alongside the existing DENIED-
  record test.
- **Audit redaction**: sensitive key variants now include
  `access_token`, `refresh_token`, `client_secret`; redaction applies at
  every nesting depth (objects, arrays, deep nesting). Free-form text is
  intentionally retained (documented policy: only keyed values are
  redacted; summaries are bounded by platform-owned handlers and
  validated input models). Oversized summaries are truncated to the
  configured maximum (512) end-to-end. Handler exceptions never leak:
  `error_kind` stays a safe classification (`execution_error`, etc.) and
  raw messages/secrets never reach records or API responses.
- **`_summarize` fallback hardening**: an unserializable payload (e.g.
  non-string dict keys or a self-referential structure) now produces a
  fixed safe marker (`[unserializable <type> payload redacted]`) instead
  of a raw `str()` that could bypass keyed redaction.

### Verification

- 427 tests pass (Docker + real PostgreSQL) on both a fresh and a warm
  database.
- `ruff check .` and `ruff format --check .` pass.
- `docker compose config --quiet` passes; `compileall` clean.

### Merged to main

- Merged to `main` (PR #31).

**Branch:** `chore/ci-github-actions` (merged to `main` via PR #23)

- Added `.github/workflows/ci.yml` (GitHub Actions, `ubuntu-latest`).
- Triggers: pushes to `main` and pull requests targeting `main`.
- Checks use the existing Docker Compose environment:
  - `docker compose build arc`
  - `docker compose run --rm arc ruff check .`
  - `docker compose run --rm arc ruff format --check .`
  - `docker compose run --rm arc python -m pytest -q`
- Environment values are development/test placeholders only; no real
  credentials.
- The repo-wide lint/format gate passes on current `main`, verified locally
  against a freshly rebuilt application image.
- GitHub Actions CI is active on `main`.
## Unified Intelligence — Secure Knowledge Reasoning Foundation (Merged)

**Branch:** `feat/approved-context-contract`
**Base:** `origin/main` (Secure RAG Semantic Retrieval Foundation, PR #29)

Next TRD-ordered slice after Skills Engine (management, PR #25) and the
Approved Context Contract: the first leg of Unified Intelligence (TRD §8,
§10, §12, §34, §39; PRD §12, §14, §26; ADR-001) — secure reasoning over
the tenant's approved knowledge. No Skills execution, AI Tools, agent
workflows, webhooks, or autonomous actions (later maturity layers).

### What changed

- **Domain** (`src/arc/domain/models.py`): `IntelligenceAnswer` (request_id,
  tenant_id, principal_id, query, answer, citations, retrieval_method,
  context_used) — validated; `answer` is `None` when no approved context was
  available (nothing is invented); citations make every answer attributable.
- **LLM abstraction** (`src/arc/services/llm.py`): `LlmProvider` protocol,
  `LlmError`, `LlmConfigurationError`, `LlmSettings` (provider/model) from
  `LLM_PROVIDER`/`LLM_MODEL`, `get_llm_settings`, `build_llm_provider`
  factory — only the deterministic local provider is supported; unknown
  providers fail closed at startup (production provider, OpenRouter primary
  per TRD §34, remains a deferred decision). The LLM is NOT the
  authorization system (TRD §10.3): providers receive only prompt text.
- **Service** (`src/arc/services/intelligence.py`): `UnifiedIntelligenceService.answer_query`
  — the ONLY retrieval path is `approved_search` (no repository reference);
  the prompt is assembled exclusively from `ApprovedContext` items (sanitized
  content + citation references; no tenant/principal IDs, vectors, scores, or
  authorization state); no approved context → LLM never invoked, answer
  `None`; embedding/LLM failures propagate (fail closed).
- **API** (`src/arc/api/controllers.py`): `POST /tenants/{tenant_id}/intelligence/query`
  behind the existing `knowledge:read` permission (reasoning is a read-class
  operation, not a new capability); path-tenant consistency 403; 400 for
  empty query/missing body/limit outside 1-50; generic 500 on
  `EmbeddingError`/`LlmError` with no internals leaked.
- **Composition root** (`src/arc/app.py`): LLM provider wired through
  `build_llm_provider(get_llm_settings())`. Documented in `.env.example`
  (`LLM_PROVIDER=deterministic`, `LLM_MODEL=deterministic-local`).

### Tests (net +37)

- `tests/test_llm.py` (new): deterministic provider (deterministic, cites
  exactly the approved context, never echoes content, empty prompt rejected),
  settings defaults/env reading, empty provider fails closed, factory
  (deterministic built, unknown provider fails closed).
- `tests/test_intelligence_service.py` (new): `IntelligenceAnswer` domain
  validation; happy path preserves context/citations; no-context → LLM never
  invoked, answer `None`; prompt contains only content + citations (no tenant/
  principal/score/state); empty query and limit<1 rejected; embedding and LLM
  failures propagate with no partial answer; default provider deterministic.
- `tests/test_intelligence_api.py` (new): 401/403; happy path end-to-end over
  real PostgreSQL (create document → query → attributable answer + citations);
  no-context query → `answer: null`; cross-tenant query never leaks context;
  path-tenant mismatch 403; empty query/missing body/limit out of range 400;
  raw PII never reaches the response; LLM and embedding failures map to
  generic 500 (services restored after injection).

### Verification

- 392 tests pass (Docker + real PostgreSQL, freshly rebuilt `arc-arc:latest`
  image with the new code), 4 warnings, 0 failures.
- `ruff check` / `ruff format --check` clean; `docker compose config --quiet`
  exit 0; `git diff --check` clean; no secrets/conflict markers.
- Runtime smoke: rebuilt image imports `UnifiedIntelligenceService` and
  constructs the configured `DeterministicLlmProvider`.

### Merged to main

- Merged to `main`.

## Connector Provider Integrations (Merged)

**Branch:** `feat/connector-provider-integrations`
**Base:** `origin/main` @ `a5b892b`
**Scope:** Person C — Connectors. GitHub, Slack, and Linear provider
integrations (PRD §22, TRD §33, ADR-002) on top of the X-13 connector
foundation already on `main` (code-defined `ConnectorProvider` catalog,
`connector_configs`, `ConnectorService`, 38 tests).

### What changed

- **Schema** (`src/arc/db/schema.sql`): `connector_sync_records` audit
  table (id PK, tenant FK ON DELETE CASCADE, connector FK ON DELETE
  CASCADE, provider, status CHECK success/failed, items_fetched >= 0,
  error_kind, created_at) with a tenant index.
- **Domain** (`src/arc/domain/models.py`): `ConnectorSyncStatus`
  (success, failed) and `ConnectorSyncRecord` with validation (success
  records cannot carry an error_kind; failed records cannot report
  fetched items).
- **Repository** (`src/arc/repositories/connector_sync.py`):
  `PostgreSQLConnectorSyncRepository` implementing the
  `ConnectorSyncRepository` Protocol; every query is tenant-scoped at the
  SQL level.
- **Provider package** (`src/arc/services/connector_providers/`):
  - `base.py` — controlled `ProviderError` hierarchy (validation / auth /
    rate-limit / transport / response), `ProviderCredential` (repr masks
    the token), validated `ProviderRecord`/`ProviderFetchResult`,
    `ProviderAdapter` Protocol.
  - `settings.py` — `CONNECTOR_CREDENTIALS` JSON (tenant -> provider ->
    token) and `CONNECTOR_PROVIDER_MODE` (simulated | live); invalid
    configuration fails closed; credentials read lazily from the
    environment.
  - `github.py`, `slack.py`, `linear.py` — httpx adapters with
    code-defined endpoints only; the tenant-supplied target is validated
    before any request; responses are validated into typed records.
  - `fake.py` — deterministic controlled/fake clients (TRD §33) with
    failure injection for testing.
  - `registry.py` — static code-defined catalog; no runtime registration.
- **Service** (`src/arc/services/connector_sync.py`):
  `ConnectorSyncService` — tenant-scoped connector lookup -> adapter ->
  credential -> fetch -> Company Brain ingestion
  (`KnowledgeService.ingest_document`, INTERNAL_KNOWLEDGE, provenance
  `connector:{provider}:{source_id}`, through the existing PII boundary)
  -> success/failed audit record. Provider failures map to generic error
  kinds (`invalid_target`, `auth_failed`, `rate_limited`,
  `transport_error`, `invalid_provider_response`, `missing_credential`,
  `unsupported_provider`, `pii_guard_failed`); the API surfaces a single
  controlled error.
- **Authorization** (`src/arc/security/authorization.py`):
  `connector:create`, `connector:read`, `connector:sync` —
  PLATFORM_ADMINISTRATOR and COMPANY_ADMINISTRATOR: all three;
  OPERATIONS_USER: read + sync; EMPLOYEE: none. Default DENY.
- **API** (`src/arc/api/controllers.py`):
  `GET /tenants/{tenant_id}/connectors` (list),
  `POST /tenants/{tenant_id}/connectors` (400 invalid provider/name,
  409 duplicate), and
  `POST /tenants/{tenant_id}/connectors/{connector_id}/sync` (404 not
  found, 400 generic failure). The path tenant is validated against the
  trusted `TenantContext` (403 on mismatch); no credential material is
  ever accepted or returned.
- **Config**: composition-root wiring in `src/arc/app.py` (simulated mode
  default); `CONNECTOR_CREDENTIALS` and `CONNECTOR_PROVIDER_MODE`
  documented with safe placeholders in `.env.example` and passed through
  `docker-compose.yml`. `httpx>=0.28,<1.0` added as a runtime dependency
  (required by the live adapters); the broken `httpx2>=2.0,<3.0` dev
  entry removed.
- **Tests** (+99, total 434): `tests/test_connector_providers.py`
  (credential repr secrecy, fail-closed settings parsing, fake clients,
  real adapters via httpx MockTransport),
  `tests/test_connector_sync_domain.py`,
  `tests/test_connector_sync_repository.py` (real PG, cascade, SQL-level
  isolation), `tests/test_connector_sync_service.py` (failure kinds,
  no-secret invariants, real-PG PII sanitization before persistence),
  `tests/test_connector_api.py` (401/403, permission matrix,
  cross-tenant 404, path mismatch 403 with no-persistence proof, generic
  failures, sanitized knowledge ingestion). `tests/test_rbac.py` and
  `tests/test_api_surface.py` updated.

### Review response (security review)

- **Centralized RBAC**: `connector:create`/`connector:read`/`connector:sync`
  are integrated into the centralized permission matrix in
  `src/arc/security/authorization.py` with the explicit role mapping
  (PLATFORM_ADMIN/COMPANY_ADMIN: all three; OPERATIONS: read + sync;
  EMPLOYEE: none; default DENY). There is no connector-specific
  authorization system; the connector layer consumes the centralized
  `AuthorizationService` decision.
- **Credential boundary**: credentials are environment-injected
  (`CONNECTOR_CREDENTIALS`) and are never tenant-supplied, persisted,
  returned, logged, audited, or exposed through `repr`. Missing/invalid
  credentials fail closed before any provider request. Production OAuth,
  secret storage, rotation, and per-tenant provider identity are
  explicitly deferred.
- **Provider target allowlist (SSRF)**: every outbound request URL is
  validated against the approved endpoint allowlist
  (`connector_providers/targets.py`) before it is sent: `https` only,
  exact approved provider hosts (GitHub/Slack/Linear), no IP literals,
  no localhost, no private ranges, no cloud-metadata address, no
  userinfo. Redirects are not followed (`follow_redirects=False`).
- **PII boundary**: provider content passes through the existing
  `KnowledgeService` PII Guard before any knowledge persistence; PII
  Guard failure fails closed (no raw fallback, no persistence of that
  record, controlled failure, safe audit event).
- **Sync vs Company Brain boundary**: this PR is the upstream ingestion
  source (Option A). It does not establish the final knowledge identity,
  RAG indexing, or deduplication model; final deduplication/document
  identity is owned by the future Company Brain ingestion layer.
- **Audit minimization**: `connector_sync_records` store safe metadata
  only (tenant, connector, provider, status, item count, generic error
  kind); raw provider payloads, PII, and secrets never reach audit
  records.
- **Live-mode gate**: simulated mode is the default; live adapters are
  constructed only under an explicit `CONNECTOR_PROVIDER_MODE=live` and
  still require a credential and allowlisted target before any external
  request. A normal environment never makes unexpected external calls.

### Deferred (NOT part of this slice; no decisions changed)

- Production credential storage: only environment-based development
  placeholders exist; ADR-002 defers credential management.
- Live provider mode enablement: `CONNECTOR_PROVIDER_MODE=live` exists
  behind the same adapter interface but is NOT authorized by ADR-002;
  the default is the deterministic simulated mode.
- Sync deduplication: a re-sync currently creates additional knowledge
  documents (documented v1 decision).
- Additional providers (e.g. Google Drive, conditional per ADR-002),
  webhooks, observability, and the remaining Person C modules are future
  work.

### Verification

- 434 tests pass (Docker + real PostgreSQL), fresh and warm, 0 failures.
- `ruff check .`, `ruff format --check .`, `compileall -q src`,
  `docker compose config --quiet`, `git diff --check`, the conflict-marker
  scan, and the secret scan are all clean.

### Merged to main

- Merged to `main`.

## Webhooks — Inbound Event Ingestion Foundation (Merged)

**Branch:** `feat/webhooks-foundation`
**Base:** `origin/main` @ `95b36e6`
**Scope:** Person C — Webhooks. First TRD-ordered slice after AI Tools
(TRD §38): inbound-only webhook ingestion per PRD §16, TRD §16, ADR-001
webhook security boundary. Scope decisions confirmed with the module
owner before implementation: (1) INBOUND ONLY — no outbound delivery;
(2) machine senders authenticate via per-endpoint HMAC-SHA256 signatures
over `{timestamp}.{raw_body}` with a ±300s timestamp window; (3) slice-1
"processing" = validate → store → record (no Unified Intelligence
triggering yet).

### What changed

- **Domain** (`src/arc/domain/models.py`): `WebhookEventStatus` (single
  terminal state `received`; new states require approved decisions) and
  `WebhookEvent` — metadata-only record (id, tenant_id, endpoint_id,
  event_id, event_type, status, payload_size_bytes, created_at) with
  fail-closed validation. Raw external payloads are NEVER persisted
  (untrusted input, possible PII; no approved payload-storage decision).
- **Schema** (`src/arc/db/schema.sql`): idempotent `webhook_events`
  table (tenant FK ON DELETE CASCADE, status CHECK, payload size CHECK,
  UNIQUE `(tenant_id, event_id)` duplicate-handling pair, tenant index).
- **Configuration** (`src/arc/services/webhook_config.py`):
  `WEBHOOK_INGESTION_ENDPOINTS` JSON (endpoint id -> {tenant_id,
  secret}); secrets >= 16 chars; malformed config fails closed; secrets
  masked in repr/str; lazy env reads (same contract class as
  `CONNECTOR_CREDENTIALS`). Documented in `.env.example`, passed through
  `docker-compose.yml`.
- **Repository** (`src/arc/repositories/webhook_events.py` +
  Protocol in `src/arc/repositories/__init__.py`):
  `PostgreSQLWebhookEventRepository` — create / get_by_event_id /
  list_for_tenant; EVERY query tenant-scoped at SQL level;
  `DuplicateKeyError` on uniqueness-pair conflict.
- **Service** (`src/arc/services/webhook_ingestion.py`):
  `WebhookIngestionService` — endpoint resolution (tenant binding from
  trusted config only), constant-time HMAC verification
  (`compute_signature`), timestamp-window replay resistance, body-size +
  JSON-envelope validation AFTER authentication, idempotent duplicates
  (re-delivery resolves to original record, `duplicate=true`). Uniform
  `WebhookAuthenticationError` for all auth failures (senders cannot
  enumerate endpoints); controlled `WebhookValidationError` (400);
  secrets/payload content never logged, returned, or persisted.
- **Authorization** (`src/arc/security/authorization.py`): `webhook:read`
  — PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER;
  EMPLOYEE none; default DENY. The ingestion endpoint is deliberately
  NOT RBAC-gated (machine senders hold no Arc identity); documented in
  the matrix docstring.
- **API** (`src/arc/api/controllers.py`): `POST /webhooks/{endpoint_id}/events`
  (uniform 401 on all auth failures; idempotent 200 with `duplicate`
  flag; 400 validation) and
  `GET /tenants/{tenant_id}/webhooks/events` behind
  `require_tenant_permission(WEBHOOK_READ)` + path-consistency 403.
  Responses expose envelope metadata only.
- **Wiring** (`src/arc/app.py`): repository + service registered at the
  composition root.
- **Tests** (+71, total 730): `tests/test_webhook_domain_config.py`,
  `tests/test_webhook_ingestion_service.py` (fake doubles),
  `tests/test_webhook_repository.py` (real PostgreSQL),
  `tests/test_webhook_api.py` (indistinguishable-401 proofs,
  RBAC matrix, cross-tenant isolation, idempotent duplicates,
  secret/payload-leak absence). `tests/test_rbac.py` and
  `tests/test_api_surface.py` updated additively.

### Deferred (NOT part of this slice)

- Triggering downstream processing (Unified Intelligence entry point is
  another owner's contract).
- Outbound webhook delivery, retry strategy finalization (TRD §37),
  replay nonce storage, per-endpoint CRUD APIs, secret rotation, secure
  secret storage, multiple endpoints per tenant.

### Verification

- 730 tests pass (Docker + real PostgreSQL), fresh AND warm database,
  0 failures; verified against a throwaway database so the shared dev
  volume was untouched.
- `ruff check .` and `ruff format --check .` clean.
- Local environment note: this developer's persistent compose volume
  contains an ORPHANED `webhook_events` table from an earlier
  uncommitted experiment (80 rows; columns `payload jsonb`, `signature`,
  `attempts` — not present anywhere in the repository). `CREATE TABLE IF
  NOT EXISTS` skips recreation, so tests hitting THAT volume fail until
  the table is dropped by its owner. CI is unaffected (fresh DB every
  run). Dropping requires the data owner's decision (destructive op).

### Merged to main

- Merged to `main`.
## Observability — Foundation Slice (Merged)

**Branch:** `feat/observability-foundation`
**Base:** `origin/main` @ `95b36e6`
**Scope:** Person C — Observability. First TRD-ordered slice after
Webhooks (TRD §38): usage-based and operational observability per PRD
§17, TRD §17/§28/§31, ADR-001 Operational Considerations. Architecture
decisions confirmed with Bala/Joe before implementation: observability
is an AGGREGATION/READ layer, never a second source of truth; stdlib
logging + PostgreSQL aggregation only (no OpenTelemetry/Prometheus);
success-gated path-param tenant attribution; best-effort telemetry
writes; strictly tenant-agnostic platform summary; `/health` unchanged.
Deferred: agent executions, LLM token usage, retrieval/embedding
instrumentation, incident lifecycle, human-intervention and automated-
action counters (producers not implemented / other owners).

### What changed

- **Domain** (`src/arc/domain/models.py`): `ApiRequestRecord` — metadata-
  only HTTP telemetry owned by this layer (id, nullable tenant_id,
  request_id correlation ID, method allowlist, route TEMPLATE, status
  code bounds, non-negative duration_ms, coarse error_kind) with
  fail-closed validation; query strings/raw paths/bodies/prompts/
  secrets are structurally excluded. Typed read-models:
  `HttpUsageMetrics`, `ToolExecutionActivityMetrics`,
  `ConnectorSyncActivityMetrics`, `WebhookEventActivityMetrics`.
- **Schema** (`src/arc/db/schema.sql`): idempotent `api_request_records`
  table (nullable tenant FK ON DELETE CASCADE, status/duration CHECKs,
  tenant + created_at indexes). NO generic event/usage table: tool,
  connector, and webhook records remain authoritative in their own
  tables and are aggregated IN PLACE at read time.
- **Repository** (`src/arc/repositories/observability.py` + Protocol in
  `src/arc/repositories/__init__.py`): one write path plus SQL-level
  aggregates (`COUNT/FILTER/AVG/percentile_cont`) against the
  authoritative tables; every tenant-scoped query enforces tenant_id in
  SQL; `tenant_id=NULL` selects the PLATFORM view (no GROUP BY tenant
  ever leaves the module); webhook source detected via `to_regclass` —
  while PR #34 is unmerged the source reports `available=false` WITHOUT
  duplication or fabrication (temporary sequencing behavior;
  aggregation consumes the real table automatically once it exists).
- **Service** (`src/arc/services/observability.py`):
  `ObservabilityService` — BEST-EFFORT telemetry writes (persistence
  failure is logged safely and dropped; never fails a business request),
  windowed (1–168h) tenant usage summary assembly, tenant-agnostic
  platform summary, component health via EXISTING public factories only
  (database SELECT 1, LLM provider constructibility, embeddings
  constructibility) reporting status labels without configuration
  leakage. Webhook-config component joins when PR #34 merges.
- **Correlation middleware**
  (`src/arc/api/middleware.py`, `src/arc/api/correlation.py`): pure-ASGI;
  mints a UUID4 canonical HTTP correlation ID per request (ContextVar
  for logging), returns it as `X-Request-ID` (including handled errors),
  measures monotonic duration, records AFTER response completion with
  SUCCESS-GATED PATH-PARAM attribution: tenant label applied ONLY when an
  authenticated tenant route completed <400; failed/unauthorized/public
  requests store NULL. Attribution is telemetry bookkeeping and NEVER
  establishes identity or authorization. Route templates stored, never
  raw paths/query strings.
- **Structured logging** (`src/arc/observability_logging.py`): stdlib
  logging configured once at startup (`LOG_LEVEL`, default INFO);
  correlation-ID filter stamps every record (`request_id=...`);
  emission points carry safe metadata only (method/route/status/
  duration/coarse error class) per TRD §28 forbidden-content list.
- **RBAC** (`src/arc/security/authorization.py`, additive):
  `observability:read` → PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR,
  OPERATIONS_USER (tenant-scoped summaries);
  `observability:platform_read` → PLATFORM_ADMINISTRATOR only
  (tenant-agnostic platform summary + component health). EMPLOYEE none;
  default DENY; no second RBAC system.
- **API** (`src/arc/api/controllers.py`):
  `GET /tenants/{tenant_id}/observability/usage-summary` behind
  `require_tenant_permission(OBSERVABILITY_READ)` + path-consistency 403;
  `GET /platform/observability/summary` and `GET /observability/health`
  behind `require_permission(OBSERVABILITY_PLATFORM_READ)`. Responses
  contain numeric aggregates only — never raw rows, input/output
  summaries, prompts, answers, payloads, credentials, or per-tenant
  breakdowns at platform scope.
- **Wiring** (`src/arc/app.py`, `src/arc/main.py`): repository+service at
  composition root; middleware mounted with lazy service resolution so
  requests stay correlated (X-Request-ID) even before startup completes.
- **Config**: `LOG_LEVEL` documented in `.env.example`, passed through
  `docker-compose.yml`.
- **Tests** (+66 net): `tests/test_observability_domain.py`,
  `_repository.py` (real PostgreSQL: round-trip, NULL-tenant rows,
  SQL isolation across all aggregates, cascade, aggregation math incl.
  p95/error-rate, time windows, webhook absent-vs-present), `_service.py`
  (best-effort write semantics, assembly, health probes without detail
  leakage), `_api.py` (401/403 matrix, cross-tenant leak-proofing,
  platform payload contains no tenant identifiers/lists, correlation IDs
  unique and present on 401/404, success-only attribution proofs,
  query-string exclusion, telemetry-failure business-continuity).
  `tests/test_rbac.py` and `tests/test_api_surface.py` updated additively.

### What was NOT changed

- Owner-controlled implementations untouched: intelligence, LLM,
  embeddings, retrieval, tools, connector providers/sync, webhook
  ingestion/config (not on main), JWT/security models/settings, PII,
  skills, knowledge. `IntelligenceAnswer.request_id` semantics preserved
  (middleware correlation ID documented as distinct from future Agent
  execution IDs).
- No incident domain, no agent-execution producers, no fabricated token
  usage, no new telemetry dependencies, no duplicate webhook source.

### Verification

- Fresh throwaway database: **734 tests passed**, 0 failures.
- Warm persistent database: **733 passed, 1 skipped** (the
  webhook-source-absent test self-skips only where a local
  `webhook_events` table exists; CI/fresh runs exercise it).
- `ruff check .`, `ruff format --check .`, `compileall -q src tests`,
  `docker compose config --quiet`, `git diff --check`, conflict-marker
  scan, secret scan: all clean. Image rebuilt before verification runs.

### Merged to main

- Merged to `main`.
## Company Brain — Document Identity & Re-ingestion (Merged)

**Branch:** `feat/company-brain-document-identity`
**Base:** `origin/main` @ `95b36e6`
**Scope:** Person A — Company Brain primary. Defines logical document
identity and re-ingestion/deduplication semantics per **ADR-003**
(`docs/architecture/decisions/ADR-003-company-brain-document-identity-and-re-ingestion.md`),
resolving the deferral recorded by the connector slice (repeated
synchronization previously created duplicate logical documents).

### What changed

- **Identity (ADR-003):** a document's logical identity is
  `(tenant_id, source, external_id)`. New nullable `external_id`
  column on `knowledge_documents` plus a partial unique index
  (`WHERE external_id IS NOT NULL`) — DB-enforced, tenant-participating,
  idempotent under bootstrap, safe against pre-existing rows. Documents
  ingested without an external identity keep the original create-always
  behavior.
- **Domain** (`src/arc/domain/models.py`): `KnowledgeDocument.external_id`
  with fail-closed validation; docstring updated to define `version`
  progression (starts at 1, +1 per accepted content change; no revision rows).
- **Service** (`src/arc/services/knowledge.py`): `ingest_document(...,
  external_id=None)` — sanitization ALWAYS runs first (including on
  re-delivery); identical sanitized content → idempotent return of the
  existing document (no version bump/chunk churn); changed content → new
  chunks/embeddings prepared in memory BEFORE any write (embedding failure
  aborts), then version+1 content update and whole chunk-set replacement in
  one transaction; concurrent first delivery loses the insert race at the
  identity index and re-resolves through the same logic.
- **Repository** (`src/arc/repositories/knowledge.py`,
  Protocol in `src/arc/repositories/__init__.py`): inserts carry
  `external_id`; new `get_by_external_id` (strictly tenant+source scoped)
  and `update_document_with_chunks` (UPDATE + chunk DELETE + chunk INSERT
  in ONE transaction; any failure rolls back to the prior version and its
  complete old index).
- **Connectors** (`src/arc/services/connector_sync.py`): sync binds
  `external_id = "{provider}:{record.source_id}"`; re-syncing one source
  record now resolves to ONE tenant-scoped document.
- **API**: unchanged (no new endpoints/permissions; manual ingestion has
  no external identity by design).

### Tests

- Service-level: create-v1, idempotent redelivery (guard invoked every
  time), changed-content version bump with chunk replacement,
  embedding-failure aborts before write, PII failure fails closed on
  re-ingestion, comparison on SANITIZED text, missing external_id legacy
  behavior, cross-tenant identity independence, invalid external_id
  rejected, lost-race recovery to the winner.
- Repository-level (real PostgreSQL): identity index enforcement, NULL
  exclusion, cross-tenant same-identity allowance, resolution scoping,
  atomic chunk replacement, mid-transaction failure rollback preserving
  prior version + chunks, concurrent first delivery creating exactly one
  row end-to-end through `KnowledgeService`.
- Connector-level: provider-scoped `external_id` binding; stable identity
  across repeated syncs.

### Security

Tenant isolation preserved (identity lookups tenant-scoped; cross-tenant
negative tests). PII-before-persistence preserved on every path including
re-ingestion. Approved Context / `approved_search` / RBAC untouched.

### Deferred (unchanged)

Retroactive deduplication/cleanup of pre-existing duplicate rows;
production embedding providers; hybrid retrieval/reranking.

## Company Brain — Legacy Duplicate Archival Lifecycle (Merged)

**Branch:** `feat/company-brain-legacy-archival`
**Base:** `origin/main` @ `2c425a6`
**Scope:** Person A — Company Brain lifecycle completion. Implements the
retroactive cleanup deferred by ADR-003/PR #38: archive-only removal of
pre-identity duplicate documents from normal retrieval surfaces.

### Semantics

- **Candidate predicate (exact, narrow):** `external_id IS NULL
  AND status = 'active' AND provenance LIKE 'connector:%'`. Safe because
  repository history establishes that legacy connector ingestion built
  provenance deterministically as `connector:{provider}:{source_id}`
  (`connector_sync.py:144`) — the same binding ADR-003 later formalized
  as `external_id`.
- **Grouping key:** `(tenant_id, source, provenance)`; grouping never
  spans tenants. Winner = newest `created_at`, tie-break smallest `id`;
  winner stays ACTIVE.
- **Archive-only:** losers flip to `status='archived'`. No deletion of
  documents/chunks; no content mutation; no external_id fabrication;
  chunks are retained but excluded from retrieval.
- **Retrieval lifecycle:** archived documents excluded at the persistence
  boundary — chunk search joins documents with `d.status='active'`
  (covers /knowledge/search, approved_search, Unified Intelligence
  candidate generation); `list_for_tenant` filters active; explicit
  `get_by_id` still recovers archived rows for audit/recovery.
- **Dry-run mandatory:** `KnowledgeService.archive_legacy_duplicates(
  dry_run=True)` returns a content-free candidate report (groups,
  winners, would-archive ids/metadata, guarantees) with ZERO mutations;
  execution requires explicit `dry_run=False` and re-checks the exact
  predicate inside the single atomic UPDATE statement.

### Residual caveat (documented, not silently widened)

`provenance LIKE 'connector:%'` is not cryptographic proof: a pre-#38
MANUAL document could carry connector-like provenance. Mitigations:
narrow predicate, archive-only reversibility, dry-run verification,
exact-predicate re-check, deterministic winner rule.

### Recovery semantics (per review)

Archival is a STATUS-ONLY transition (`active` → `archived`) and is
therefore technically reversible at the data level. There is currently
NO application-level restore/unarchive operation: recovery of an
archived document is a controlled MANUAL DBA action (flipping
`status` back to `'active'` via SQL). An application-level restore
API/service is a deferred future follow-up, not an existing
capability.

### Idempotency / concurrency

Reruns archive nothing (predicate excludes archived). One-time admin/
maintenance operation invoked deliberately per environment; concurrent
ingestion during the window can add fresh duplicates which a rerun then
reconciles. No background jobs introduced.

### Tests

Repository (real PostgreSQL): group discovery, winner/tie-break,
cross-tenant independence, tenant-scoped sweep leaving other tenants
untouched, NULL-vs-identified exclusion, non-connector provenance
exclusion, archived-rows exclusion, idempotency, chunks retained but
excluded from search, get_by_id recovery, approved_search + Unified
Intelligence regression proving archived knowledge cannot re-enter RAG.
Service: dry-run zero-mutation report shape, metadata-only payload,
explicit execution count, idempotent rerun reporting.

### Deferred

Production embedding providers; hybrid retrieval/reranking; optional
hard-deletion policy (requires separate team decision).

### Verification

See PR description (Docker + real PostgreSQL suite, ruff, format, compose).

### Merged to main

- Merged to `main`.

## Webhooks — Ingestion Body-Cap Hardening (Merged)

**Branch:** `fix/webhook-ingestion-body-cap`
**Base:** `origin/main` @ `bc9b436`
**Scope:** Bharath G — Webhooks. Narrow production-readiness follow-up
from Bala's APPROVED PR #34 review: `POST /webhooks/{endpoint_id}/events`
previously buffered the complete unauthenticated body (`await
request.body()`) before any size check. Answers recorded by Bala/Joe:
keep the 400 contract; oversize may reject before HMAC/timestamp
verification; stop consuming past the cap (no drain); rate limiting is a
separate deferred item.

### What changed

- `src/arc/api/controllers.py` only (+ private helper): new
  `_read_capped_body(request, max_bytes)` — Content-Length serves as an
  EARLY-REJECTION FAST PATH only (client-controlled, never enforcement);
  otherwise the body streams via `request.stream()` with a hard
  cumulative cap at `MAX_BODY_BYTES` (65536). Reads STOP as soon as the
  cap trips — the remaining stream is intentionally not drained.
  Bodies ≤ cap are returned byte-exact to `WebhookIngestionService`, so
  HMAC-over-exact-received-body semantics and all authentication,
  tenant-binding, idempotency, and audit behavior are unchanged. The
  oversize rejection keeps the EXISTING 400 response/message, is
  endpoint-independent (no enumeration signal), and deliberately
  precedes authentication (an aborted read cannot be verified).
- Stack verification: Starlette `Request.stream()` consumes raw chunks;
  Uvicorn pauses socket reads at its own 64 KB high-water mark
  (`flow_control.HIGH_WATER_LIMIT`) and closes a connection whose body
  was left unconsumed after the response — so stopping mid-stream adds
  no unbounded buffering and no middleware/ASGI machinery was needed.
- `tests/test_webhook_api.py` (+10): exact-cap success (valid JSON
  envelope sized to precisely 65536), oversize→400 without credentials,
  endpoint-independent identical 400 bodies, no payload echo, chunked
  within/over cap, misleading-large CL fast path, direct stop-consumption
  proof against a fabricated `receive()` (reader must never request a
  chunk past the cap), exact-cap stream-reader round-trip. Service-level
  `MAX_BODY_BYTES` validation retained as defense-in-depth.

### Verification

- Fresh throwaway DB: **880 passed, 1 skipped**. Warm DB: **880 passed,
  1 skipped** (skip = pre-existing observability absent-source guard).
- ruff check/format clean; compileall clean; compose config valid;
  git diff --check / conflict-marker / secret scans clean.

## CI Baseline (Established)

**Branch:** `chore/ci-github-actions` (merged to `main` via PR #23)

- Added `.github/workflows/ci.yml` (GitHub Actions, `ubuntu-latest`).
- Triggers: pushes to `main` and pull requests targeting `main`.
- Checks use the existing Docker Compose environment:
  - `docker compose build arc`
  - `docker compose run --rm arc ruff check .`
  - `docker compose run --rm arc ruff format --check .`
  - `docker compose run --rm arc python -m pytest -q`
- Environment values are development/test placeholders only; no real
  credentials.
- The repo-wide lint/format gate passes on current `main`, verified locally
  against a freshly rebuilt application image.
- GitHub Actions CI is active on `main`.

## Human Intervention — Approval-Gate V1 Foundation (Merged)

**PR #50** — merged to `main` (commit `aa409c7`).

Surgical reintroduction of the reviewed approval-gate from `84db40b` (PR #46,
reverted by PR #48). Preserved all PR #47 PII guard work unchanged.

**What this provides**:

- `HumanApprovalService` with lifecycle management (create, decide, consume)
- `PostgreSQLApprovalRequestRepository` with tenant-scoped SQL operations
- `ApprovalRequest` and `ApprovalStatus` domain models
- `approval_requests` database table with race-safe unique partial index
- `REQUIRE_HUMAN_APPROVAL` policy in `ToolExecutionService`:
  - Creation path: records pending approval, fails closed
  - Consumption path: atomically consumes approved request, executes handler
- Approval endpoints: list, read, decide
- `APPROVAL_READ` / `APPROVAL_DECIDE` RBAC permissions
- Canonical digest: `json.dumps(validated.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`
- Self-approval prevention: `requester != approver`
- Single-use consumption: atomic transition `approved -> consumed`
- Lazy expiry: `pending` rows past TTL read as `EXPIRED`

**Files created**: `approvals.py` (service), `repositories/approvals.py`, 4 test files
**Files modified**: `controllers.py`, `schema.sql`, `models.py`, `domain/__init__.py`, `repositories/__init__.py`, `authorization.py`, `tools.py`, `app.py`, `test_api_surface.py`, `test_rbac.py`, `test_tool_service.py`

**Preserved unchanged**: PII guard (`skills.py`, `app.py` PII wiring, `test_skill_pii_guard.py`, `test_skill_service.py` PII fixtures), ADR-005 (already on main), PR #45 Skills Engine

## ADR-007 Production Embedding Architecture (Merged)

**Commits**: `ca44f9c`, `c4d535a` on `main`.

Reviewed and approved production embedding architecture decision record.
Resolved review findings (gateway, backup, re-embed wording).
Located at `docs/architecture/decisions/ADR-007-production-embedding-provider-and-vector-representation.md`.

## Approval Observability Slice (PR #51 — Merged)

**PR #51** — merged to `main` (commit `e7b0b22`).

Authorized by ADR-005 §line 339 ("approval-specific metrics (later observability slice)").
Observability principle: aggregation/read-only, NOT a second source of truth.

## Frontend Foundation + Security Hardening (PR #52 — Merged)

**PR #52** — merged to `main` (commit `c0e8dde`).

Joe's original frontend foundation (`7dcc335`), Bala's conflict resolution (`f66e720`), Bala's formatting (`5110834`), and Bharath's security hardening (`b33b889`).
Provides the full frontend product surface with authentication, tenant context, routing, and focused security hardening (JWT algorithm allowlist, principal.claims restriction, clipboard error handling, duplicate-submit protection, .env protection, Vite proxy documentation, invalid date fallback).

## Production Embedding Provider + 64→1536 Migration (PR #53 — Merged)

**PR #53** — merged to `main` (commit `4daa5a7`).

Implements ADR-007: production OpenAI-compatible embedding provider with
gateway-routable `base_url`, `EMBEDDING_DIMENSIONS` updated to 1536,
and the idempotent `migrate_embeddings.py` migration script.

## Secure RAG Source-Type Filtering (PR #54 — Merged)

**PR #54** — merged to `main` (commit `f9de5a9`).

Adds optional `source_type` filtering to the knowledge search endpoint.
Uses existing `KnowledgeSource` enum; invalid values return HTTP 400.
Preserves tenant isolation, active-document filtering, and ApprovedContext contracts.
Repository, service, API, and ApprovedContext tests added.


## Issue #58 — Tenant Onboarding Owner Auto-Assignment (Implemented, Uncommitted)

**Issue:** GitHub #58 — "POST /tenants does not create OWNER membership for creator"
**Resolution:** Option A — auto-create OWNER membership in controller via new atomic service method.
**Approved by:** Joe (product) + Bala (architecture). No schema or auth-model changes.

### Root cause

`POST /tenants` created the tenant row but did NOT create a membership for the
authenticated creator. The creator could not list or access the tenant they just
created. The dev membership endpoint was the only way to add users, which is
inconvenient for the creator.

### What changed (7 files)

- **`src/arc/db/connection.py`**: New `create_tenant_with_owner(tenant, membership)` —
  wraps both INSERT statements in a single `async with self.transaction() as conn:`
  for atomicity. Both inserts succeed or both roll back.
- **`src/arc/repositories/tenancy.py`**: New `create_with_owner(tenant, membership)`
  on `PostgreSQLTenantRepository` — delegates to the atomic DB method.
- **`src/arc/services/domain.py`**: New `create_tenant_with_owner(tenant, user_id)`
  on `TenantService` — creates `Membership` with `UserRole.OWNER`, calls
  `tenant_repo.create_with_owner()`.
- **`src/arc/api/controllers.py`**: `create_tenant` endpoint now calls
  `tenant_service.create_tenant_with_owner(tenant, principal.user_id)` and captures
  the `principal` parameter (renamed from `_`).
- **`src/arc/main.py`**: Added `DuplicateKeyError` exception handler returning
  409 Conflict JSON response for race-condition idempotency.
- **`tests/test_rbac.py`**: Updated `test_platform_administrator_can_create_tenant`
  to create the user first (FK satisfied) then create tenant.
- **`tests/test_tenant_onboarding.py`** (new, 6 tests): Owner membership assignment,
  no duplicate membership, permission required, duplicate-tenant-ID 409, database-level
  atomicity (tenant rollback on membership FK failure), and tenant isolation after creation.

### What was NOT changed

- No schema changes (no new tables, no new columns).
- No auth-model changes (UserRole for membership, ApplicationRole for RBAC — independent).
- Dev membership endpoint (`src/arc/api/dev_controllers.py`) unchanged — still available
  for adding other users/roles.
- No changes to controllers outside the `create_tenant` endpoint.

### Verification

- **1228 tests pass** (Docker + real PostgreSQL), 1 skipped (pre-existing
  observability absent-source guard), 0 failures.
- `ruff check` passes on all changed files.
- Single-transaction tenant+membership insert; FK constraint validated;
  race-condition idempotency via DuplicateKeyError → 409; database-level
  test proves tenant rollback when membership INSERT fails (FK violation
  on nonexistent user).

## Issue #60 — RBAC Role Independence Clarification (Implemented)

**Issue:** GitHub #60 — "clarify(auth): define provisioning and mapping between application RBAC roles and tenant membership roles"
**Resolution:** Option B — completely independent role systems, no automatic mapping.
**ADR:** ADR-008 (`docs/architecture/decisions/ADR-008-tenant-membership-and-application-rbac-roles.md`)

### Decision

UserRole (tenant membership: OWNER/MEMBER/VIEWER) and ApplicationRole
(platform RBAC: PLATFORM_ADMINISTRATOR/COMPANY_ADMINISTRATOR/OPERATIONS_USER/EMPLOYEE)
are and must remain completely independent role systems.

- No automatic mapping exists between them.
- Membership in a tenant does NOT grant application-level permissions.
- ApplicationRole assignment does NOT grant tenant-level access.
- Both systems must be satisfied independently for full access.

### What changed

- **ADR-008** created at `docs/architecture/decisions/ADR-008-tenant-membership-and-application-rbac-roles.md`.
  Formalizes the role-system relationship, provisioning model, default
  behavior, assignment authority, multi-tenant behavior, and compatibility
  with existing architecture.
- **CURRENT_STATE.md** updated with Issue #60 resolution and ADR-008 reference.

### What was NOT changed

- No code changes. The architecture already implements independent role systems.
- No schema changes. Both systems use existing storage mechanisms.
- No test changes. Existing tests already verify role independence.
- No permission matrix changes. The existing matrix is correct.
- No service or controller changes. The authorization flow is correct.

### Verification

- Existing tests verify independence:
  - `test_application_roles_are_independent_of_membership_roles`
  - `test_membership_role_never_grants_application_permissions`
  - `test_permission_matrix` (all four ApplicationRoles)
  - `test_tenant_creation_assigns_owner_membership` (OWNER created, no ApplicationRole change)
  - `test_tenant_isolation_after_creation` (cross-tenant isolation maintained)
- No regressions expected (documentation-only change).

## In Progress

### GitHub / Engineering Workflow

- Complete verification of Joe and Bharath repository access.
- Complete X-6 Linear acceptance criteria.

### AI Development Setup

- Finalize AI coding-agent workflow.
- Configure OmniRoute.
- Configure OpenRouter.
- Define model roles.
- Benchmark candidate models.
- Establish AI context workflow.
- Verify AI development safety boundaries.

### Reproducible Development Environment

- Docker baseline — established (merged).
- Dev Container baseline — established (merged).
- Compose — established (merged).
- CI environment — established.
- Windows verification — complete (Docker build, ruff, format, pytest all pass).
- macOS verification — pending (Joe to rebuild Docker image and verify inside container).

## Product Work

Joe is developing the product roadmap and detailed product/module definition.

Product:

**Arc**

Domain:

**IT Services**

The product is intended to combine the 12 interconnected enterprise capabilities defined by the approved project roadmap.

Detailed requirements are not considered finalized until approved and documented.

## Platform Work

Bharath is responsible for the reproducible local environment and CI/platform baseline.

This includes:

- Docker
- Dev Container
- Compose
- CI
- Cross-platform verification

## Engineering / AI Work

Bala is responsible for:

- GitHub engineering workflow
- Repository conventions
- AI development setup
- AI context system
- Security baseline
- ADR process
- Architecture coordination

## Next

1. Open PR for Issue #60 RBAC role independence clarification (branch: `fix/issue-60-rbac-provisioning`).
2. Coordinate the next Bala Foundation issue with Joe and Bharath.
3. Continue the AI development setup.
4. Complete Foundation cross-platform verification (macOS — Joe's responsibility).
5. Connect GitHub with Linear.
6. Benchmark candidate AI models.
7. Conduct the final Foundation review.
8. Begin product implementation only after Foundation acceptance.

## Blocked / Waiting

### Product Definition

Detailed product requirements and roadmap dependencies are still being finalized.

Owner:

Joe

### Environment Baseline

Final runtime/environment configuration is being established.

Owner:

Bharath

### CI

The CI baseline (`.github/workflows/ci.yml`) has been established and
merged to `main` (PR #23). CI is active and passing on `main`.
Remaining Foundation cross-platform verification is macOS.

Owner:

Bharath

## Known Risks

- Premature architecture decisions before product requirements are finalized.
- AI-generated code being accepted without review.
- Secrets entering AI prompts or Git history.
- Inconsistent Windows/macOS environments.
- Documentation becoming stale.
- Unclear ownership between team members.
- Overengineering infrastructure before demonstrating the need.
- Treating GitHub branch-protection policy as technically enforced when the current plan does not enforce the ruleset.
- Membership provisioning is development-only (no public endpoint) and is now protected by X-11 authentication + the `membership:create` permission.

## Foundation Completion Criteria

The Foundation Phase is complete only when all three developers can independently:

```text
Clone
  ↓
Configure
  ↓
Start
  ↓
Test
  ↓
Lint
  ↓
Use the approved AI development workflow
  ↓
Create a branch
  ↓
Commit
  ↓
Push
  ↓
Open Pull Request
  ↓
Pass CI
  ↓
Receive review
  ↓
Merge
```

Only after this gate should normal product implementation begin.

