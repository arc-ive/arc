# Arc V2 Project Context

> **Purpose.** A persistent context snapshot for Arc V2, written so a future session
> with no access to the originating conversation can pick the work up safely.
>
> **Snapshot taken:** 2026-09-21, against `origin/main` @ `525b8b5`.
>
> **Status of facts in this file.** Every issue number, PR number, assignee and state
> below was read from GitHub at snapshot time, not recalled. Anything not directly
> verified is labelled **UNVERIFIED** or **BLOCKED** with a reason. GitHub state
> changes continuously — see §19 before acting on anything here.

---

## 1. Project Identity

**Repository:** `arc-ive/arc` (public, default branch `main`).

**Architecture:** modular monolith, Docker-first.

| Layer | Stack |
|---|---|
| Backend | FastAPI / Python 3.12, `src/arc/` (~21.7k LOC, 77 modules) |
| Frontend | React + Vite, `frontend/src/` (~108 files) |
| Database | PostgreSQL 17 + pgvector, 20 tables, `src/arc/db/schema.sql` |
| Tests | pytest (~2,473 passing, 165 skipped), Vitest (153 passing) |

**V2 governing documents:**

- `docs/v2/ARC_V2_PRD.md`
- `docs/v2/ARC_V2_TRD.md`
- `docs/v2/ARC_V2_ADR.md` — 28 accepted ADRs (V2-ADR-001 … V2-ADR-028)

**Authority order (non-negotiable):**

```
V2 ADR  >  TRD  >  PRD  >  implementation
```

If implementation contradicts the governing architecture, the implementation is
wrong. Do not silently reinterpret a requirement to match the code.

**Production-grade objective — V2-ADR-028** defines production-ready as *all ten* of:

1. end-to-end workflow works
2. tenant isolation verified
3. authorization verified
4. failures controlled
5. observability exists
6. AI features have evaluation coverage
7. secrets handled correctly
8. data boundaries preserved
9. tests pass
10. documentation matches behaviour

**Current development phase:** exhaustive V2 audit **complete and frozen**;
**remediation underway** against an assigned backlog.

---

## 2. Team and Ownership

| Name | GitHub login | Git author strings seen |
|---|---|---|
| Joe | `Joemon24` | `Joemon24`, `Joemon Joy` |
| Bharath | `bharathg2004` | `bharathg2004`, `Bharath G` |
| Bala | `crystalknife` | `crystalknife`, `Balasubrahmanya A G` |
| Chinthan | `chinthanshetty07` | `chinthanshetty07`, `ChinthanShetty`, `Chinthan Shetty` |

**Stated domain ownership** (as recorded by the team):

- **Joe** — AI / RAG / LLM / Agents
- **Bharath** — Platform / DevOps / DB / observability, plus Skills / Skill Execution
- **Bala** — Core backend / API / integrations
- **Chinthan** — CI/infra and frontend contributions (see per-issue assignments in §7)

**Do not reassign issues based on assumptions.** Per-issue assignees recorded in
§5–§7 are the authoritative GitHub state at snapshot time and were set deliberately.

> **Recorded discrepancy, do not "correct" it.** The stated domain ownership places
> Skills / Skill Execution with Bharath, but **#208** (skill execution record
> persistence) and **#241** (skill declared inputs) are assigned to **Bala** on
> GitHub, because the underlying change is in `SkillExecutionService`, whose trace
> persistence Bala authored (#143). Both are correct as they stand. Left as-is.

There is **no `CODEOWNERS` file** in this repository.

---

## 3. Development / Review Workflow

- The user + OpenCode **implement** assigned work.
- Teammate/Claude is **review-only**: reviews do not implement and do not merge.
- PRs require **real verification**, not "tests are green".
- Do **not** declare V2 complete merely because tests pass (see §17).
- Merge only after appropriate approval and checks.

**V2-ADR-027 — PR discipline:**

```
feature branch → tests → commit → push branch → PR → review → merge
```

**CONTRIBUTING.md conventions:**

- Branch naming: `feature/<short-name>`, `fix/<short-name>`, `chore/<short-name>`,
  `docs/<short-name>`. Never personal/ambiguous names (`bala`, `joe-work`, `test`).
- Commits: small, focused, descriptive; `type: short description`.

**CI pipeline** (`.github/workflows/ci.yml`), as of snapshot:

| Job | Purpose |
|---|---|
| `Lint & Format` | Ruff, version read from the exact pin in `pyproject.toml` |
| `Test (shard 1–4)` | pytest split four ways by `.test_durations`, `fail-fast: false` |
| `Schema Bootstrap (fresh DB)` | added by PR #244 — provisioning against an empty database |

`main` is **not** branch-protected at snapshot time; there are no required status checks.

---

## 4. V2 Audit Baseline

An exhaustive end-to-end audit was performed and is **frozen**.

**Evidence base:** 433 V2 requirements extracted from the PRD, TRD and all 28 ADRs;
a 7-area system map producing 170 file:line observations; ~100 runtime tests against
a live instance (webhooks, connectors, approvals, frontend browser testing, document
formats, RAG evaluation, failure injection, concurrency).

**Frozen baseline at audit close:**

| | Count |
|---|---|
| Open remediation issues | **39** |
| Audit-filed issues | **36** |
| Pre-existing issues carried forward | 3 (#185, #188, #203) |
| P0 | **2** |
| P1 | **8** |
| P2 | **18** |
| P3 | **10** |
| Requirements blocked/unverified for documented reasons | **43** |

**Requirement coverage at audit close:**

| Classification | Requirements | Share |
|---|---|---|
| RUNTIME TESTED | 325 | 75% |
| CODE VERIFIED | 65 | 15% |
| BLOCKED / not runtime-testable | 43 | 10% |

**Current state at snapshot (2026-09-21, `main` @ `525b8b5`):** **36 open issues** —
1 P0, 7 P1, 17 P2, 10 P3, plus #203 (unlabelled). 34 carry the `audit` label.
#207, #209 and #188 closed since the baseline.

> ### "39 issues fixed" is NOT equivalent to "Arc V2 complete."
>
> The 39 issues are **findings**, not the requirement set. They were produced by an
> audit that explicitly could not verify 43 requirements, and that ran entirely
> against a deterministic LLM provider. Closing every issue leaves those 43
> requirements exactly as unverified as they are today. Completion is defined in
> §17 and requires a requirement-level pass across all 433.

---

## 5. P0 Issues

### #206 — Skill approval gate is bypassable with a fabricated `approval_id`

| | |
|---|---|
| **Status** | **OPEN** |
| **Assignee** | Bala (`crystalknife`) |
| **Linked PR** | **#247** (OPEN, head `33fef7a`) — "fix(security): verify skill approval on resume" |
| **Requirement** | V2-ADR-011 (skill and tool approval are separate controls), V2-ADR-012 (approval is not authorization), V2-ADR-028 criteria 3 and 4 |
| **Verification** | Defect **RUNTIME-VERIFIED**. Fix **NOT yet verified** — see below. |

**Root cause.** `src/arc/services/skill_execution.py:292`:

```python
# On resume, skip this gate — the approval was already granted.
if skill.approval_required and approval_id is None:
```

Any non-`None` `approval_id` skips the gate. The comment asserts an approval exists;
nothing verifies it. The value is forwarded to the tool layer (`:334`) but consumed
only when that tool independently requires tool-level human approval — so for any
other tool it is never validated by anything.

**Runtime evidence (original).** Skill set `approval_required=true`;
`approval_requests` table held **0 rows**; `POST /skills/{id}/execute` without an
approval_id correctly returned `approval_required`; `POST /skills/{id}/resume` with
`approval_id: "fabricated-approval-does-not-exist"` returned **HTTP 200,
`status: "succeeded"`, 1 step executed, tool invoked**, and `approval_requests`
remained at 0.

**Snapshot note — UNVERIFIED.** PR #247 exists and its four test shards pass, but
**`Lint & Format` is FAILING** at head `33fef7a`. The fix has not been independently
runtime-verified against the original reproduction.

---

### #207 — Arc cannot start against a fresh database; no schema bootstrap

| | |
|---|---|
| **Status** | **CLOSED (COMPLETED)** 2026-09-21 |
| **Assignee** | Bharath (`bharathg2004`) |
| **Linked PR** | **#244 (MERGED)** — "fix(deploy): bootstrap schema on fresh database (#207)" |
| **Requirement** | V2-ADR-028 criteria 1 and 10; PRD-02 |
| **Verification** | **VERIFIED** — original reproduction re-run against the PR head and inverted |

**Root cause.** `src/arc/db/schema.sql` was applied by nothing outside test fixtures.
No migration runner existed. `src/arc/setup/init.py` held a stale 3-table inline DDL
that lagged the ~20-table schema and had no importers.

**Original runtime evidence.** Empty database → `asyncpg.exceptions.UndefinedTableError:
relation "tenants" does not exist` → `Application startup failed. Exiting.` → 0 tables,
`/health` never served.

**Fix and verification.** `ArcDatabase.ensure_schema()` applies `schema.sql`
idempotently on every startup, before reference seeding; failure aborts startup.
Re-running the original reproduction against PR #244's head produced: 0 tables →
**`/health` 200** → **20 tables**, log `Database schema ensured from schema.sql`.
Idempotent restart preserved an inserted marker row (20 tables, marker intact).

**Non-blocking follow-ups raised in review of #244 (not filed as issues):**

1. `split(";")` now runs at **startup**, not only in tests, so a semicolon inside a
   `schema.sql` comment breaks application startup. Demonstrated: `/health` 000,
   **5 of 20 tables** created. No test guards this rule (the PR's guard test checks
   for inline `CREATE TABLE`, not semicolons).
2. The statement loop is **not transactional**, so a mid-file failure leaves a
   partially provisioned database.
3. Comment-only fragments are sent to PostgreSQL, producing an opaque
   `'NoneType' object has no attribute 'decode'`.
4. `setup/init.py` now shells out to `psql`, which is **not present** in the
   `python:3.12-slim` image. Latent — the module has no importers.

---

## 6. P1 Issues

| # | Title | Assignee | Status | PR |
|---|---|---|---|---|
| **#208** | fix(skills): skill execution records are never persisted — repository exists but is not wired | Bala | OPEN | none known |
| **#209** | fix(pii): PII Guard does not detect credentials, API keys, or tokens | Joe | **CLOSED (COMPLETED)** | **#246 MERGED** |
| **#210** | fix(rag): no relevance floor — irrelevant queries return confident cited answers | Joe | OPEN | none known |
| **#211** | fix(rag): citations report the retrieval set, not what grounded the answer | Joe | OPEN | none known |
| **#212** | fix(capabilities): enabling a platform capability disables the feature for every tenant | Bharath | OPEN | none known |
| **#213** | fix(approvals): no tool requires human approval — the approval subsystem is unreachable | Bharath | OPEN | none known |
| **#214** | fix(seed): reference knowledge documents bypass ingestion and are invisible to RAG | Bharath | OPEN | none known |
| **#215** | fix(pii): SSN detection still misses the exact formats in closed issue #167's acceptance criteria | Joe | OPEN | none known |

**#208** — `PostgreSQLSkillExecutionRecordRepository` is fully implemented but is the
**only** repository class absent from `app.py`'s wiring (all 14 others are constructed).
`SkillExecutionService.__init__` takes `record_repo=None` (`:138`) and `_persist_record`
returns silently when None (`:441-446`). `repositories/observability.py:153` reads the
table. **RUNTIME-VERIFIED:** three executions (succeeded/denied/precondition-refused)
plus one through the UI left `skill_execution_records` at **0** and
`usage-summary.skills.total_executions` at **0**. A *denied* execution — an AI proposing
an unauthorized tool — leaves no audit trail.

**#210** — No relevance threshold anywhere in `services/retrieval.py`. `relevance_score`
is computed (`:295`) and never used to filter. **RUNTIME-VERIFIED:** no-answer
correctness **0/5** across the 22-query evaluation. The no-answer path exists and works
on a completely empty index, but is unreachable once any chunk exists.

**#211** — `services/intelligence.py:138` builds `citations` from every approved item
**before** the model runs. **RUNTIME-VERIFIED:** citation count tracks the retrieval set
exactly (limit 1→1, 2→2, 5→5) and all five unanswerable queries still returned ~5 citations.

**#212** — `CapabilityService.is_effective` (`services/capabilities.py:37-50`): platform
row absent → allow; platform row `True` → requires explicit tenant opt-in. So enabling is
*more restrictive* than not registering. **RUNTIME-VERIFIED** and state restored:
0 rows → tool execute **200**; admin enables `tool_execution` → **403**; row deleted → **200**.

**#213** — `PLATFORM_TOOLS = (SERVICE_HEALTH_TOOL,)` (`services/tools.py:432`), declared
`risk_level=LOW` with a default policy. No tool anywhere declares
`REQUIRE_HUMAN_APPROVAL`. **RUNTIME-VERIFIED:** three tool executions left
`approval_requests` at 0; the approvals API returns `{"items":[],"total":0}` and
structurally always will. The approval machinery itself is complete and its state
machine is correct (§9).

**#214** — `src/arc/setup/reference_data.py:222,227,347` inserts knowledge documents via
raw `INSERT INTO knowledge_documents` SQL, bypassing `KnowledgeService` and the
chunk+embed pipeline. **RUNTIME-VERIFIED:** 8 seeded documents across all four tenants,
**0 chunks**. Connector sync, by contrast, chunks correctly — this is specific to the seeder.

**#215** — #167 was closed COMPLETED, but its own acceptance criteria list
`123-45-6789` **and** `123456789`. **RUNTIME-VERIFIED:** `555-12-3456` redacts;
`123-45-6789` does **not**, even with "social security number" context; bare
`123456789` does not. `US_SSN` *is* in the defaults and commit `d3ca84a` *is* on main,
so this is recognizer coverage, not configuration.

---

## 7. P2 and P3 Backlog

All rows read from GitHub at snapshot time. **No PRs are known to be linked to any of
these except #231 (PR #245) and #237 (PR #243).**

### P2 — 17 open

| # | Title | Assignee | Status | PR | Root cause (short) |
|---|---|---|---|---|---|
| 216 | fix(agent): LLM provider failure is unhandled — HTTP 500 and no run trace persisted | Bala | OPEN | — | No try/except around the provider call at `agent.py:194` |
| 217 | fix(rag): caller limit does not bound the context set, and there is no token budget | Joe | OPEN | — | `limit` passed to dense and lexical retrievers separately; RRF returns the union; no prompt budget |
| 218 | fix(rag): dense and lexical scores share one field with incompatible scales, degrading ranking | Joe | OPEN | — | Cosine and `ts_rank` both written to `KnowledgeMatch.similarity` |
| 219 | fix(rag): contradictory sources are cited together with no conflict or recency signal | Joe | OPEN | — | No supersession/recency handling in retrieval |
| 220 | fix(knowledge): documents created through the UI can never be updated | Bharath | OPEN | — | No PUT/PATCH on the document route; UI form exposes no `external_id`, so no upsert key |
| 221 | fix(webhooks): documented endpoint configuration shape fails every delivery | Bharath | OPEN | — | `.env.example` omits the required `action` block |
| 222 | fix(webhooks): API exposes no failure reason, attempt count, or next-retry time | Bharath | OPEN | — | Event responses omit `error_kind`, `retry_count`, `next_retry_at`, `processed_at` |
| 223 | fix(frontend): Usage page reports available metrics as Not tracked | Joe | OPEN | — | Three tiles hardcode "N/A — Not tracked" for data the backend returns |
| 224 | fix(frontend): Approvals status filter never refetches and does nothing | Chinthan | OPEN | — | `statusFilter` used by queryFn but absent from the React Query `queryKey` |
| 225 | fix(frontend): API errors render as a permanent loading skeleton with no error state | Joe | OPEN | — | Failed queries render the loading skeleton indefinitely |
| 226 | feat(frontend): no UI exists to start or view agent runs | Joe | OPEN | — | No Agents nav entry; `runAgent` imported by nothing |
| 227 | fix(rag): chunking runs with zero overlap in production wiring | Joe | OPEN | — | `KnowledgeChunker()` constructed with no args at `app.py:129` and `retrieval.py:129` |
| 228 | fix(agent): agent_capability_unavailable conflates two unrelated causes, and the documented default always fails | Bala | OPEN | — | Same error kind at `agent.py:163` and `:174`; deterministic provider is never decision-capable |
| 229 | fix(connectors): credential encryption is disabled by default and the key is undocumented | Bala | OPEN | — | Missing `CONNECTOR_ENCRYPTION_KEY` logged at INFO, ENV fallback; variable absent from `.env.example` |
| 230 | fix(observability): failed and empty-choices LLM calls produce no usage record | Joe | OPEN | — | `_execute_request` raises before reading `usage`; failures never metered |
| 231 | fix(ci): CI never exercises the production configuration | Chinthan | OPEN | **#245 (OPEN, all checks green)** | Whole suite runs `APP_ENV=development` |
| 232 | fix(tests): test suite drops the schema of whatever DATABASE_URL names, defaulting to the dev database | Bharath | OPEN | — | `conftest.py:48` `DROP SCHEMA public CASCADE`; default URL is the dev database |

### P3 — 10 open

| # | Title | Assignee | Status | PR | Root cause (short) |
|---|---|---|---|---|---|
| 233 | fix(connectors): whitespace-only credential is accepted and stored as valid | Bala | OPEN | — | Emptiness tested by truthiness, not after stripping |
| 234 | fix(knowledge): concurrent upserts lose document version increments | Bharath | OPEN | — | Non-atomic read-modify-write; no `ON CONFLICT`, no optimistic lock |
| 235 | fix(llm): retry attempts, backoff and exhaustion are never logged | Joe | OPEN | — | `services/llm.py` has no logger at all |
| 236 | fix(api): tool execution uses `input` while skill tool_calls use `parameters` | Bala | OPEN | — | Two names for one concept; unknown fields silently ignored |
| 237 | feat(frontend): no delete control for skills although the permission and endpoint exist | Chinthan | OPEN | **#243 (OPEN, all checks green)** | See correction note below |
| 238 | fix(webhooks): handled terminal outcomes are logged as ERROR with a stack trace | Bala | OPEN | — | Business outcome raised as an exception escaping to the sweep |
| 239 | fix(db): approval expiry invariant is enforced only in code, not in the schema | Bharath | OPEN | — | No CHECK constraint for `expires_at > created_at` |
| 240 | fix(observability): requests outside the route table log as `unmatched` | Bharath | OPEN | — | Attribution derived only from path params |
| 241 | fix(skills): declared skill inputs cannot be supplied through the API | Bala | OPEN | — | `SkillExecuteRequest` exposes only `tool_calls` and `satisfied_preconditions` |
| 242 | fix(api): skills are tenant-scoped by query parameter while every other resource uses the path | Bharath | OPEN | — | Divergent scoping convention |

> **Correction recorded on #237.** The issue's original *Current behavior* and
> *Root cause* were **wrong** and a correction is posted as a comment on the issue.
> The delete affordance was already fully wired (`canDelete`, `deleteTarget`,
> `deleteMutation`, a rendered `<DeleteConfirmDialog>`, a `Trash2` button). The two
> real defects are: (a) the button carried no `title`/`aria-label`, so it had no
> accessible name; (b) `DeleteConfirmDialog` rendered `<Dialog>` with **no props**, and
> `Dialog` returns `null` when its own `open` is falsy — so the confirmation could never
> open and deletion was impossible. Implementing from the original text would have added
> a duplicate control while leaving the real bug in place.

### Unlabelled

| # | Title | Assignee | Status |
|---|---|---|---|
| 203 | fix: retry on LLM provider returning HTTP 200 with empty choices | Joe | **OPEN** — its PR #204 is MERGED; the issue was not auto-closed |

---

## 8. Recently Completed / Merged Work

| PR | Author | Merged | Significance |
|---|---|---|---|
| #198 | Bharath | 2026-09-21 | Bounded repository list queries with a default limit (#183) |
| #199 | Bala | 2026-09-21 | HMAC timestamp tolerance 300s → 120s (#184). **RUNTIME-VERIFIED:** −119s accepted, −121s/−301s/−600s/+301s all 401 |
| #200 | Joe | 2026-09-21 | `.env.example` LLM model config. Reviewed: initially flipped `LLM_PROVIDER` to `openrouter`, which broke fresh-clone startup; corrected to a purely additive comment block |
| #201 | Chinthan | 2026-09-21 | CI: four-way test sharding, lint lifted off the application image, Dockerfile layer reorder. Wall clock ~9.7 min → ~4.8 min |
| #202 | Bala | 2026-09-21 | Removed tenant ids from repository error messages (#180) |
| #204 | Joe | 2026-09-21 | **Empty OpenRouter choices retry** (#203). `LlmError` → `LlmRetryableError` (a subclass, so existing `except LlmError` handlers are unaffected) so empty-choices enters the existing bounded retry. Reviewed and approved |
| #205 | Bala | 2026-09-21 | **Credential length bound** (#185, now CLOSED). Confirmed unfixed on main during the audit: a 200,000-character credential was accepted and stored as 200,028 bytes |
| #244 | Bharath | 2026-09-21 | **Fresh-database schema bootstrap** (#207). See §5 |
| #246 | Joe | 2026-09-21 | **Credential / API key / token detection** (#209). See below |

### #246 in detail — remediation for #209

| | |
|---|---|
| PR | **#246**, MERGED 2026-09-21 |
| Commit | **`28d364d`** |
| Issue | **#209** (CLOSED, COMPLETED) |
| Author | Joe (`Joemon24`) |
| Review | **Approved by Chinthan** |

**Independent verification performed by Chinthan** — the original #209 probes were
re-run against the PR head rather than relying on CI:

| input (verbatim from #209) | before | on #246 |
|---|---|---|
| `Recovery token ghp_auditsynthetictoken12345.` | not redacted | `Recovery token <CREDENTIAL>.` |
| `key sk-proj-abc123def456ghi789jkl` | not redacted | `key <CREDENTIAL>` |
| `AKIAIOSFODNN7EXAMPLE` | not redacted | `<CREDENTIAL>` |

**Test results:** 44/44 PII tests passed; 133/133 PII-adjacent tests passed (knowledge,
skill, tool PII); CI 4/4 shards passed.

**False-positive testing:** ten realistic pieces of enterprise content were tested;
**nine were correctly left untouched** — prose, git commit SHA, UUID, 32-char document
id, base64 blob, sha256 digest, hyphenated skill id, product licence key, policy text.

**Non-blocking follow-up observations — these are NOT blockers to #246** and must not be
represented as such unless a future issue's acceptance criteria require them:

- Slack (`xoxb-`, `xoxp-`) and Linear tokens not covered, though Arc ships
  `slack.py` and `linear.py` connectors
- Google API keys (`AIza…`) not covered
- Stripe keys (`sk_live_…`, underscore form) not covered
- Database connection strings with embedded passwords not covered
- Patterns are unanchored, so a match can be partial (`ghp_…-TAIL` → `<CREDENTIAL>-TAIL`);
  this also produced one contrived false positive (`AKIAOPSDESKREQUEST0042` → `<CREDENTIAL>42`)
- Generic high-entropy bearer tokens not covered. This *was* listed in #209's
  acceptance criteria, and the reviewer explicitly judged it should **not** block:
  generic entropy detection is what would start redacting the git SHAs, UUIDs and
  digests the PR correctly leaves alone. Recorded as a deliberate engineering
  trade-off, not an oversight.

### Open PRs at snapshot

| PR | Author | Targets | Checks |
|---|---|---|---|
| **#243** | Chinthan | #237 | all green |
| **#245** | Chinthan | #231 | all green |
| **#247** | Bala | #206 | **`Lint & Format` FAILING**; 4/4 test shards passing |

---

## 9. Known Verified-Working Areas

All **RUNTIME-VERIFIED** during the audit against a live instance. Treat as working
unless a later change invalidates them.

| Area | Evidence |
|---|---|
| Unauthenticated access protection | 401 on 8/8 tenant-scoped endpoints with no session |
| Cross-tenant isolation (reads) | **403 on 10/10** endpoints; same endpoints 200 on own tenant |
| Cross-tenant isolation (writes) | POST **and** DELETE memberships into another tenant → 403; row counts unchanged |
| Cross-tenant isolation (query-param path) | `/skills?tenant_id=<other>` → 403 (a distinct code path from `/tenants/{id}/…`) |
| Cross-tenant isolation (RAG) | Querying another tenant's topic returned only own-tenant documents |
| Cross-tenant isolation (connectors) | Credential GET/POST/DELETE and sync against another tenant → 403 |
| RBAC | Employee denied on 6/6 privileged operations including attempted self-escalation to OWNER; server-side, not UI-hiding |
| ADR-009 execution boundary | Undeclared tool → `denied`; unmet precondition → refused |
| Webhook auth | Invalid signature / wrong secret / unknown endpoint → uniform 401, no endpoint enumeration |
| Webhook timestamp | 120s tolerance, symmetric |
| Webhook malformed payloads | 6/6 rejected with specific 400s; no rows created |
| Webhook idempotency | Same `event_id` → same record, `duplicate: true`, 1 row |
| Webhook retry lifecycle | transient → `retrying` with exponential backoff → exhaustion → **`dead_letter`** |
| Webhook stuck recovery | Event stuck 20 min recovered in 26s; genuinely reprocessed, not a status flip |
| **Webhook concurrency** | **10 simultaneous duplicate deliveries → 1 row, 1 tool execution, 9 duplicate flags. No double execution** |
| Connector credential encryption | AES-256-GCM with key versioning; `encrypted_credential` is bytea (57 bytes for a 28-char secret); zero plaintext; **zero secret occurrences in logs** |
| Connector credential rotation | `rotated_at` set, row replaced in place, old ciphertext gone, audit appended |
| Connector credential deletion | Row removed, audit `delete` appended, subsequent GET → 404 |
| Connector credential audit trail | Every operation recorded with actor: create/rotate/create/create/delete |
| Connector → Company Brain | Sync produced knowledge documents **with chunks** (PRD-07 works end-to-end) |
| Connector sync idempotency | Second sync created no duplicate documents |
| Approval state machine | approve 200, reject 200, expired **409**, duplicate decision **409**, wrong tenant **403**, insufficient role **403**; `uq_approval_requests_open_binding` prevents duplicate open approvals |
| RRF hybrid retrieval | 11/14 top-1 (79%), 13/14 recall@5 (93%) on the 22-query evaluation |
| Deletion cascade | DELETE → 204, chunks cascade 1→0, document immediately stops being cited |
| `external_id` upsert | Same id, `version` 1→2, one row, chunk re-indexed, only current version cited |
| Request validation | Malformed input → controlled 4xx on 11/12 probes, never 5xx; `limit=true` → 422 `int_type` |
| Structured logging | Every request logs method, route, status, `duration_ms`, tenant, `request_id` |
| Config fail-closed | DB pool bounds and webhook tolerance raise on invalid values |
| Production gate correctness | `main.py:103` gate and `_cookie_secure()` are both written correctly and fail closed when `APP_ENV` is unset |

---

## 10. Known Audit Findings

Cross-references to the issue that carries each finding. Do **not** re-file these.

| Finding | Issue |
|---|---|
| Skill approval bypass on resume | #206 (P0) |
| Fresh-database bootstrap missing | #207 (P0, **closed** via #244) |
| PII Guard missed credentials/keys/tokens | #209 (P1, **closed** via #246) |
| Skill execution records never persisted | #208 |
| No RAG relevance floor | #210 |
| Citations report retrieval, not grounding | #211 |
| Capability semantics inverted | #212 |
| Approval subsystem unreachable | #213 |
| Seeder bypasses ingestion | #214 |
| SSN detection limitations | #215 |
| Agent provider failure unhandled / no trace | #216 |
| Context set unbounded, no token budget | #217 |
| Incompatible score scales | #218 |
| Contradictory sources cited together | #219 |
| UI documents un-updatable | #220 |
| Webhook documented config fails every delivery | #221 |
| Webhook API hides failure/retry state | #222 |
| Connector findings (encryption default, whitespace credential, sync retry state) | #229, #233 |
| API findings (`input` vs `parameters`, skills scoping) | #236, #242 |
| UI findings | #223, #224, #225, #226, #237 |
| Concurrency / versioning (lost version increments) | #234 |
| Production configuration verification gap | #231 |

**Additional recorded observations not filed as issues** (kept so they are not
rediscovered): `connector_sync_records` carries no retry/failure state and there is no
sync retry mechanism comparable to the webhook one; connector provider integrations are
simulated-only by default (`build_provider_registry` falls through to
Fake{GitHub,Slack,Linear}), which is a scope limitation under ADR-002, not a defect.

---

## 11. Explicitly Disproven / Out-of-Scope Findings

**Do not reopen these merely because they look like missing features.** Each was
examined and rejected with a reason.

| Claim | Verdict | Reason |
|---|---|---|
| File / PDF / DOCX / CSV / HTML upload is missing | **OUT OF SCOPE** | **#166 closed as NOT_PLANNED**: "V2 does not require file/document upload… File upload (PDF/DOCX/TXT) is aspirational and outside V2 acceptance scope." Independently confirmed five ways: zero format mentions across PRD/TRD/ADR; no `UploadFile`/`multipart` anywhere in `src/arc/api/`; `POST /knowledge` accepts `application/json` only with `content: string`; no parser dependency in `pyproject.toml`; the UI create form has `fileInputs: 0` |
| Commercial entitlement layer (ADR-004 layer 2) is missing | **OUT OF SCOPE** | **#144**'s agreed scope explicitly excluded it: "Do NOT implement billing/Stripe (explicitly deferred per PRD §24)". Its Definition of Done covers capabilities only |
| Incidents page is an unimplemented placeholder | **NOT A DEFECT** | **V2-ADR-021** decides against a dedicated incident entity: "Do not add an `incidents` table solely because incident concepts appear in product documentation. A first-class incident entity requires a separate product requirement." The placeholder is the correct outcome |
| Skills "Execute" button is missing / #170 regressed | **DISPROVEN** | The control exists as an icon-only button `title="Execute skill"`; an initial text search missed it. Confirmed by DOM enumeration and by performing a real execution. #170 was correctly closed |
| Approval bypass reproducible on `/execute` | **DISPROVEN on that route** | `SkillExecuteRequest` silently drops `approval_id`. The defect is real but only on `/resume` — filed correctly as #206 |
| Cross-tenant membership write is possible | **DISPROVEN** | Acme admin POST and DELETE into Nova both returned **403**; Nova membership count unchanged 4→4. Structural concern only (raw path `tenant_id`, no TenantContext), recorded as low-priority hardening |
| Deciding an expired approval returns 500 | **TEST ARTIFACT** | Caused by a planted row with `expires_at` before `created_at`, violating a domain invariant the application never produces. With valid ordering the endpoint correctly returns **409** |
| Knowledge documents cannot be updated at all | **DISPROVEN as stated** | `external_id` upsert works correctly (same id, version 1→2, re-indexed). The real, narrower defect is that the **UI form has no `external_id` field** — filed as #220 |
| Webhook `failed` + retries-exhausted rows are never dead-lettered | **TEST ARTIFACT** | That state is not naturally reachable; a planted row. Real exhaustion correctly reaches `dead_letter` |
| #237 "delete affordance was never wired" | **PARTLY DISPROVEN** | See the correction note in §7 |

---

## 12. RAG Current State

**Ingestion model.** Direct knowledge **text/content** is the V2 ingestion model —
`POST /tenants/{id}/knowledge` with `source` (enum of six), `provenance`, `content`
(string). No file upload (§11).

**Retrieval.** Hybrid: dense (pgvector cosine) + lexical (PostgreSQL `ts_rank`), fused
by Reciprocal Rank Fusion. **V2-ADR-007** — hybrid retrieval without reranking;
**V2-ADR-020** — reranking deferred.

**Audit evaluation — 22 queries, RUNTIME:**

| Metric | Result |
|---|---|
| Queries | 22 |
| Answered | 22/22 (100%) |
| `context_used` | 22/22 (100%) |
| **No-answer correctness** | **0/5 (0%)** |
| **Expected document ranked FIRST (top-1)** | **11/14 (79%)** |
| Expected document anywhere (recall@5) | 13/14 (93%) |
| Responses exceeding the requested limit | 1/22 |

**Citation behaviour.** Citations are the **retrieval set**, captured before the model
runs. Count tracks `limit` exactly (1→1, 2→2, 5→5) and unanswerable queries still return
~5 citations. → **#211**.

**Relevance-floor defect.** No threshold anywhere; `relevance_score` computed and
discarded. Nonsense queries return confident, cited answers. → **#210**.

**Grounding defect.** A citation presented against an answer implies support; today it
only means the chunk was retrieved. → **#211**.

**`external_id` version/upsert behaviour — VERIFIED WORKING.** Re-POSTing the same
`external_id` returns the same document id with `version` incremented, one row, chunk
re-indexed, only the current version cited. Identical content → no version bump, no
chunk churn.

**Deletion behaviour — VERIFIED WORKING.** DELETE → 204, chunks cascade, document
immediately stops appearing in citations.

**Known concurrency/versioning limitation.** 8 concurrent upserts with differing content
produced **version 2, not 8** — six increments lost to a non-atomic read-modify-write.
Row count, chunk set and content stayed consistent, so this is a lost counter, not
corruption. → **#234**.

**Deterministic vs live LLM testing limitation — BLOCKED.** All RAG results above were
obtained with `LLM_PROVIDER=deterministic` and `EMBEDDING_PROVIDER=deterministic`.
Retrieval and ranking figures are real; **answer quality and grounding under a live
model are unmeasured**.

---

## 13. LLM / AI Current State

- **Deterministic provider is the safe default.** `.env.example` ships
  `LLM_PROVIDER=deterministic` / `LLM_MODEL=deterministic-local`. `get_llm_settings()`
  documents this: "Defaults to the deterministic provider so the application runs
  without configuration."
- **OpenRouter is opt-in.** Selecting it requires `OPENROUTER_API_KEY`; missing key
  raises `LlmConfigurationError` at startup (fail-closed, verified).
- **Free model used for local real-RAG testing when applicable:**
  `nvidia/nemotron-3-super-120b-a12b:free`, documented in `.env.example` as an opt-in
  comment block (PR #200).
- **The free provider is subject to rate limits and availability changes.** This is
  documented in `.env.example`. Evidence: the previously configured free model
  (`google/gemma-4-31b-it:free`) began returning HTTP 429 on all retries, and *this*
  model is the subject of #203.
- **#203** — OpenRouter can return HTTP 200 with an empty `choices` array. Previously
  raised a non-retryable `LlmError` → HTTP 500. Issue is still **OPEN** although its
  PR merged.
- **#204 (MERGED)** — the retry fix. `LlmRetryableError` is a **subclass** of
  `LlmError`, so existing `except LlmError` handlers are unaffected while the retry loop
  catches it specifically. Retry remains bounded (`range(1 + max_retries)`), backoff
  unchanged, 429/5xx/401/403 classification untouched.
- **Provider failure behaviour — VERIFIED.** With the provider pointed at a dead
  endpoint, a RAG query took ~4s (bounded retry with backoff), returned **HTTP 500
  `{"detail":"Intelligence query failed"}`** with no provider detail leaked, and
  **no fabricated answer**. The agent path, by contrast, returned an unhandled
  500 and persisted no trace → **#216**.

> ### BLOCKED: real-LLM evaluation
>
> Real LLM evaluation was **blocked** during the exhaustive audit because live-provider
> evaluation was not permitted or configured (ADR-002 does not authorize live mode; no
> API key was configured). **22 of the 43 blocked requirements are AI Evaluation
> requirements for this reason.**
>
> **NEVER claim real-LLM behaviour is fully verified unless a later runtime test proves
> it.** Everything recorded about answer quality, grounding, tool proposal and agent
> planning reflects the deterministic stub only.

---

## 14. Skills / Agents / Approvals

**`SkillExecutionService` boundary.** Skills declare `allowed_tools`; execution is
driven by caller-supplied `tool_calls`. **V2-ADR-009** — AI proposal is not
authorization; **V2-ADR-010** — `ToolExecutionService` is the execution boundary.
**RUNTIME-VERIFIED:** a declared tool with satisfied preconditions → `succeeded`; an
**undeclared** tool → `denied`; an unsatisfied precondition → refused.

**Approval boundary.** **V2-ADR-011** separates skill approval from tool human approval;
**V2-ADR-012** states approval is not authorization. Statuses: PENDING, APPROVED,
REJECTED, EXPIRED, CONSUMED, with lazy expiry, atomic `consume_if_approved`, and a
uniqueness constraint on the open binding.

- **Skill approval bypass — #206** (P0). See §5. PR #247 in flight, lint failing.
- **Execution-record persistence — #208** (P1). See §6.
- **Approval subsystem reachability — #213** (P1). The machinery is complete and its
  state machine is correct; it simply cannot be triggered because no tool declares
  `REQUIRE_HUMAN_APPROVAL`. The tool-level `consume_if_approved` path is therefore
  **BLOCKED — not verifiable end-to-end until an approval-requiring tool exists.**

**Agent bounded orchestration.** **V2-ADR-013** — the agent remains bounded;
**V2-ADR-014** — reuse existing agent run persistence. `AgentExecutionService` sits
strictly above `SkillExecutionService` and holds no tool registry of its own.

**Relevant runtime behaviour.**

- `POST /agent/runs` under the documented default returns `status: "failed"`,
  `error_kind: "agent_capability_unavailable"`. The real cause is that the
  deterministic provider is not decision-capable, **not** a capability gate — the same
  error kind is emitted from both `agent.py:163` and `:174`. → **#228**.
- With an unreachable provider the agent returns an unhandled **HTTP 500** and
  **persists no trace**, while the RAG path fails cleanly. → **#216**.
- Capability enforcement is genuinely wired into four domains: `skill_execution`,
  `tool_execution`, `agent_execution`, `connector_sync`.

**Current UI limitations (verified).** There is **no Agents entry** in the tenant
navigation and no control anywhere to start an agent run, although `POST /agent/runs`
exists and `frontend/src/api/endpoints/agent.js` wraps it. → **#226**.

---

## 15. Frontend Findings

All established by real browser testing against a live backend during the audit.

| Finding | Evidence | Issue |
|---|---|---|
| **Company Brain routing** | `/app/t/{tenant}/company-brain` resolves to `/knowledge/knowledge` (doubled segment, React Router v7 relative resolution from `App.jsx:143-144`) → `GET /api/tenants/{tenant}/knowledge/knowledge` **404** | #225 |
| **Generic 404 skeleton behaviour** | A non-existent document id also 404s and renders the **same permanent loading skeleton** — no error state, no "not found", no retry. A failed request is indistinguishable from a slow one, forever | #225 |
| **Skills execution feedback** | Clicking Execute returns **200** and the tool genuinely runs (`tool_execution_records` +1, `success`), but the dialog closes with **no toast, no result, no status**. Compounded by #208: `skill_execution_records` = 0 and observability reports `total_executions: 0`, so the execution is invisible afterwards too | #208 (+ feedback aspect) |
| **Skills delete UI gap** | Delete button exists but had no accessible name; `DeleteConfirmDialog` rendered `<Dialog>` with no props so the confirmation could never open → deletion impossible. Runtime before fix: `[role=dialog]` count **0**, body scroll lock never engaged | #237 (PR #243) |
| **Inert Approvals filter** | With three approvals (rejected/approved/expired, **none pending**), clicking "pending" left all three displayed and fired **zero** network requests | #224 |
| **Usage tracking display** | Tiles show `AI REQUESTS: N/A`, `TOKENS: N/A`, `AGENT RUNS: N/A` ("Not tracked") while API Requests (44), Tool Calls (11), Webhook Events (10) render real values. The backend **does** expose all three — `/observability/agent-runs` returned a real run; `/observability/llm-usage` returns tokens, latency and cost | #223 |
| **Agents navigation state** | No Agents entry among the 14 sidebar links; no way to start or view a run | #226 |

**Also verified working:** login page and DEV persona sign-in end-to-end; tenant overview
shows real backend data; skill detail page renders the complete definition; the Execute
dialog opens and performs a real execution; the Approvals page renders lazily-computed
**Expired** status correctly; `/auth/me` returns a complete, correct permission set.

**Observation, not filed:** the Execute dialog's tool-calls placeholder shows
`[{"tool_name": "check_health", "input": {}}]` — both the tool name and the field name
are wrong for the skill path (it needs `check_service_health` and `parameters`). Root
cause is the naming inconsistency in **#236**.

---

## 16. Testing Rules

- **Unit tests alone are insufficient for production claims.**
- **Runtime behaviour must be tested for runtime defects.** A test that re-implements
  the code under test proves nothing — see the tautological dev-route tests described
  in #231's PR (#245), which passed while the gate was deliberately broken.
- **Security issues require actual boundary tests**, not simulated ones.
- **Tenant isolation must be tested** — reads, writes, and every distinct scoping path
  (path param *and* query param).
- **Persistence and state transitions must be verified**, not inferred from a 200.
- **Failure paths must be verified.**
- **Avoid destructive tests against the development database unless explicitly isolated.**
  `tests/conftest.py:48` runs `DROP SCHEMA public CASCADE` against whatever
  `DATABASE_URL` names, and its default is the **dev** database URL (→ #232). Always
  pin `DATABASE_URL` to a dedicated test database.
- **Pre-existing test failures must not be falsely attributed to remediation work.**
  Establish the baseline first.
- **Verify fixes against the original reproduction**, not only against new tests written
  alongside the fix.

---

## 17. Completion Definition

> ### Arc V2 is NOT considered complete merely because:
>
> - all GitHub issues are closed, **or**
> - all tests are green, **or**
> - the application starts.

**Final completion requires a requirement-level verification pass across the 433 V2
requirements.**

Every requirement must ultimately be classified as exactly one of:

- **VERIFIED**
- **FIXED + VERIFIED**
- **BLOCKED**
- **OUT OF SCOPE**
- **NOT YET VERIFIED**
- **NOT APPLICABLE**

**Remaining blocked requirements must carry an explicit documented reason.** At audit
close, 43 were blocked:

| Category | Count | Reason |
|---|---|---|
| AI Evaluation (RAG, Agent, LLM, Tools, Security) | 22 | No live LLM provider configured; ADR-002 does not authorize live mode |
| Release Governance / Process / Delivery Process | 16 | Human process requirements, not executable |
| Documentation / Testing / Non-Goals | 5 | Not runtime-testable |

Plus one deliberate refusal recorded separately: the `conftest.py` schema-drop
behaviour (#232) was **not** runtime-tested because verifying it would destroy the
audit environment; the mechanism was confirmed by reading the fixture.

**Areas that must be revisited when their blockers are removed:**

- Real LLM behaviour (answer quality, grounding, tool proposal, agent planning)
- Production configuration (partially addressed by #231 / PR #245)
- Real provider integrations (connectors are simulated-only by default)
- Scale and concurrency beyond the small corpus and 8–10 way tests performed
- Document-format handling **only if** V2 scope changes (currently out of scope, §11)

---

## 18. Current Work State

At the time this file was generated:

- The **audit is complete and frozen**. Do not restart it.
- **Remediation is underway.**
- **Issues are already assigned** (§5–§7). **Do not reassign them.**
- **#246 is a completed remediation PR for #209** — merged, independently verified,
  approved. Use it as the model: reproduce the original defect, fix, verify against the
  original reproduction, document non-blocking follow-ups without inflating them into
  blockers.
- **#207 is likewise complete** via PR #244 (merged, independently verified).
- **Three PRs are open:** #243 (#237, green), #245 (#231, green), #247 (#206, **lint
  failing**).
- Next work should proceed through the already-assigned P0 → P1 → P2 → P3 backlog.

---

## 19. How to continue from this file

A future session should, in order:

1. **Read this file first.** It is the fastest path to the project's state, decisions
   and constraints.

2. **Check current GitHub state before acting.** This is a snapshot taken
   2026-09-21 against `origin/main` @ `525b8b5`. Issue and PR statuses change.
   Start with:

   ```bash
   gh issue list --repo arc-ive/arc --state open --limit 100 \
     --json number,title,labels,assignees
   gh pr list --repo arc-ive/arc --state open --json number,title,author,statusCheckRollup
   git fetch origin && git rev-parse --short origin/main
   ```

3. **Never assume an issue is fixed just because this file says it was.** Re-verify
   against the issue's own reproduction steps. Several findings in this project were
   *corrected* after implementation began — #237's root cause was wrong as filed, and
   two closed issues (#167, #144) were found not to meet their own stated acceptance
   criteria.

4. **Verify current HEAD and linked PRs** before starting work on any issue — someone
   may already have a branch open. Check `gh pr list` for the issue number.

5. **Continue implementation of the already-assigned backlog.** Respect the existing
   assignees. Follow V2-ADR-027's flow and CONTRIBUTING's branch/commit conventions.

6. **Do not restart the exhaustive audit unless explicitly requested.** It is frozen.
   Adding findings is fine; re-deriving the 433-requirement matrix is not.

7. **Do not declare Arc V2 complete until the final 433-requirement verification gate
   passes** (§17). Closing all 36 open issues does not satisfy it, and neither does a
   green CI run.

**Two standing cautions:**

- When testing locally, pin `DATABASE_URL` to a dedicated test database. The suite
  drops the schema of whatever it points at (#232).
- Anything recorded here about AI answer quality reflects the **deterministic provider
  only**. Do not represent it as real-LLM verification (§13).
