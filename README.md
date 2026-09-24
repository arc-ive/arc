# Arc

> Enterprise multi-tenant AI platform for IT Services organizations.

## Project Status

**Foundation — ADR-001 through ADR-013 accepted and implemented; QA Phases 0–4 merged (`41f32fd`)**

Arc has completed tenant membership boundary enforcement (X-10), application RBAC (X-11), and the ADR-009–013 slices (tenant-scoped membership administration, observability attribution, tenant suspension, self-scoped approval reads, external actions). Browser E2E (Playwright, Chromium) and a CI `e2e` quality gate are merged. CI runs on PRs but is not a required check. The team continues product implementation under the approved ADRs. See `CURRENT_STATE.md` for the current engineering state.

## Domain

**IT Services**

## Team

- Bala — Engineering + AI Lead
- Joe — Product + Roadmap Lead
- Bharath — Platform + DevOps Lead

## Foundation Goals

The Foundation Phase aims to establish:

- Reproducible development environments
- A controlled GitHub workflow
- Pull request and CI quality gates
- Durable project and AI context
- Architecture decision records
- Security and secret-handling rules
- Product and requirements documentation
- A standardized AI-assisted development workflow

## Repository Structure

```text
.github/          GitHub workflows, templates and repository configuration
.devcontainer/    Reproducible development container configuration
docs/             Product, requirements, architecture and operational documentation
scripts/          Developer and automation scripts
src/              Application source code
tests/            Shared test infrastructure
```

Additional application directories will be introduced when the agreed technical architecture requires them.

## Source of Truth

GitHub is the canonical source for:

- Source code
- Engineering documentation
- Architecture decisions
- AI project context
- Security rules
- Development conventions

Linear is used for:

- Work tracking
- Issues
- Cycles
- Priorities
- Roadmap execution

AI tools are development aids. They do not replace the repository's authoritative documentation.

## Quick Start (fresh clone)

```powershell
# 1. Clone and configure environment (safe development defaults)
cp .env.example .env

# 2. Start PostgreSQL + pgvector and the backend (schema is
#    provisioned automatically from src/arc/db/schema.sql on first
#    startup; restarts are idempotent and preserve data)
docker compose up --build -d

# 3. Verify health
curl http://localhost:8000/health
# {"status":"ok"}

# 4. Start the frontend (requires Node 24)
cd frontend
npm install
npm run dev
# http://localhost:5173
```

Fresh database provisioning is exercised by CI (``schema-bootstrap``
job) and covered by ``tests/test_schema_bootstrap.py``.

## Development Status

X-10 (tenant membership boundary), X-11 (application RBAC), and the ADR-009–013 architecture slices are implemented and verified. Browser E2E coverage (QA Phases 0–4) is merged with a CI quality gate.

See `CURRENT_STATE.md` for the current engineering state.