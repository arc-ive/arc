# ARC QA Inventory (Phase 0 — Discovery)

- **Audited SHA:** `a15e681` (`origin/main`, branch `main`, clean tree)
- **Method:** source code as truth. No code, tests, or config modified.
- Backend: FastAPI (`src/arc/api`, `src/arc/services`), asyncpg → PostgreSQL + pgvector (`pgvector/pg17` image), single DDL file `src/arc/db/schema.sql` (20 tables) applied idempotently by `ArcDatabase.ensure_schema()` on startup; no Alembic/Flyway (evolution via `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`).
- Frontend: React + Vite + TanStack Query + React Router (`frontend/src`), Vitest/jsdom tests (41 files), oxlint, no Playwright anywhere.
- Auth: Google OIDC + JWT bearer (X-11) + server sessions + dev-only reference login; RBAC via central `AuthorizationService` (5 application roles) + per-tool permissions + tenant membership (X-10).
- Multi-tenancy: `tenants` root; 14 tables tenant-scoped (`NOT NULL tenant_id` + `ON DELETE CASCADE`); `users`/`sessions`/`platform_capabilities` global; `api_request_records`/`llm_usage_records` nullable-tenant. Enforcement at SQL layer + service layer + defensive re-checks.
- AI: `LlmProvider`/`ToolProposingLlm`/`SkillSelectingLlm` protocols; `DeterministicLlmProvider` (default) + `OpenRouterProvider` (production, `LLM_PROVIDER=openrouter`); embeddings via `EmbeddingProvider` (deterministic/OpenAI). Consumers: `UnifiedIntelligenceService` (Ask Arc only) and `AgentExecutionService` (bounded, max 3 steps).
- External integrations: Google OIDC, OpenRouter/OpenAI (LLM + embeddings), GitHub/Slack/Linear provider adapters (simulated default, live httpx), webhook HMAC ingress, SMTP none, no queues/workers except in-process asyncio sweeps (approval expiry, webhook retry).
- Config: environment-driven (`get_*_settings()` fail-closed validators), documented in `.env.example`; tests pin `APP_ENV`/`JWT_*`/empty role assignments.
- Docker/CI: `docker-compose.yml` (`postgres` + `arc`, `DATABASE_URL` from `POSTGRES_DB`); CI (`.github/workflows/ci.yml`) = lint job (pinned ruff), 4-way `pytest-split` sharded Docker tests on `arc_test`, plus `production-config` (`APP_ENV=production`) and `schema-bootstrap` (fresh DB) jobs, plus frontend job (npm ci → oxlint → vitest → vite build). No deploy jobs.

## Frontend routes (43)

Auth: public (`/login`, `/`), `RequireAuth` (workspace), `RequirePermission(<perm>)` (tenant pages), `RequirePlatformAdmin` (platform), `RequireTenant` membership (tenant layout). Tenant context from `useTenant()`/`useParams`; capabilities from `GET /auth/me`.

| # | Route | Guard | Key interactive elements | Backend calls |
|---|---|---|---|---|
| 1 | `/` RootRedirect | none | none | none |
| 2 | `/login` | public | Google sign-in button, persona Select + sign-in | dev reference-personas fetch only |
| 3 | `/session` | — | redirect only | none |
| 4 | `/app` WorkspaceDispatch | RequireAuth | ErrorState retry | `GET /auth/me` |
| 5 | `/app/profile` | RequireAuth | Sign-out button | `GET /auth/me` |
| 6-7 | `/app/t/:id` layout/index | RequireTenant | none (`Outlet`/redirect) | membership check |
| 8 | `/app/t/:id/home` | RequireAuth+Tenant | links only | `getUserTenants` |
| 9 | `/app/t/:id/ask` AskArc | `knowledge:read` | form, textarea (Enter-submit), source Select, Ask/Clear/Copy buttons, answer+citations | `POST .../intelligence/query`, `GET .../knowledge` |
| 10-12 | `/app/t/:id/knowledge`, `/new`, `/:documentId` | `knowledge:read` / `knowledge:create` | search input, source Tabs, new/edit forms (Select/Inputs/Textarea/Version), doc links | knowledge CRUD + search |
| 13 | `/app/t/:id/overview` | `tenant:read` | links only (capability-gated) | tenants/users/knowledge/approvals/agent-runs |
| 14 | `/app/t/:id/users` | `tenant:read` | Add-member + Confirm-remove Dialogs, search input (>4 rows) | membership CRUD, tenant users |
| 15 | `/app/t/:id/settings` | `tenant:update` | company profile form, Save/Discard | get/update tenant |
| 16-18 | `/app/t/:id/skills`, `/new`, `/:skillId` | `skill:read` / create | Execute dialog (inputs, preconditions checkboxes, tool-calls JSON), skill CRUD forms, delete confirm | skills CRUD + execute |
| 19 | `/app/t/:id/agents` | `agent:execute` + `observability:read` (history) | goal textarea, Start button, View-trace toggles | runAgent, list/getAgentRun |
| 20 | `/app/t/:id/tools` | `tool:read` / execute-gated | per-tool Execute modal (JSON input) | listTools, executeTool |
| 21 | `/app/t/:id/connectors` | `connector:read` / create/sync-gated | Create dialog (provider Select), Sync buttons | list/create/sync connectors |
| 22 | `/app/t/:id/webhooks` | `webhook:read` | static ledger table only | listWebhookEvents |
| 23 | `/app/t/:id/usage` | `observability:read` | 24h/7d/30d period buttons | usage-summary |
| 24 | `/app/t/:id/approvals` | `approval:read` / decide-gated + four-eyes | status filter buttons, Approve/Reject buttons | list/decide approvals |
| 25-31 | removed-shell redirects (operations/activity/incidents/company-brain) + legacy `/app/*` aliases | — | redirects only | none |
| 32-36 | `/platform/*` dashboard/tenants/users/observability | RequirePlatformAdmin | create dialogs, search input, links, health badges | platform tenants/users/summary/health |
| 37 | `*` NotFoundPage | none | Back-to-dashboard link (points at legacy alias) | none |

Anomalies: every button/link/input found has a handler; only issues are `NotFoundPage` linking a legacy alias (non-admins bounce) and a Cancel button missing explicit `type=` inside a form (`NewKnowledgePage.jsx:170-176`).

## Backend endpoints (selection; full per-endpoint table in prior API inventory)

Auth/session: `GET /auth/google`, `/auth/callback`, `/auth/workspaces`, `POST /auth/logout(-all)`, `GET /auth/me`, `GET /health`, dev-only `/internal/dev/*`. Product: intelligence query (`knowledge:read`), agent runs + resume (`agent:execute`), skills CRUD/execute/resume, tools list/execute (`tool:execute` + per-tool perms), approvals list/get/decide, knowledge CRUD/search, observability usage/LLM/agent-runs (+ platform summary), webhooks ingest (HMAC, uniform 401) + list/process, connectors CRUD/sync/credentials (503 without encryption key), platform capabilities (6, platform-admin), tenants/users/memberships/platform listings. Conventions: path-vs-context mismatch → 403; cross-tenant ≡ 404; controlled failures are 200s with `status`/`error_kind`; validation 422; generic 500s. Security-sensitive: credential endpoints (plaintext in, 503 without key), approvals decide (four-eyes), membership provisioning, platform admin routes, webhook ingress, OIDC/session handling.

## Database (20 tables)

Root/global: `tenants`, `users` (UNIQUE email), `platform_capabilities`. Tenant-scoped (`NOT NULL tenant_id`, CASCADE): `memberships` (UNIQUE user+tenant), `connector_configs` (UNIQUE tenant/provider/name), `knowledge_documents` (partial unique identity), `skills` (UNIQUE tenant/name/version), `tool_execution_records` (CHECK status/outcome/risk; partial unique success idempotency), `knowledge_chunks` (dual FK + HNSW + GIN indexes), `connector_sync_records`, `connector_credentials` (UNIQUE tenant/provider), `connector_credential_audit`, `webhook_events` (UNIQUE tenant/event; status machine via DROP/ADD CHECK pairs), `approval_requests` (CHECK status/digest/expiry; partial unique open binding), `agent_run_records`, `skill_execution_records` (FK skills; `agent_run_id` unenforced), `tenant_capabilities` (composite PK, dual CASCADE). Nullable-tenant: `api_request_records`, `llm_usage_records`. User-only: `sessions`. Migration: single `schema.sql` + `ensure_schema()` splitter (no `;` in comments) + one out-of-band embeddings script.

## AuthN/AuthZ boundaries needing tests

Login/logout/session persist+expiry, protected vs public routes, 5 roles × permission matrix (JWT never grants; membership never grants app perms), tenant membership gate (X-10), path-vs-context 403s, OIDC code/state/nonce, CSRF on state-changing routes, per-tool permissions, approval four-eyes, platform-admin gates, webhook HMAC uniformity, dev-auth mount isolation (`APP_ENV`), Secure cookies outside development.

## Multi-tenancy map

Every tenant resource in §4 tables above is `WHERE tenant_id=$1` at SQL plus service-layer context derivation plus (retrieval) defensive re-check. Cross-tenant test points (UI + API): skills, documents/chunks/search, tools audit, approvals, agent runs/traces, connectors/credentials/sync, webhooks, memberships, observability aggregates, LLM usage, capabilities. Nullable-tenant aggregates must never GROUP BY tenant.

## Modules present (verified)

Tenants, users, memberships, auth/session/OIDC/dev-auth, RBAC, capabilities, skills (+inputs/risk/approval flags), tools (2, code-defined), skill/agent execution, approvals (+sweep), Company Brain (knowledge CRUD/search), RAG (chunk/embed/retrieve/RRF/ApprovedContext), Unified Intelligence (single endpoint), agents (bounded, no memory), LLM providers (deterministic/OpenRouter) + pricing/usage telemetry, embeddings (deterministic/OpenAI) + migration script, connectors (GitHub/Slack/Linear sim+live) + credentials (AES-256-GCM) + sync, webhooks (ingest/pipeline/retry-sweep), observability (usage/LLM/agent-run/health summaries), rate limiting, PII guard, pagination, sessions/CSRF, platform admin, reference seed data. **Absent:** tickets, health, escalation, support, onboarding-intelligence, notifications, billing, audit-log UI, agent memory, reranking.

## AI failure surface

Providers (key/model/base-url validation, 401/403 vs 429/5xx/timeout/empty-choice bounded retry, no fallback), deterministic-deviations, empty/no-match retrieval (answer None, LLM never called), malformed/unknown/denied tool proposals, approval expiry/consume races, agent no-decision/invalid-decision/catalog-miss, WEBHOOK_PROCESSOR scoping, usage ContextVar staleness, embedding dim-mismatch/failure (fail-closed pre-persist), prompt-injection labeling, cross-tenant retrieval (RuntimeError).

## Observability test surface

Write-paths (all best-effort, never break responses): tool/skill/agent/LLM/approval/API-request records + traces. Read-paths: tenant usage summary, LLM usage + records, agent-run list/trace, platform summary (tenant-agnostic), component health (labels only). Verify attribution (tenant/user/request IDs), aggregation math, window filtering, cascade deletes, platform-tenant blindness, correlation-ID echo.

## External integrations

Google OIDC (code/state/nonce/session cookies; mockable HTTP), OpenRouter (key/model config, bounded retry, mock transport in tests; needs sandbox key for eval), OpenAI embeddings (mockable client), GitHub/Slack/Linear adapters (simulated default; live httpx — no live tests), webhook senders (HMAC, self-simulated), reference seed (idempotent SQL). No queues, no SMTP, no billing.

## Existing tests

131 backend files (107 `test_*.py`: ~33 unit, ~44 integration real-PG, ~30 API via TestClient; 24 golden eval files + deferred agent eval placeholder), 41 frontend Vitest files (jsdom; pages, lib helpers, guards, a11y scans). Fixtures: disposable `arc_test` DB guard (`UnsafeTestDatabaseError`), session schema rebuild, pinned JWT env, `client`/`make_token`/`authorization_override`/`seeded`/`repositories`, eval conftest (skip real-LLM without key). **Playwright: zero** — no config/tests/scripts/deps/docs. CI: single `ci.yml` — lint (pinned ruff, no cache), 4 `pytest-split` Docker shards on `arc_test`, `production-config` job (`APP_ENV=production`), `schema-bootstrap` job (fresh DB), frontend job (npm cache only: ci → oxlint → vitest → build). No deploy jobs, no E2E job.
