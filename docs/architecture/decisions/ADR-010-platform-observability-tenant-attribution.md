# ADR-010: Per-Tenant Attribution in Platform Observability

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

Platform observability is strictly tenant-agnostic. The constraint is
stated in four places across three layers:

| Location | Statement |
|---|---|
| `security/authorization.py` | `observability:platform_read` grants the "STRICTLY TENANT-AGNOSTIC platform operational summary… Platform visibility never exposes per-tenant business data." |
| `repositories/__init__.py` | "`tenant_id=None` selects the PLATFORM view — strictly tenant-agnostic operational totals; **no method returns per-tenant breakdowns**." |
| `services/observability.py` | "No tenant identifiers, per-tenant usage, rankings, or breakdowns are ever included (approved Joe/Bala policy)." |
| `api/controllers.py` | The endpoint contract repeats it. |

The operational consequence: during an incident, a platform operator can
see that the error rate has risen and **cannot see which customer is
affected**. Diagnosis requires asking each customer's own administrator
to look from inside their workspace, which is the opposite of how an
incident is actually run.

The data already supports attribution. `api_request_records` carries a
nullable `tenant_id` and is indexed on it. The gap has always been
policy, never capability.

## Decision

Platform observability may attribute HTTP request and error counts to a
tenant.

1. A new endpoint `GET /platform/observability/tenants` returns, per
   tenant: request count, error count and error rate for the window.
2. It requires `observability:platform_read`, unchanged — this widens
   what that permission shows, not who holds it.
3. The existing `GET /platform/observability/summary` is **unchanged**
   and remains tenant-agnostic. Code and tests depending on it keep
   working, and an operator who wants only platform health still gets
   exactly that.
4. Scope is deliberately narrow. Attribution covers **request volume,
   error counts and error rate**. It does NOT cover knowledge, skills,
   approvals, agent goals, prompts, document contents, or any other
   tenant business data.

## Options Considered

### Option 1 — Keep the policy

Description: leave platform observability tenant-agnostic.

Advantages:

- No customer-identifying information on the platform plane at all.
- Simplest possible privacy story.

Disadvantages:

- An operator cannot answer "which customer is affected" during an
  incident, which is the first question asked.
- Pushes diagnosis onto customers, who have less context than the
  operator about a platform-wide fault.

### Option 2 — Attribute errors only

Description: expose per-tenant error counts, but no request volume.

Advantages:

- Answers the incident question.
- Reveals nothing about how much a customer uses the product.

Disadvantages:

- An error count without a denominator is close to unreadable: 40 errors
  is alarming for a customer making 50 requests and noise for one making
  50,000.

### Option 3 — Attribute requests and errors (chosen)

Description: expose per-tenant request count, error count and error rate.

Advantages:

- Errors are interpretable, because the rate has a denominator.
- Matches how the operator actually reasons during an incident.

Disadvantages:

- Request volume is a commercial signal: it indicates how heavily a
  customer uses Arc. It stays inside the operator's own platform, but it
  is no longer invisible to them.

## Rationale

Option 2 fails on its own terms. The purpose is to make an anomaly
legible, and an error count without a denominator is not legible.

Option 3's cost is that the operator can see relative customer usage.
The operator already hosts the data, provisions the tenants and bills
for them, so this is not a new trust relationship — it is a smaller
disclosure than the one the customer has already accepted by being
hosted. The rejected disclosure is customer *content*, and that remains
entirely out of reach.

## Consequences

### Positive

- Incidents can be attributed to a customer without asking them.
- No change to who holds any permission.
- The existing tenant-agnostic summary is untouched.

### Negative

- Reverses an explicitly approved policy. Anyone reading the old
  docstrings must be pointed here; they are updated to cite this ADR
  rather than left contradicting it.
- Relative customer usage becomes visible to platform operators.

### Risks

- Scope creep. "Which customer" invites "what were they doing", and the
  next request will be for endpoints or payloads. The boundary is that
  attribution covers counts only; anything describing tenant *content*
  needs its own decision.

## Security Considerations

- **Authorization**: unchanged. `observability:platform_read` is held by
  `PLATFORM_ADMINISTRATOR` only.
- **Tenant isolation**: unchanged. This does not give the platform plane
  any route into tenant-scoped data; a platform administrator still
  receives 403 on every tenant route (ADR-003).
- **Data exposure**: tenant id, tenant name and three integers. No
  request paths, payloads, user identifiers, prompts or document
  content.
- **Unattributed traffic**: records with a null `tenant_id` — public and
  unauthenticated requests — are reported as a single unattributed
  bucket rather than dropped, so the per-tenant figures never silently
  fail to sum to the platform total.

## Operational Considerations

- No migration; `api_request_records.tenant_id` already exists and is
  indexed.
- One aggregate query per request, grouped by tenant.

## Testing / Validation

- A platform administrator receives per-tenant counts.
- A company administrator and an operations user are refused.
- Errors and requests attribute to the correct tenant.
- Unattributed traffic appears as its own bucket.
- The existing tenant-agnostic summary is byte-identical.

## Related Documents

- `docs/architecture/decisions/ADR-003-company-brain-document-identity-and-re-ingestion.md`

## Related Work

- GitHub: #297

## Supersedes

Supersedes the tenant-agnostic constraint on platform observability
recorded in `services/observability.py`, `repositories/__init__.py`,
`security/authorization.py` and `api/controllers.py`, to the extent
described above. The tenant-agnostic `get_platform_summary` remains.

## Superseded By

<!-- none -->
