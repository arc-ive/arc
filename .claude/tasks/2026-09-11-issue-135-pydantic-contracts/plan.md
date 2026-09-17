# Plan — Issue #135: Pydantic request contracts

- **Requirements:** `./requirements.md`
- **Audit:** `./audit.md`
- **Approved:** 2026-09-11, by dev@zeru.finance ("approved, go ahead")
- **Status:** in progress

## Approach

Declare a Pydantic model for each of the 16 in-scope request bodies, typing enum
fields as the existing domain enums so FastAPI validates and documents them.
Replace hand-written range checks on query parameters with declarative `Query`
bounds. Then, as a separate commit, declare each endpoint's error responses so
OpenAPI reflects what callers actually receive. Finally, teach the frontend to
render the list-shaped 422 detail.

The two 500-producing bugs are fixed as a consequence rather than by a targeted
patch: once a required field is `str` with `min_length=1`, the request never
reaches the code that constructs a domain object from a missing value.

Rejected alternatives:

- **Normalising 422 back to a string `detail`** — keeps the existing frontend and
  tests working untouched, but contradicts the issue's Definition of Done, which
  asks for structured per-field errors. Decided at Q4.
- **A shared `BaseRequest` with `extra="forbid"` everywhere** — would reject
  unknown keys, which is a silent break for any caller sending extra fields.
  Freeze (Q1) says capture today's behaviour; today extra keys are ignored.
- **Modelling the tool-execution payload** — polymorphic by design; only the
  two-field envelope is modelled (Q5).

## Baseline

Run before touching anything, on the branch point `f3f3095`, against `arc_test`.
`APP_ENV=development` matches CI, so the known local-only dev_auth failure (fixed
separately in PR #147) does not pollute the numbers.

| Check | Command | Result before the change |
|---|---|---|
| Backend, full | `APP_ENV=development DATABASE_URL=...arc_test pytest -q` | **1587 passed, 1 skipped, 0 failed** (156s) |
| Frontend | `npm test` in `frontend/` | 107 passed, 11 files (measured earlier this session at the same commit) |
| Lint | `ruff check .` / `ruff format --check .` | clean, 189 files |
| New contract tests vs. unmodified code | `pytest tests/test_request_validation_contracts.py -q` | **14 failed, 4 passed** |

Pre-existing failures: **none** under `APP_ENV=development`. Anything failing
afterwards is a regression.

The 4 contract tests that already pass are correct and must stay passing: one
(`test_create_tenant_with_list_body`) is a case FastAPI already rejects natively,
and three are the valid-input guards for R8. The other 14 prove the gap.

## Steps

Three commits, in order.

### Commit 1 — request models, enums, query bounds

| # | Step | Endpoints | Verified by |
|---|---|---|---|
| S1 | Tenant and user bodies | `POST /tenants`, `PUT /tenants/{id}`, `POST /users` | S9 + existing tenant tests |
| S2 | Membership bodies, `role` as `UserRole` | `POST /tenants/{id}/memberships`, `POST /internal/dev/users/.../memberships` | S9; **requires updating `tests/test_membership_provisioning.py:186`** — see Risks |
| S3 | Skill bodies, `status` as `SkillStatus` | `POST /skills`, `PUT /skills/{id}`, `POST /skills/{id}/execute` | S9 + existing skill tests |
| S4 | Knowledge body, `source` as `KnowledgeSource` | `POST /tenants/{id}/knowledge` | S9 |
| S5 | Intelligence query body (port the existing bool-guard as a validator) | `POST /tenants/{id}/intelligence/query` | S9 + existing intelligence tests |
| S6 | Connector body, `provider` as `ConnectorProvider`; approval decision as `Literal["approve","reject"]`; tool-execute envelope | `POST .../connectors`, `POST .../approvals/{id}/decisions`, `POST .../tools/{name}/execute` | S9 + existing connector/approval/tool tests |
| S7 | Agent and resume bodies, `previous_steps[]` entries modelled with `ToolExecutionStatus` | `POST /agent/runs`, `POST /agent/runs/resume`, `POST /skills/{id}/resume` | S9; interacts with `_require_tenant_permission_from_body` — see Risks |
| S8 | Query parameters: `limit` → `Query(ge=1, le=50)`, `source_type` → `Optional[KnowledgeSource]`, `status` → `Optional[ApprovalStatus]` | knowledge search, approvals list | S9 + existing retrieval/approval tests |
| S9 | Tests: per-endpoint 422 cases (missing field, wrong type, invalid enum) and the five documented 500-inputs | new test module | run against pre-fix code — must fail |

### Commit 2 — error declarations

| # | Step | Verified by |
|---|---|---|
| S10 | Declare `responses={...}` for the error statuses each endpoint can return, across all 51 | S11 |
| S11 | Test asserting `/openapi.json` documents those statuses for a representative sample, including one endpoint per error class | itself, run before S10 exists |

### Commit 3 — frontend

| # | Step | Verified by |
|---|---|---|
| S12 | `errors.js`: render a field-specific message from a list-shaped `detail`; make `isValidation` cover 422 as well as 400 | S13 |
| S13 | Vitest cases for a list-shaped 422, a string-shaped 400, and a network error | run against pre-change `errors.js` — must fail |

## Requirement coverage

| Requirement | Covered by | Proven by |
|---|---|---|
| R1 — bodies validated against a schema | S1-S7 | S9 asserts 422 on malformed bodies per endpoint |
| R2 — 422 with per-field detail | S1-S7 | S9 asserts status 422 **and** that `detail` is a list with a `loc` |
| R3 — the five 500-inputs become 422 | S1, S3, S7 | S9 sends exactly those five payloads; each fails pre-fix with 500 |
| R4 — enum fields validated | S2, S3, S4, S6, S7 | S9 posts an invalid value per enum |
| R5 — query bounds declared | S8 | S9 asserts out-of-range `limit` → 422, and that the handler no longer hand-checks |
| R6 — errors documented in OpenAPI | S10 | S11 reads the generated document |
| R7 — UI shows a useful 422 message | S12 | S13 |
| R8 — valid requests unchanged | all | the full existing suite, which exercises the valid paths of every endpoint |
| R9 — no `response_model=` | — | `grep -c "response_model=" src/` is 0 after the change |

## Verification strategy

- **Backend tests** — a new module of validation cases derived from the
  requirements table, not from the models. Each asserts a status and, for 422s,
  that `detail` is a list. Goes red against pre-change code, which returns 400,
  500, or 200 for those same payloads.
- **Frontend tests** — assert the rendered message for a list-shaped detail. Goes
  red against today's `errors.js`, which produces "Request failed with status 422".
- **Regression** — the whole existing suite is the R8 oracle: it exercises the
  valid path of essentially every endpoint, so a model that wrongly rejects valid
  input will surface there rather than needing new coverage.
- **Independent verifier:** opus subagent, fresh context, adversarial brief,
  given the requirements and the diff.
- **Self-review:** cold read of `git diff` per commit.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A model is stricter than today's hand validation and rejects input that used to work (R8 break) | **High** — this is the main risk of the change | Port each existing hand-check literally rather than writing the model from the field names; the full suite exercises valid paths; no `extra="forbid"` anywhere |
| `tests/test_membership_provisioning.py:186` asserts a string `detail` and will break | **Certain** | Expected and approved at Q4. Update that assertion deliberately, call it out in the PR, and do not touch any other assertion to make something pass |
| `_require_tenant_permission_from_body` already consumes the body of `/agent/runs*`; adding a body model means two readers | Medium | Starlette caches the parsed body, so both work — but verify explicitly with a live request rather than assuming |
| Required-but-empty strings (`{"id": ""}`) still reach `__post_init__` and 500 | Medium | `min_length=1` on required string fields; S9 covers the empty-string case, not only the missing-key case |
| Optional bodies (`Body(default=None)`) become required when modelled | Medium | Keep the parameter optional where it is optional today; S9 asserts a bodyless request still behaves as before |
| The 51-endpoint declarations commit hides a substantive edit | Low | It is mechanical and separate; the diff should contain no logic changes, which the cold review checks |

## Rollback

Revert the branch. No schema, data, or configuration changes are involved. The
change is confined to request parsing, OpenAPI metadata, and one frontend module.
