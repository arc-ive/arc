# ADR-012: A Requester May Always Read Their Own Approval Requests

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

`OPERATIONS_USER` holds `tool:execute` and does not hold
`approval:read` (`src/arc/security/authorization.py`). That is exactly
the combination that produces approval requests: the operations user
calls a high-risk tool, `ToolExecutionService` denies it with
`REQUIRE_HUMAN_APPROVAL`, and a pending `approval_requests` row is
written with that user as `requester_user_id`.

They then cannot see the row they created. `GET /tenants/{id}/approvals`
requires `approval:read`; the frontend route, the nav entry and the page
body are all gated on the same permission.

This matters more than a missing list view, because of where the resume
step lives. An approved request is not finished — it is a single-use
licence the **requester** has to spend, by calling `execute_tool` with
the `approval_id` (ADR-005: approval is not authorization; the approved
call still goes through the full authorized execution boundary, which
consumes the approval). The only place in the product that spends an
approval is the "Run it now" control on the Approvals page. So the
requester who most needs that page is the one who cannot open it, and
an approval granted to an operations user is a licence with nowhere to
spend it.

The constraint that shapes this ADR: the fix must not widen what anyone
can see about anyone else. Approval rows carry `input_summary` — a
redacted, truncated rendering of the arguments a colleague submitted
(`src/arc/services/tools.py`) — and `requester_user_id`. Tenant-wide
approval read is therefore a real disclosure, and it is the thing
`approval:read` exists to control.

## Decision

**A caller who holds a trusted tenant context may always read the
approval requests they themselves created, regardless of
`approval:read`.**

1. `approval:read` continues to mean *tenant-wide* approval read. A
   caller holding it sees every row in the tenant, exactly as before.
2. A caller **without** `approval:read` who has passed the X-10 tenant
   boundary is narrowed to rows where `requester_user_id` equals their
   authenticated principal. The narrowing is applied **in SQL**, in both
   the `SELECT` and the `COUNT`, so the scoped caller's page and its
   `total` are both computed over their own rows only. Nothing is
   fetched and then filtered in Python.
3. The same rule applies to the single-row read
   `GET /tenants/{id}/approvals/{approval_id}`. A self-scoped caller
   asking for someone else's approval receives **404, not 403** — a
   scope they cannot read must not confirm the row exists.
4. **`approval:decide` is not touched.** Reading your own request has
   never implied deciding it, and the four-eyes rule
   (`HumanApprovalService.decide_request`) forbids deciding your own
   request whatever role you hold. A self-scoped caller submitting a
   decision still receives 403 from the unchanged permission check.
5. The X-10 tenant boundary is not touched. A non-member is refused by
   `get_trusted_tenant_context` before any of this is reached, so
   "self-scoped" never means "cross-tenant".

Mechanically this is one new dependency,
`require_tenant_permission_or_self(permission)`, which returns a
`TenantReadScope` — the trusted context plus `restrict_to_user_id`,
which is `None` for a permission holder and the caller's own user ID
otherwise. Only the two approval read routes use it.

## Options Considered

### Option 1 — Grant `approval:read` to `OPERATIONS_USER`

Description: add the permission to the role's frozenset.

Advantages:

- One line; no new concepts.
- The existing page works unchanged.

Disadvantages:

- Grants tenant-wide read of every colleague's approval requests and
  their redacted argument summaries, to solve a problem about the
  caller's own row. The widening is the whole cost of the change and
  none of it is needed.
- Does nothing for `EMPLOYEE`, who can also become a requester through
  `agent:execute` (V2-ADR-005 routes employee work through Agent, which
  reaches tools), so the same gap returns for the next role.
- Makes `approval:read` mean less: it would no longer mark the people
  trusted to see the tenant's pending decisions.

### Option 2 — Put a resume control somewhere outside the Approvals page

Description: surface "your approved actions" on the page where the
action was originally attempted (Tools / Ask Arc), and leave the
Approvals page permission-gated as it is.

Advantages:

- No change to the permission model at all.
- Arguably better product placement: you resume where you were
  interrupted.

Disadvantages:

- Needs the same data through the same endpoint. Either it calls
  `GET /approvals` — which is the permission problem, unmoved — or a
  second, narrower endpoint is invented that returns "my approvals",
  which is this ADR's decision wearing a different URL and a second
  code path to keep honest.
- The requester still cannot see that their request was **rejected**,
  or that it expired unused. Resume is not the only reason to look.
- Duplicates the approval row rendering in a second place.

### Option 3 — Self-scoped read (chosen)

Description: as recorded under Decision.

Advantages:

- Narrow and principled, and states a rule a reader can check in one
  sentence: you can always see what you asked for, and never anyone
  else's.
- Fixes every present and future requester role at once, because it is
  keyed on `requester_user_id` rather than on a role's permission set.
- Discloses nothing new. Every row a self-scoped caller can now read is
  a row they authored.
- Keeps `approval:read` meaningful — it stays the tenant-wide grant.

Disadvantages:

- A real change to the authorization model, so it needs this ADR and it
  needs the narrowing to be correct.
- The same endpoint now returns different row sets to different callers.
  A reader of the handler has to notice the scope, and a future
  contributor adding a filter there has to keep it in SQL.
- The frontend gains a second state: a page that renders for someone who
  can see only their own requests and can decide none of them.

## Rationale

Option 1 pays for a self-service fix with a privacy widening, and pays
again the next time a role becomes a requester. Option 2 avoids the
model change only by re-inventing it as a second endpoint, and still
leaves the requester unable to learn their request was rejected.

Self-scoping is also not a new idea in Arc. `GET /users/{id}/tenants`
already serves a caller with no matrix permission at all, and refuses the
same call for another user's ID — the authenticated principal, not a
role, decides the row set. ADR-012 applies that existing shape to a
second resource rather than introducing a new kind of rule.

Option 3 is chosen because the rule it adds is the one the system
already implies everywhere else: `requester_user_id` is durable, is
written from the authenticated principal inside the execution boundary,
and is already the basis of the four-eyes check. Reading your own row is
the weakest possible additional grant — strictly weaker than any role
grant, because it authorizes zero rows the caller did not create.

Filtering in SQL rather than in Python is part of the decision, not an
implementation detail: a Python filter over a fetched page returns short
pages and a `total` computed over rows the caller may not see, which is
both wrong and a slow leak of how much approval traffic the tenant has.

## Consequences

### Positive

- The resume path shipped for #300 is reachable by the roles that
  actually create approval requests.
- A requester can see that their request was approved, rejected or
  expired, without anyone granting them tenant-wide visibility.
- `approval:read` keeps a single clear meaning.

### Negative

- Two read routes now resolve a scope rather than a plain context, and
  that scope must be threaded through the service to the repository.
- `total` semantics are per-caller on these routes. Two users looking at
  the same tenant legitimately see different counts.
- The Approvals page has a mode with no decision column at all, which
  has to read as intentional rather than as broken.

### Risks

- A future filter or sort added to the approval listing could be applied
  after the scope narrowing is lost — for example by reintroducing a
  "fetch all then filter" step. Mitigated by keeping
  `restrict_to_user_id` a parameter of the repository query itself, so
  there is no code path that fetches unscoped rows for a scoped caller.
- `require_tenant_permission_or_self` could be misapplied to a write
  route, where "self-scoped" has no meaning. Mitigated by the dependency
  returning `TenantReadScope`, whose name and docstring say read, and by
  its only two call sites both being `GET`.

## Security Considerations

- **Authentication** unchanged. `restrict_to_user_id` comes from
  `AuthenticatedPrincipal.user_id`, which is derived from the validated
  session or JWT `sub` claim, never from a body, query parameter or
  header.
- **Authorization** widened by exactly one rule, stated above.
  `approval:decide` and `tool:execute` are untouched, so this grants no
  new ability to act — only to see rows the caller authored.
- **Tenant isolation** unchanged. The tenant predicate stays in every
  query and the trusted context is still established first; the new
  predicate is an additional `AND`, never a replacement.
- **No existence leak.** The single-row read returns 404 for a row
  outside the caller's scope, identical to a row that does not exist.
- **No data exposure.** Every newly readable row has the caller as its
  `requester_user_id`. Encrypted approved input is still never returned
  by a read route; it is read only inside the execution boundary on
  resume.
- **Fail closed.** A caller with no application role at all resolves to
  self-scope, not full scope. Since such a caller cannot execute tools,
  they author no approval rows and read an empty list.

## Operational Considerations

- No schema change. `approval_requests.requester_user_id` already
  exists and is already indexed by the tenant-scoped queries' access
  pattern; the added predicate is on the same row set.
- No migration, no configuration, no new secret.
- Support impact: "I can see fewer approvals than my colleague" is now
  expected behaviour, and the page says so in copy rather than leaving
  it to be inferred.

## Testing / Validation

- A requester without `approval:read` lists their own row and does not
  see a colleague's row in the same tenant.
- `total` for the scoped caller counts only their own rows — asserted
  with more rows in the tenant than the caller authored, so a
  Python-side filter over a fetched page would fail the assertion.
- A caller holding `approval:read` still receives every row in the
  tenant.
- A self-scoped caller reading another user's approval by ID receives
  404.
- A self-scoped caller attempting a decision receives 403, proving
  read-scope did not become decide-scope.
- Cross-tenant isolation holds for both scoped and unscoped callers.

## Related Documents

- ADR-005 — Human Intervention Approval Gate (binding, single use,
  four-eyes, "approval is not authorization")
- ADR-008 — Tenant membership and application RBAC roles (the two
  independent role systems this decision does not merge)

## Related Work

- Linear:
- GitHub: #318, #300

## Supersedes

## Superseded By
