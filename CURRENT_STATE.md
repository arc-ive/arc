# Arc — Current State

Last Updated:

2026-08-19

Current Phase:

Foundation Phase — X-10, X-11, and X-13 merged; ADR-002 merged; CI baseline established (PR under review)

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

## CI Baseline (Established — PR under review)

**Branch:** `chore/ci-github-actions`

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
- Remaining: GitHub-side CI verification after review/merge.

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
- CI environment — established (PR under review).
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

1. **Review and merge the CI baseline** (chore/ci-github-actions): GitHub Actions workflow + state update; human review, PR, and merge required.
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

The CI baseline (`.github/workflows/ci.yml`) has been established on
`chore/ci-github-actions` and is pending review/merge. Remaining Foundation
verification is cross-platform (Windows/macOS).

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

