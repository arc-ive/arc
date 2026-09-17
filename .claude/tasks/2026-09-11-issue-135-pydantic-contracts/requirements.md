# Requirements — Issue #135: Pydantic API request contracts

- **Date:** 2026-09-11
- **Asked by:** dev@zeru.finance
- **Status:** draft

## The ask, verbatim

> https://github.com/arc-ive/arc/issues/135
> solve this bug using grill me skill and kickass skill anaylize the workflow

Note: #135 is not a bug. It is a P1 engineering task, *"Add Pydantic API
request/response contracts"*, labelled `v2` / `api-contract`.

Grilling answers that set scope, in order asked: **a, a** then **a, a** then **a, c**

- Q1 → response models must **freeze** today's exact shapes, not tighten them
- Q2 → **document** the existing error shapes in OpenAPI; do not design a new envelope
- Q3 → **request contracts + error documentation this pass**; response models become a follow-up issue
- Q4 → accept the DoD's **422 + list-shaped detail**, and update the frontend's error rendering in the same PR
- Q5 → the tool-execution endpoint gets an **envelope-only** model; per-tool validation stays where it is
- Q6 → error declarations cover **all 51 endpoints**, as a **separate second commit** on the same PR

## Goal

Requests to the Arc API are validated against declared schemas, invalid ones are
rejected with structured 422 errors instead of 400s, 500s, or silent acceptance,
and every endpoint's error responses are visible in the OpenAPI document.

## Requirements

| # | Requirement | How it would be proven unmet |
|---|---|---|
| R1 | Every endpoint accepting a JSON request body validates it against a declared schema | An endpoint in the in-scope set still annotates its body as `Dict[str, Any]` or `Optional[Any]` |
| R2 | A request body with a missing required field, a wrong field type, or an invalid enum value is rejected with **422** and a per-field `detail` list | Send each of those three against an in-scope endpoint; any returns 200, 400, or 500 |
| R3 | Inputs that today cause an unhandled `ValueError`/`KeyError` and a generic **500** are rejected with **422** instead | `POST /tenants` with `{}`, `POST /users` with `{}`, `POST /skills` with `{}`, `PUT /tenants/{id}` with `{"name": ""}`, and a malformed `previous_steps` entry on either `/resume` endpoint — any still returning 500 |
| R4 | Fields whose legal values are an existing domain enum are validated against that enum | Post an invalid `role`, `status`, `source`, `provider`, or `decision` value; anything other than 422 |
| R5 | Query parameters with a legal range are bounded declaratively rather than by hand-written checks inside the handler | `limit` on knowledge search still accepts out-of-range values, or still rejects them from inside the function body |
| R6 | Every endpoint declares the error responses it can return, and they appear in the generated OpenAPI document | Fetch `/openapi.json`; an endpoint's documented responses omit a status it demonstrably returns |
| R7 | The UI shows a useful, field-specific message for a 422 response | Trigger a validation failure in the browser; the message reads "Request failed with status 422" or similar |
| R8 | For **valid** input, every endpoint returns the same status code and the same response body as before this change | Diff a valid request/response against the pre-change behaviour; any difference |
| R9 | No endpoint gains a `response_model=` declaration in this change | `grep response_model= src/` returns a hit |

## Constraints

- C1: **No `response_model=`.** Response typing is a separate tranche (Q3).
- C2: `POST /webhooks/{endpoint_id}/events` is untouched. Its HMAC verification
  needs the exact raw bytes, so FastAPI body parsing must not be introduced.
- C3: `POST /tenants/{tenant_id}/tools/{name}/execute` gets a model for its
  two-field envelope only. The per-tool `input_model.model_validate` dispatch in
  `services/tools.py` stays exactly where it is.
- C4: Where a `tenant_id` comes from today — path, query string, or request body —
  does not change. The API has all three patterns and unifying them is a break.
- C5: No database, schema, or domain-model changes.
- C6: Error *shapes* are not redesigned. FastAPI's native shapes are documented,
  not replaced.
- C7: Valid-input behaviour is frozen; only invalid-input behaviour changes.
- C8: Every changed line traces to a requirement above.

## Non-goals

- **Response models / `response_model=` for the 51 endpoints.** The larger half of
  the issue's Definition of Done, deliberately deferred to its own issue so the
  behavioural change here stays reviewable.
- **Standardising where `tenant_id` comes from.** Three patterns exist (path,
  query, body). Worth an issue; changing it is an API break.
- **A custom error envelope.** Rejected at Q2: it breaks every consumer and every
  error path for presentational gain.
- **Rewriting endpoints whose hand-written validation is already correct**, beyond
  moving that validation into a model. The issue says this explicitly.
- **Typing the tool-execution payload itself**, which is polymorphic by design.
- Re-shaping the raw-bytes webhook ingestion path.

## Open questions

All resolved during grilling; recorded above under "The ask". None outstanding.

## Current behaviour

From the audit at `./audit.md`, which read all 51 endpoints. Independently
spot-checked rather than taken on trust:

- **1 of 51** endpoints has a typed Pydantic request body (`DevLoginRequest`,
  development-only). **0 of 51** declare `response_model=`.
- **11** endpoints annotate a body as `Dict[str, Any]`; **5** more use
  `Optional[Any] = Body(default=None)` with hand-written `isinstance` checks; **1**
  reads raw bytes. **33** take no body at all. The issue's claim of "20+ endpoints
  use `Dict[str, Any]`" is an overcount for request bodies — though it understates
  the response side, where nothing is typed anywhere.
- `src/arc/api/controllers.py:309-313` constructs `Tenant(...)` *before* the
  `try` block that begins on line 314. `Tenant.__post_init__` raises `ValueError`
  on an empty id or name, nothing catches it, and the caller gets a generic 500.
  Verified by reading the code. `POST /users` and `POST /skills` repeat the
  pattern.
- `controllers.py:2073-2084` and `:2156-2167` rebuild `previous_steps` by direct
  dict indexing and an unwrapped enum parse, outside the surrounding try/except,
  so a malformed entry also produces a 500.
- Validation quality is uneven rather than uniformly absent: the memberships,
  connectors and intelligence-query handlers already validate correctly by hand
  and need their logic *moved*, not written.
- Two incompatible 422 shapes already ship today: FastAPI-native validation
  errors carry a list `detail`, hand-raised `HTTPException(422, "...")` carries a
  string.
- `frontend/src/api/errors.js` derives its user-facing message from `detail` only
  when `detail` is a string, so a list-shaped 422 degrades to "Request failed with
  status N". Its `isValidation` accessor tests `status === 400` and is referenced
  only by its own unit test — no UI branches on it.

## Definition of done

> Done means: every in-scope endpoint validates its body against a declared
> schema; missing fields, wrong types and invalid enum values return 422 with a
> per-field detail list; the five documented 500-producing inputs return 422
> instead; bounded query parameters are declared rather than hand-checked; every
> endpoint's error responses appear in `/openapi.json`; the UI renders a
> field-specific message for a 422; and valid requests are demonstrably unchanged
> in both status and body — each of these observed to run, not inferred.
