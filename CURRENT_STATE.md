# Arc — Current State

Last Updated:

2026-08-20

Current Phase:

Foundation Phase — X-10, X-11, and X-13 merged; ADR-002 merged; CI baseline established; Company Brain — Knowledge Storage & Ingestion Foundation implemented (pending review/merge)

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

## Company Brain — Knowledge Storage & Ingestion Foundation (Implemented — pending review)

**Branch:** `feat/company-brain-foundation`
**Base:** `origin/main` (reconciled with current main)
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

### Pending

- Human review of the PR; merge into `main`.

## AI Tools — AI Tools Foundation (Implemented — pending review)

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

### Pending

- Human review of PR #31; merge into `main`.

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
- Windows verification.
- macOS verification.

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

1. **Review and merge Company Brain — Knowledge Storage & Ingestion Foundation** (feat/company-brain-foundation): implemented, committed, and pushed; human review and merge required.
2. Complete X-6 verification and close the Linear issue.
3. Coordinate the next Bala Foundation issue with Joe and Bharath.
4. Continue the AI development setup.
5. Complete Foundation cross-platform verification (Windows/macOS).
6. Connect GitHub with Linear.
7. Benchmark candidate AI models.
8. Conduct the final Foundation review.
9. Begin product implementation only after Foundation acceptance.

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
merged to `main` (PR #23). Remaining Foundation verification is
cross-platform (Windows/macOS).

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

