# Issue #135 — API Contract Audit (Pydantic request/response models)

Audit date: 2026-09-11
Scope: every HTTP endpoint mounted by `arc.main:app`.
Method: read every route-decorated function body in `src/arc/api/` directly (not grep-only), cross-checked against `src/arc/domain/models.py`, `src/arc/security/models.py`, `src/arc/services/tools.py`, and the test suite for shape-locking assertions.

**Files that define routes** (confirmed by grepping for `APIRouter(`, `include_router`, and route decorators across all of `src/`; nothing outside `src/arc/api/` defines a route):

| File | Router | Mounted in `main.py` | Endpoints |
|---|---|---|---|
| `src/arc/api/controllers.py` | `api_router` (no prefix) | always (`app.include_router(api_router)`) | 42 |
| `src/arc/api/auth_routes.py` | `auth_router` (no prefix) | always | 5 |
| `src/arc/api/dev_auth.py` | `dev_auth_router` (prefix `/internal/dev/auth`) | **only if** `APP_ENV=development` | 3 |
| `src/arc/api/dev_controllers.py` | `dev_router` (prefix `/internal/dev`) | **only if** `APP_ENV=development` | 1 |
| `src/arc/api/csrf.py`, `middleware.py`, `correlation.py` | — | — | 0 (middleware/infra only, no routes) |

**Total: 51 HTTP endpoints.**

---

## E. Headline counts

| Metric | Count | / 51 |
|---|---:|---:|
| Total endpoints | 51 | 100% |
| Endpoints with a typed Pydantic **request** body | **1** | 2% |
| Endpoints with `response_model=` declared | **0** | 0% |
| Endpoints whose body is literally annotated `Dict[str, Any]` | **11** | 22% |
| Endpoints whose body is `Optional[Any]` via `Body(default=None)` (hand-checked `isinstance(body, dict)`) | **5** | 10% |
| Endpoints reading a raw byte body via `Request.stream()` (bypasses FastAPI body parsing entirely) | **1** | 2% |
| **Subtotal: endpoints with *some* unvalidated/untyped body** (Dict[str,Any] + Optional[Any] + raw bytes) | **17** | 33% |
| Endpoints with no request body at all (GET/DELETE, or POST with only query/path params) | **33** | 65% |
| Query/path parameters typed as plain `str`/`int` where an existing domain enum or a bound would be correct | **9 distinct params** (see §C) | — |
| Endpoints whose response shape is asserted exactly (`assert set(body) == {...}`) by a passing API test today | **9** (see §D) | 18% |

**On the issue's "20+ endpoints use `Dict[str, Any]`" claim: this appears to be an overcount.** Counting the literal annotation `Dict[str, Any]` gives **11**. Counting every endpoint with *any* kind of untyped/hand-validated JSON body — including the looser `Optional[Any] = Body(default=None)` pattern and the one raw-bytes webhook endpoint — still only reaches **17**. Neither reading supports "20+". See §"Reconciling the issue's claim" below for the full list backing this number.

---

## Full endpoint inventory

Legend for the **Req. Body** column: `none` = no body param; `Dict[str,Any]` = untyped dict, hand-validated with `.get(...)`; `Optional[Any]` = `Body(default=None)`, hand-checked `isinstance(..., dict)`; `Pydantic:X` = typed model X.
Legend for **Resp.**: the function's return-type annotation, then `| RM:yes/no` for whether `response_model=` is set on the decorator (it never is — see §E — so this is omitted per-row and stated once: **no endpoint in the codebase sets `response_model=`**).

### `src/arc/api/controllers.py` (`api_router`, no prefix) — 42 endpoints

| # | Method & Path | Location | Req. Body | Response annotation | Notes |
|---|---|---|---|---|---|
| 1 | `GET /health` | controllers.py:241 | none | `Dict[str, str]` | Trivial; body-locked by 3 tests (`{"status":"ok"}`). |
| 2 | `GET /auth/me` | controllers.py:247 | none | `Dict[str, Any]` | Hand-built dict (id/email/role/permissions/memberships). `permissions` set is shape-locked by test (§D). |
| 3 | `POST /tenants` | controllers.py:296 | `Dict[str,Any]` (`tenant_data`) | `Dict[str, Any]` | **Bug**: `Tenant(id=tenant_data.get("id"), name=tenant_data.get("name"), ...)` is constructed *before* any try/except; if `id`/`name` is missing or `""`, `Tenant.__post_init__` (domain/models.py:135-139) raises `ValueError`, which is **not** caught here → falls through to the global handler → generic `500`, not 400/422. See finding **BUG-1**. |
| 4 | `GET /platform/tenants` | controllers.py:342 | none | `List[Dict[str, Any]]` | — |
| 5 | `GET /tenants/{tenant_id}` | controllers.py:367 | none | `Dict[str, Any]` | — |
| 6 | `PUT /tenants/{tenant_id}` | controllers.py:394 | `Dict[str,Any]` (`tenant_data`) | `Dict[str, Any]` | Safe pattern: every field uses `.get(key, existing.value)` fallback, so a *missing* key never crashes. An **explicitly empty string** (`{"name": ""}`) still hits the same `Tenant.__post_init__` ValueError → 500 (narrower version of BUG-1). Response shape is exactly asserted by a test (§D). |
| 7 | `POST /users` | controllers.py:435 | `Dict[str,Any]` (`user_data`) | `Dict[str, Any]` | Same construct-before-try pattern as #3: `User(id=.get("id"), email=.get("email"), ...)` uncaught → 500 on missing/empty `id`/`email`. Same class as **BUG-1**. |
| 8 | `GET /platform/users` | controllers.py:469 | none | `List[Dict[str, Any]]` | Response shape exactly asserted by test (§D). |
| 9 | `GET /tenants/{tenant_id}/users` | controllers.py:494 | none | `List[Dict[str, Any]]` | — |
| 10 | `POST /tenants/{tenant_id}/memberships` | controllers.py:519 | `Dict[str,Any]` (`membership_data`) | `Dict[str, Any]` | **Good** hand-validation example: explicitly checks `if not user_id: raise HTTPException(422, "user_id is required")` (catches both missing and empty string) and wraps `role` in `try/except ValueError` → 400. `role` is plain string parsed into `UserRole` enum by hand (§C). This is the exact pattern a Pydantic model + enum field replaces cleanly, and it already *works correctly* (unlike #3/#7) — see risk ranking below. |
| 11 | `DELETE /tenants/{tenant_id}/memberships/{user_id}` | controllers.py:565 | none | `Dict[str, Any]` | Returns `{"detail": "Membership removed"}`. |
| 12 | `GET /users/{user_id}/tenants` | controllers.py:587 | none | `List[Dict[str, Any]]` | Self-only (403 if `user_id` != caller). |
| 13 | `POST /skills` | controllers.py:646 | `Dict[str,Any]` (`skill_data`) | `Dict[str, Any]` | `tenant_id` is a **query parameter**, not a path segment (route is just `/skills`) — inconsistent with every `/tenants/{tenant_id}/...` resource elsewhere in the file. `status` field hand-parsed into `SkillStatus` (caught, 400). **Same BUG-1 pattern**: `Skill(id=..., name=skill_data.get("name"), purpose=skill_data.get("purpose"), ...)` constructed *outside* any try/except → missing/empty `name`/`purpose` → uncaught `ValueError` → 500. |
| 14 | `GET /skills` | controllers.py:698 | none | `List[Dict[str, Any]]` | `tenant_id` is a query parameter (same inconsistency as #13). |
| 15 | `GET /skills/{skill_id}` | controllers.py:717 | none | `Dict[str, Any]` | `tenant_id` is a query parameter. |
| 16 | `PUT /skills/{skill_id}` | controllers.py:741 | `Dict[str,Any]` (`skill_data`) | `Dict[str, Any]` | `tenant_id` is a query parameter. Uses `dataclasses.replace(existing, name=skill_data.get("name", existing.name), ...)` — safe against *missing* keys, still vulnerable to an *explicit empty string* the same way as #6. `status` hand-parsed (caught, 400). |
| 17 | `DELETE /skills/{skill_id}` | controllers.py:802 | none | `None` (204 No Content) | `tenant_id` is a query parameter. |
| 18 | `POST /skills/{skill_id}/execute` | controllers.py:859 | `Optional[Any]` (`Body(default=None)`) | `Dict[str, Any]` | `tenant_id` query param. Hand-checks `isinstance(body, dict)` → 400; then `body.get("tool_calls")`, `body.get("satisfied_preconditions", [])` passed straight to the service with no shape validation at the HTTP layer (deeper validation happens in `SkillExecutionService`). `NotFoundError`/`ValueError` from the service are caught → 404/400. |
| 19 | `POST /agent/runs` | controllers.py:984 | `Optional[Any]` (`Body(default=None)`) | `Dict[str, Any]` | **Third** way `tenant_id` is supplied in this API: here it comes from the **request body** (via the `_require_tenant_permission_from_body` dependency, controllers.py:939-980), not path or query. That dependency itself hand-validates `isinstance(body, dict)` and `tenant_id` non-empty str (400s). `goal` is passed to the service unchecked at the HTTP layer. Best-effort trace persistence is wrapped in a bare `except Exception` (intentional, documented). |
| 20 | `GET /tenants/{tenant_id}/knowledge/search` | controllers.py:1113 | none | **no return annotation at all** | `query: str` required (no `min_length`); `limit: int = 5` has **no declared bounds** — hand-checked `if limit < 1 or limit > 50: raise HTTPException(400)` inside the body instead of `Query(ge=1, le=50)`. `source_type: Optional[str] = Query(default=None)` is hand-parsed into `KnowledgeSource` (§C) instead of being typed as the enum directly. This is the closest literal match to the issue's own example ("a `limit` with no bounds", "a `status` filter"). Also the **only** handler in the file with no `->` annotation at all *and* no `response_model` — fully undocumented in OpenAPI today. Response shape (`matches[0]` keys) is exactly asserted by a test (§D). |
| 21 | `POST /tenants/{tenant_id}/intelligence/query` | controllers.py:1195 | `Optional[Any]` (`Body(default=None)`) | `Dict[str, Any]` | Best-written hand-validation in the file: checks body is a dict, `query` is a non-empty stripped string, and `limit` is a non-bool int in `[1,50]` (explicitly guards against `bool` being an `int` subclass). Thorough but 100% replicable by a Pydantic model with a custom validator — good Pydantic candidate, low behavioral risk since already correct. |
| 22 | `POST /tenants/{tenant_id}/knowledge` | controllers.py:1267 | `Dict[str,Any]` (`knowledge_data`) | `Dict[str, Any]` | `source` hand-parsed into `KnowledgeSource` (caught `TypeError`/`ValueError` → 400). `provenance`/`content`/`version`/`external_id` passed unchecked to the service, but the service call **is** wrapped in `try/except ValueError → 400`, so (unlike #3/#7/#13) missing required fields correctly surface as 400, not 500. |
| 23 | `GET /tenants/{tenant_id}/knowledge/{document_id}` | controllers.py:1336 | none | `Dict[str, Any]` | — |
| 24 | `GET /tenants/{tenant_id}/knowledge` | controllers.py:1363 | none | `List[Dict[str, Any]]` | — |
| 25 | `GET /tenants/{tenant_id}/tools` | controllers.py:1411 | none | `List[Dict[str, Any]]` | Catalog is platform-owned/code-defined (currently exactly one tool, `check_service_health`). |
| 26 | `POST /tenants/{tenant_id}/tools/{name}/execute` | controllers.py:1432 | `Dict[str,Any]` (`body`, required) | `Dict[str, Any]` | **Important nuance**: `body["input"]` is untyped at the HTTP layer *by necessary design* — it's dispatched by `name` to one of N platform tools, each with its own Pydantic `input_model`/`output_model` (see §A, `services/tools.py`). `ToolExecutionService.execute_tool` already does `tool.input_model.model_validate(raw_input)` internally (tools.py:609/717) and raises `ToolValidationError` → 400. **A single static `response_model=`/request model on this route would be wrong** given the current polymorphic-by-tool-name design — flagged as a case to leave alone or handle very differently from the others (see risk ranking). |
| 27 | `GET /tenants/{tenant_id}/connectors` | controllers.py:1504 | none | `List[Dict[str, Any]]` | — |
| 28 | `POST /tenants/{tenant_id}/connectors` | controllers.py:1524 | `Dict[str,Any]` (`connector_data`) | `Dict[str, Any]` | `provider` hand-parsed into `ConnectorProvider` (caught → 400); `name` hand-checked non-empty string (caught → 400). This handler's manual validation is correct/complete (service-level `ConnectorConfig` construction cannot receive an invalid input from here) — low risk. |
| 29 | `POST /tenants/{tenant_id}/connectors/{connector_id}/sync` | controllers.py:1568 | none | `Dict[str, Any]` | — |
| 30 | `POST /webhooks/{endpoint_id}/events` | controllers.py:1669 | **raw bytes** via `Request.stream()`, capped by `_read_capped_body` (controllers.py:1628) | `Dict[str, Any]` | Deliberately bypasses FastAPI's JSON body parsing (HMAC verification needs exact raw bytes; see docstring). Not RBAC-gated by design (machine-to-machine, ADR-001). Not a good candidate for a Pydantic *request* model as-is (pre-auth raw-bytes handling is load-bearing), though the *response* shape could still get a model. |
| 31 | `GET /tenants/{tenant_id}/webhooks/events` | controllers.py:1723 | none | `List[Dict[str, Any]]` | — |
| 32 | `POST /tenants/{tenant_id}/webhooks/process` | controllers.py:1745 | none (`event_id` is a required **query** param) | `Dict[str, Any]` | `event_id: str = Query(..., description=...)` — required, correctly untyped (opaque sender ID, no enum applies). Returns `result` (a `Dict[str, Any]`) straight from `WebhookPipelineService.process` with no controller-side re-shaping — response shape is whatever the service returns, not documented anywhere. |
| 33 | `GET /tenants/{tenant_id}/observability/usage-summary` | controllers.py:1784 | none | `Dict[str, Any]` | **Correctly bounded** query param: `hours: int = Query(default=24, ge=1, le=168)` — this is the pattern the other unbounded `limit`/`hours`-style params (e.g. #20) should follow. Returns the service's dict directly. Response shape exactly asserted by test, including nested `http`/`tools`/`connectors`/`webhooks`/`approvals` sub-keys (§D) — **high test coverage of exact shape**. |
| 34 | `GET /platform/observability/summary` | controllers.py:1806 | none | `Dict[str, Any]` | Same `hours` bounding pattern as #33. Test asserts *absence* of tenant identifiers/lists rather than an exact key set. |
| 35 | `GET /observability/health` | controllers.py:1824 | none | `Dict[str, Any]` | Returns service dict directly. `components.<name>` shape (`{"status": ...}`) exactly asserted by test (§D). |
| 36 | `GET /tenants/{tenant_id}/observability/agent-runs` | controllers.py:1841 | none | **`list`** (bare, unparameterized — not `List[Dict[str, Any]]` like every sibling list endpoint) | Same `hours` bounding pattern as #33. Inconsistent/incomplete annotation. |
| 37 | `GET /tenants/{tenant_id}/observability/agent-runs/{record_id}` | controllers.py:1862 | none | `Dict[str, Any]` | — |
| 38 | `GET /tenants/{tenant_id}/approvals` | controllers.py:1932 | none | `List[Dict[str, Any]]` | `status_filter: Optional[str] = Query(default=None, alias="status")` — **exact match** for the issue's own "a `status` filter" example: plain `str`, hand-parsed via `try: ApprovalStatus(status_filter) except ValueError: raise HTTPException(400)`. Directly replaceable by `Optional[ApprovalStatus]` as the param type. |
| 39 | `GET /tenants/{tenant_id}/approvals/{approval_id}` | controllers.py:1959 | none | `Dict[str, Any]` | Response shape exactly asserted by test (§D), explicitly checking the audit-sensitive digest/raw-arguments fields are *absent*. |
| 40 | `POST /tenants/{tenant_id}/approvals/{approval_id}/decisions` | controllers.py:1978 | `Dict[str,Any]` (`decision_data`) | `Dict[str, Any]` | `decision` field hand-checked via `if decision_raw not in ("approve", "reject"): raise HTTPException(400)` — a plain 2-value string literal, ideal `Literal["approve","reject"]` or enum field candidate. |
| 41 | `POST /skills/{skill_id}/resume` | controllers.py:2025 | `Optional[Any]` (`Body(default=None)`) | `Dict[str, Any]` | `tenant_id` query param (same inconsistency as #13-17). Hand-validates `approval_id` (non-empty str), `tool_calls` (non-empty list), `resume_from_step` (non-negative int) — all correctly caught, 400. **Bug**: the `previous_steps` reconstruction loop (controllers.py:2073-2084) reads `raw_step["sequence"]`, `raw_step["tool_name"]`, `ToolExecutionStatus(raw_step["status"])` by **direct indexing outside any try/except** — a malformed entry (missing key, or an invalid `status` value) raises `KeyError`/`ValueError` that is **not caught** (the `try/except NotFoundError/ValueError` below only wraps the later `execution_service.execute(...)` call) → generic `500`. See **BUG-2**. |
| 42 | `POST /agent/runs/resume` | controllers.py:2107 | `Optional[Any]` (`Body(default=None)`) | `Dict[str, Any]` | Identical structure and identical **BUG-2** as #41 (controllers.py:2156-2167), plus its own hand-checks for `approval_id`/`skill_id`/`tool_calls`/`resume_from_step`. Also note: `tenant_id` for this endpoint again comes from the **body** via `_require_tenant_permission_from_body`, the third tenant-id-location pattern. |

### `src/arc/api/auth_routes.py` (`auth_router`, no prefix) — 5 endpoints

| # | Method & Path | Location | Req. Body | Response annotation | Notes |
|---|---|---|---|---|---|
| 43 | `GET /auth/google` | auth_routes.py:158 | none | `RedirectResponse` | Not a JSON contract; a 302 redirect. Not in scope for Pydantic modeling. |
| 44 | `GET /auth/callback` | auth_routes.py:203 | none (`code`, `state`, `error`: `Optional[str] = Query(None)`) | `RedirectResponse` | Query params are correctly untyped opaque OAuth values (no enum applies). Not a JSON contract either. |
| 45 | `GET /auth/workspaces` | auth_routes.py:359 | none | `Dict[str, Any]` | `{"workspaces": [...], "count": N}`. |
| 46 | `POST /auth/logout` | auth_routes.py:400 | none | `Dict[str, str]` | `{"status": "ok"}`. |
| 47 | `POST /auth/logout-all` | auth_routes.py:422 | none | `Dict[str, str]` | `{"status": "ok"}`. |

Note: `GET /auth/me` (the endpoint the issue's author probably expects to live here) is actually defined in `controllers.py:247`, not `auth_routes.py` — the two "auth" surfaces are split across files.

### `src/arc/api/dev_auth.py` (`dev_auth_router`, prefix `/internal/dev/auth`) — 3 endpoints, **mounted only when `APP_ENV=development`**

| # | Method & Path | Location | Req. Body | Response annotation | Notes |
|---|---|---|---|---|---|
| 48 | `GET /internal/dev/auth/reference-users` | dev_auth.py:194 | none | `Dict[str, Any]` | Static in-memory allowlist dump. |
| 49 | `GET /internal/dev/auth/reference-personas` | dev_auth.py:204 | none | `Dict[str, Any]` | Static in-memory list dump. |
| 50 | `POST /internal/dev/auth/login` | dev_auth.py:215 | **`Pydantic:DevLoginRequest`** (dev_auth.py:185-186) | `Dict[str, Any]` | The **only** endpoint in the whole codebase with a typed Pydantic request body. `{"status": "ok", "user_id": ..., "session_id": ...}`. Missing-body / missing-`user_id` correctly return native FastAPI `422`s (tests at `tests/test_dev_auth.py:206,214`). |

### `src/arc/api/dev_controllers.py` (`dev_router`, prefix `/internal/dev`) — 1 endpoint, **mounted only when `APP_ENV=development`**

| # | Method & Path | Location | Req. Body | Response annotation | Notes |
|---|---|---|---|---|---|
| 51 | `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships` | dev_controllers.py:32 | `Dict[str,Any]` (`membership_data`) | `Dict[str, Any]` | Same `role` hand-parse-to-`UserRole` pattern as controllers.py #10, but **without** the `user_id`-required check (not needed here — `user_id`/`tenant_id` are path params, not body fields). |

---

## A. Pydantic models that already exist in the codebase

A repo-wide search for `BaseModel` (`grep -rln BaseModel src/arc/`) found exactly **two files** that define Pydantic models — nothing else in the codebase uses Pydantic today outside these:

| Model | Location | Used by |
|---|---|---|
| `DevLoginRequest` | `src/arc/api/dev_auth.py:185-186` (`user_id: str`) | Request body of `POST /internal/dev/auth/login` (dev_auth.py:217) — the **only** FastAPI route in the app with a typed request body. |
| `ServiceHealthInput` | `src/arc/services/tools.py:370-373` (no fields, `extra="forbid"`) | **Not** a FastAPI request model. It's the `input_model` for the `check_service_health` tool definition (`SERVICE_HEALTH_TOOL`, tools.py:416-424+), validated dynamically inside `ToolExecutionService.execute_tool` (tools.py:609, 717) via `tool.input_model.model_validate(raw_input)` — one layer below the generic `POST /tenants/{tenant_id}/tools/{name}/execute` HTTP endpoint (#26 above), which itself takes `Dict[str, Any]`. |
| `ServiceHealthEntry` | `src/arc/services/tools.py:376-380` (`name: str`, `status: str`) | Nested inside `ServiceHealthOutput`. |
| `ServiceHealthOutput` | `src/arc/services/tools.py:383-390` (`tenant_id: str`, `services: List[ServiceHealthEntry]`) | `output_model` for the same tool; used for the tool catalog's `output_schema` (via `.model_json_schema()`, tools.py:229) and presumably to validate handler output before it's returned. |

**Implication for issue #135's scope**: the AI-Tools subsystem already has a working, dynamic, per-tool Pydantic validation pattern (`ToolDefinition.input_model` / `output_model`) that is architecturally *separate* from a FastAPI route's own `request`/`response_model`. `POST /tenants/{tenant_id}/tools/{name}/execute` (#26) dispatches to one of N tools by name — today there is exactly **one** registered tool (`SERVICE_HEALTH_TOOL`) — so a single static request/response model on that route would be **wrong** for the general case even though it would happen to work today with one tool. This is the one endpoint in the audit where "just add a Pydantic model" is not the obviously correct move; it needs a design decision (e.g., a discriminated/generic envelope, or leaving `input`/`output` as `Dict[str, Any]` deliberately and documenting why).

---

## B. Error response shape — is it consistent?

**Short answer: the envelope key (`detail`) is universally consistent, but the *shape of its value* is not, and the inconsistency lands specifically on 422s.**

Verified by reading `src/arc/main.py` in full, reading `src/arc/api/csrf.py`, and confirming FastAPI 0.141.1's actual registered default handlers in the project's own venv (`.venv-demo`):

1. **`arc.main` registers exactly two custom handlers** (main.py:39-70):
   - `DuplicateKeyError` → `JSONResponse(409, {"detail": str(exc)})`
   - `Exception` (catch-all) → re-raises if it's an `HTTPException` (letting Starlette's default handler run), otherwise logs and returns `JSONResponse(500, {"detail": "Internal server error"})`.
   - No handler is registered for `RequestValidationError`.

2. **FastAPI pre-registers its own handlers at `FastAPI()` construction time**, before `arc.main`'s handlers are added. Confirmed directly against the installed package:
   ```
   {StarletteHTTPException: http_exception_handler,
    RequestValidationError: request_validation_exception_handler,
    WebSocketRequestValidationError: websocket_request_validation_exception_handler}
   ```
   Starlette's exception middleware looks up the handler by **exact exception type first**; only if there's no exact match does it walk the MRO. So `RequestValidationError` (raised by FastAPI itself for bad path/query/body params) is caught by FastAPI's own exact-type handler, never by `arc.main`'s later-registered `Exception` handler.
   FastAPI's default handler (`fastapi/exception_handlers.py`, read directly from the installed package):
   ```python
   async def request_validation_exception_handler(request, exc):
       return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})
   ```
   `exc.errors()` is a **list of structured error objects** (each with `type`, `loc`, `msg`, `input`, ...).

3. **Handler-level manual `raise HTTPException(status_code=422, detail="...")`** (e.g. `create_membership`, controllers.py:534-537) goes through Starlette's *other* pre-registered handler (`http_exception_handler`), which returns `{"detail": exc.detail}` — here `exc.detail` is whatever string the handler passed.

**Net effect: two different HTTP 422 shapes exist side by side, distinguished only by which code path produced them:**

| Source | Status | Body shape |
|---|---|---|
| FastAPI's own parameter/body validation (e.g. `hours` out of `Query(ge=1,le=168)` bounds, a required `Query(...)` missing, a non-object JSON body posted where a dict is expected) | 422 | `{"detail": [{"type": ..., "loc": [...], "msg": ..., "input": ...}, ...]}` (list) |
| A handler's own `raise HTTPException(422, detail="...")` (only one place does this today: `create_membership`, controllers.py:534-537) | 422 | `{"detail": "user_id is required"}` (string) |
| Any other `raise HTTPException(4xx/5xx, detail="...")` throughout the app (the overwhelming majority of error paths) | varies | `{"detail": "<string>"}` |
| `DuplicateKeyError` → custom handler | 409 | `{"detail": "<string>"}` |
| Unhandled exception → global handler | 500 | `{"detail": "Internal server error"}` (fixed string, never leaks internals — verified by `tests/test_global_exception_handler.py`) |
| CSRF middleware failures (`src/arc/api/csrf.py:87-129`) — these run *before* routing, so they bypass the exception handlers entirely and build `JSONResponse` directly | 403 | `{"detail": "<string>"}` |

This is corroborated by the test suite itself: `tests/test_membership_provisioning.py:186` asserts `"user_id is required" in response.json()["detail"]`, which only makes sense if `detail` is a string — while `tests/test_observability_api.py:190-199` and `tests/test_webhook_pipeline_api.py:172` and `tests/test_tool_api.py:346-347` all assert `status_code == 422` for FastAPI-native validation failures (out-of-bounds `hours`, missing required `event_id` query param, a JSON list posted where an object was expected) without ever inspecting `detail`'s internal shape — none of those tests could safely do `"x" in response.json()["detail"]` the way the membership test does, because their `detail` is a list, not a string.

**Practical consequence for #135**: introducing Pydantic request models will *increase* how often the list-shaped 422 fires (replacing today's hand-written string-shaped 400s in many of the "Notes" cells above with FastAPI's native list-shaped 422). Any frontend code that currently does something like `error.response.data.detail` as a display string will break for those specific endpoints unless the frontend already branches on `Array.isArray(detail)`. This is worth surfacing to the user explicitly before scoping — it's a real behavior change, not just an internal cleanup, unless a custom `RequestValidationError` handler is added at the same time to normalize the shape.

---

## C. Existing enums accepted as plain strings today

All enums below are defined in `src/arc/domain/models.py` unless noted. "Accepted as plain string" means: an endpoint parses a client-supplied `str` into the enum by hand (`Enum(value)` wrapped in `try/except`) rather than declaring the parameter/field's type as the enum itself (which is what would make FastAPI/Pydantic validate and document it automatically).

| Enum | Values | Where it's accepted as a plain string today |
|---|---|---|
| `UserRole` | `owner`, `member`, `viewer` | `POST /tenants/{tenant_id}/memberships` body field `role` (controllers.py:539-545); `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships` body field `role` (dev_controllers.py:50-56) |
| `SkillStatus` | `active`, `inactive`, `archived` | `POST /skills` body field `status` (controllers.py:665-667); `PUT /skills/{skill_id}` body field `status` (controllers.py:766-768) |
| `KnowledgeSource` | `policy`, `procedure`, `incident_report`, `troubleshooting`, `internal_knowledge`, `solution` | `GET /tenants/{tenant_id}/knowledge/search` **query param** `source_type` (controllers.py:1117, 1150-1159) — this is the literal "status/type filter typed as `str`" case the issue describes; `POST /tenants/{tenant_id}/knowledge` body field `source` (controllers.py:1297-1303) |
| `ConnectorProvider` | `slack`, `github`, `google_drive`, `linear` | `POST /tenants/{tenant_id}/connectors` body field `provider` (controllers.py:1541-1546) |
| `ApprovalStatus` | `pending`, `approved`, `rejected`, `expired`, `consumed` | `GET /tenants/{tenant_id}/approvals` **query param** `status` (aliased from `status_filter`, controllers.py:1934, 1946-1953) — the other exact "status filter" match; also used internally (not from a client string) at the decision endpoint |
| `ToolExecutionStatus` | `success`, `failed` | `POST /skills/{skill_id}/resume` and `POST /agent/runs/resume`, inside each `previous_steps[]` entry: `ToolExecutionStatus(raw_step["status"])` (controllers.py:2079, 2162) — **not even wrapped in try/except**, see BUG-2 below |
| *(ad hoc, no named enum)* | `"approve"` / `"reject"` | `POST /tenants/{tenant_id}/approvals/{approval_id}/decisions` body field `decision` (controllers.py:1995-2000) — a natural `Literal["approve","reject"]` candidate; maps onto `ApprovalStatus.APPROVED`/`REJECTED` internally but isn't itself one of the named enum values end-to-end |

**Enums that exist but are *not* client-input-driven anywhere in the API** (so they are not candidates for request-side enum validation, only worth knowing about): `ConnectorStatus`, `RetrievalMethod` (only one value, `dense_semantic`, always server-selected), `ToolRiskLevel`, `ToolAuthorizationOutcome`, `ConnectorSyncStatus`, `WebhookEventStatus`, `SkillExecutionStatus`, `AgentRunStatus` — all of these are server-assigned *output* statuses, never parsed from a request. `ApplicationRole` (`src/arc/security/models.py:17-29`) is likewise never accepted from a request; it's assigned out-of-band via the `APPLICATION_ROLE_ASSIGNMENTS` environment variable.

---

## D. Endpoints whose response shape is already an effective contract (test-locked)

Found via `grep -rn "assert set(" tests/*.py` (23 hits total) and manually classifying each as an API-level test (goes through `TestClient`/`http_client` against a real route) versus a service/unit-level test. **9 endpoints** have at least one *API-level* test that asserts an exact key set on the JSON response. Changing these response shapes — even in backward-compatible-seeming ways like adding a field — will fail these tests today, so they are the highest-friction targets for any reshaping:

| Endpoint | Test | What's locked |
|---|---|---|
| `GET /auth/me` | `tests/test_auth_me.py:53` | exact `set(body["permissions"])` |
| `PUT /tenants/{tenant_id}` | `tests/test_tenant_company_config.py:158-166` | exact `set(body)` (full tenant shape) |
| `GET /platform/tenants` | `tests/test_platform_tenant_listing.py:149` | exact `set(target_tenant.keys())` |
| `GET /platform/users` | `tests/test_platform_user_listing.py:155` | exact `set(target_user.keys())` |
| `GET /tenants/{tenant_id}/knowledge/search` | `tests/test_retrieval_api.py:169-176` | exact `set(matches[0])` |
| `GET /tenants/{tenant_id}/observability/usage-summary` | `tests/test_observability_api.py:242-267` | exact `set(body)` **and** exact key sets of nested `body["http"]`, `body["tools"]`, `body["connectors"]`, `body["webhooks"]`, `body["approvals"]` — the single most tightly-specified response in the app |
| `GET /observability/health` | `tests/test_observability_api.py:298` | exact `set(body["components"][component])` for each component |
| `GET /tenants/{tenant_id}/approvals/{approval_id}` | `tests/test_approval_api.py:260-273` | exact `set(body)`, plus an explicit assertion that the digest/raw-arguments fields are *absent* |
| `POST /agent/runs` | `tests/test_agent_api.py:250-255` | exact `set(step.keys())` for each entry in `body["steps"]` |

`GET /health` is additionally locked by full-equality (`response.json() == {"status": "ok"}`) in three separate test files (`test_health.py:12`, `test_global_exception_handler.py:100`, `test_observability_api.py:328`), though this one is so trivial it's not a meaningful risk.

Other `assert set(...)` hits in the test suite (`test_agent_service.py`, `test_knowledge_service.py`, `test_pii.py`, `test_rbac.py`, `test_observability_service.py`, `test_webhook_domain_config.py`) were read and confirmed to be **service/unit-level or config-parsing tests**, not exercising the HTTP layer — they don't constrain any endpoint's wire shape directly, so they're excluded from the table above.

---

## Reconciling the issue's "20+ endpoints use `Dict[str, Any]`" claim

Full list of the **11** endpoints whose body parameter is annotated literally `Dict[str, Any]`:
`POST /tenants`, `PUT /tenants/{tenant_id}`, `POST /users`, `POST /tenants/{tenant_id}/memberships`, `POST /skills`, `PUT /skills/{skill_id}`, `POST /tenants/{tenant_id}/knowledge`, `POST /tenants/{tenant_id}/tools/{name}/execute`, `POST /tenants/{tenant_id}/connectors`, `POST /tenants/{tenant_id}/approvals/{approval_id}/decisions`, `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships`.

Adding the **5** endpoints using the looser `Optional[Any] = Body(default=None)` pattern (`POST /skills/{skill_id}/execute`, `POST /agent/runs`, `POST /tenants/{tenant_id}/intelligence/query`, `POST /skills/{skill_id}/resume`, `POST /agent/runs/resume`) and the **1** raw-bytes webhook endpoint gets to **17**.

Either number is short of "20+". If the issue author meant to include GET endpoints whose *response* is `Dict[str, Any]`/`List[Dict[str, Any]]` (there are many — see the inventory), the claim would be true but is a different, larger, and much lower-risk category (typing an output shape is safe; it can't reject a request that used to be accepted). **Recommend clarifying with the user which of these three readings the issue intended** before sizing the work — the number materially changes the estimate.

---

## Notable bugs found while reading (not just style issues)

These are real behavioral defects, found by tracing exact control flow, that a Pydantic request model would fix as a *side effect* of the refactor — worth calling out separately from pure "add typing" cleanup because fixing them changes observable API behavior (500 → 400/422) and should be called a bug fix, not a pure refactor, when it lands.

**BUG-1 — required-field validation is skipped entirely, causing 500 instead of 400/422, on 3 create endpoints.**
`POST /tenants` (controllers.py:309-313), `POST /users` (controllers.py:445-450), and `POST /skills` (controllers.py:669-686) each construct a domain dataclass directly from `.get(...)` calls on the raw request dict, and that construction happens **before** the function's own `try/except` block starts. The dataclasses' `__post_init__` methods (`Tenant` at domain/models.py:135-139, `User` at domain/models.py:157-161, `Skill` at domain/models.py:679-687) do raise `ValueError` for missing/empty required fields (`id`, `name`, `email`, `purpose`) — but nothing in the request path catches that `ValueError`, so it propagates to `arc.main`'s global handler and comes back as a generic `500 {"detail": "Internal server error"}`. Compare with `POST /tenants/{tenant_id}/memberships` (controllers.py:532-537), which explicitly checks `if not user_id: raise HTTPException(422, ...)` before doing anything else — that one behaves correctly. `PUT /tenants/{tenant_id}` and `PUT /skills/{skill_id}` are partially protected (they default missing keys to the *existing* record's value) but still hit the same bug if a field is present with an explicit empty-string value.

**BUG-2 — malformed `previous_steps` entries crash to 500 on both resume endpoints.**
`POST /skills/{skill_id}/resume` (controllers.py:2073-2084) and `POST /agent/runs/resume` (controllers.py:2156-2167) each rebuild a list of `SkillExecutionStepOutcome` from client-supplied `previous_steps` entries using **direct dict indexing** (`raw_step["sequence"]`, `raw_step["tool_name"]`) and an **unwrapped** enum parse (`ToolExecutionStatus(raw_step["status"])`) — this loop runs *before* the function's `try/except NotFoundError/ValueError` block starts. A client omitting a key, or supplying an invalid `status` value, gets `KeyError`/`ValueError` → uncaught → generic `500`, even though every sibling field in the same request body (`approval_id`, `tool_calls`, `resume_from_step`) is hand-validated correctly and returns a clean 400.

Both bugs share the same root cause the issue is trying to fix: hand-rolled dict access with no systematic guarantee that every code path is wrapped in validation. A Pydantic model for the request body would make both bugs structurally impossible (Pydantic validates the whole shape up front, before any handler code runs), which is a strong independent argument for prioritizing exactly these endpoints — not just for API-contract cleanliness but because they are currently returning the wrong status code for bad input.

---

## Risk ranking: endpoints to touch with most care

1. **`GET /tenants/{tenant_id}/observability/usage-summary`** (controllers.py:1784) — the most exhaustively shape-tested endpoint in the app (6 separate `assert set(...)` checks across parent + 5 nested objects, §D). Any response model must match this exactly, including nested aggregate objects; a mismatch on optional/`None` fields or key naming will fail tests immediately. Low ambiguity about the *target* shape (it's fully spelled out in tests), but zero tolerance for drift.
2. **`POST /tenants/{tenant_id}/tools/{name}/execute`** (controllers.py:1432) — the one endpoint where "just add a Pydantic model" is architecturally wrong as stated. It's a dynamic dispatch over a tool catalog (currently 1 tool, designed for N), each with its own `input_model`/`output_model` already living in `services/tools.py`. Needs a deliberate decision (generic envelope vs. leave as `Dict[str, Any]`), not a mechanical fix — highest chance of the "blindly rewrite" mistake the issue explicitly warns against.
3. **`POST /agent/runs` and `POST /agent/runs/resume`** (controllers.py:984, 2107) — `tenant_id` is sourced from the request **body** here (via `_require_tenant_permission_from_body`), the only two endpoints in the API with that pattern (everywhere else it's a path segment, and the `/skills*` family uses a query param instead — three different conventions across one API). A body-shape change here touches both the tenant-resolution dependency and the payload in a way that's easy to get subtly wrong (e.g., forgetting the dependency also reads `body["tenant_id"]` independently of whatever Pydantic model gets added to the route itself).
4. **`POST /skills/{skill_id}/resume` and `POST /agent/runs/resume`** (controllers.py:2025, 2107) — the most structurally complex hand-rolled bodies in the app (5 top-level fields, one of which, `previous_steps`, is itself a list of objects with an enum field), and the site of BUG-2. High value to fix, but the most surface area to get exactly right, including the resume-continuation semantics (`resume_from_step`, `previous_steps` echoing prior results back to the server) which a naive model might not preserve faithfully.
5. **`GET /tenants/{tenant_id}/approvals/{approval_id}`** (controllers.py:1959) — response shape is test-locked (§D) *and* the test explicitly asserts sensitive fields (`arguments_digest`, raw arguments) are **absent**. A `response_model` here is exactly the right tool (it would enforce that omission structurally instead of relying on the serializer function remembering not to include them) but must be built to deliberately exclude those fields, not just mirror the domain dataclass 1:1 — an automatic/naive model generation here could accidentally leak the digest.

Lower-risk, good first targets precisely because they're *already* nearly correct and well-covered: `POST /tenants/{tenant_id}/memberships` and `POST /internal/dev/users/{user_id}/tenants/{tenant_id}/memberships` (validation logic is already right, just needs to move into a model), and `POST /tenants/{tenant_id}/connectors` (same).
