# ADR-011: Tenant Lifecycle — Suspension, Not Deletion

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

A tenant can be created and read. It cannot be stopped.

- No `DELETE /tenants/{id}` endpoint exists.
- `tenants.status` exists on the record, but no endpoint can change it.
  `TenantUpdateRequest` deliberately omits the field.
- **Nothing consults `tenants.status` at any authorization boundary.**
  A tenant whose status reads `suspended` behaves exactly like an active
  one, so the field is currently decorative.

That last point matters most. Adding a control that writes `suspended`
without making the value mean anything would be theatre: the UI would
report a customer as stopped while every one of their users kept working
normally.

Hard deletion is also more destructive than it looks.
`approval_requests` and `api_request_records` both declare
`FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE`, so
removing a tenant row destroys its approval history and request
telemetry — the audit trail of a customer who has left, which is usually
the moment that trail is most needed.

## Decision

Tenants are **suspended and restored**, never deleted through the
product.

1. `POST /tenants/{tenant_id}/status` sets a tenant to `active` or
   `suspended`. It requires the global `tenant:update` permission
   (`PLATFORM_ADMINISTRATOR`), and is a separate endpoint from
   `PUT /tenants/{id}` so that status is never changed as a side effect
   of editing a company profile.
2. **Suspension has a defined effect**, enforced where the tenant
   boundary is already established: `TenantContextService` refuses to
   create a context for a suspended tenant. Every tenant-scoped route
   therefore fails closed — knowledge, skills, tools, approvals, agents,
   connectors, observability, Ask Arc — because they all establish a
   context first.
3. **Platform routes still see the tenant.** Listing tenants, reading
   the record and the observability register continue to work, so a
   suspended customer remains administrable and auditable.
4. **Suspension is reversible and lossless.** No data is removed; the
   tenant returns to exactly its prior state on restore.
5. **No delete endpoint is added.** Erasure for a legal request is a
   separate, audited, out-of-band process, not a product control.

## Options Considered

### Option 1 — Add a delete endpoint

Description: `DELETE /tenants/{id}`, cascading.

Advantages:

- Removes the data, which is what "delete" implies.

Disadvantages:

- Destroys approval history and request telemetry via the existing
  cascades — the audit trail of a departed customer.
- Irreversible, and the control that most invites a misclick.
- Conflates "stop this customer" with "erase this customer", which are
  different decisions with different authority.

### Option 2 — Soft-delete with a `deleted_at` column

Description: add a nullable timestamp; treat non-null as deleted.

Advantages:

- Preserves data.

Disadvantages:

- Adds a second lifecycle concept next to the `status` column that
  already exists, so two fields would describe overlapping states and
  eventually disagree.

### Option 3 — Suspension via the existing status field (chosen)

Description: make the field that already exists mean something.

Advantages:

- No schema change, no new lifecycle concept.
- Reversible and lossless.
- Enforced at the point where every tenant route already converges, so
  there is one place to get right rather than fifty.

Disadvantages:

- Does not satisfy an erasure request; that remains a separate process.
- A single enforcement point is also a single point of failure, so it
  needs direct tests rather than only route-level ones.

## Rationale

Option 3 makes an existing field real instead of introducing a parallel
one. Enforcing in `TenantContextService` is the decisive part: every
tenant-scoped route already establishes a context before doing anything,
so suspension covers routes that do not yet exist, rather than being a
check each new endpoint must remember.

Deletion was rejected because the cascades make it destroy exactly the
records an operator needs after a customer leaves.

## Consequences

### Positive

- A customer can actually be stopped, and restored.
- `tenants.status` stops being decorative.
- No migration, no new column, no data loss.

### Negative

- Suspension is enforced in one place, so a future route that bypasses
  `TenantContextService` would bypass suspension. The existing rule that
  the tenant boundary comes only from the trusted context already
  forbids that.
- Does not satisfy erasure. Anyone expecting "delete" to mean "gone"
  needs to read this.

### Risks

- A suspended tenant's users see a generic access-denied response rather
  than "your workspace is suspended". This is deliberate — the message
  does not distinguish suspension from non-membership — but it will
  generate support contacts that look like access bugs.

## Security Considerations

- **Authorization**: status changes require the global `tenant:update`
  permission, which only `PLATFORM_ADMINISTRATOR` holds. A company
  administrator holds `tenant:update` scoped to their own tenant for
  profile fields and cannot reach this endpoint, so a customer cannot
  suspend or un-suspend themselves.
- **Fail closed**: an unknown or unreadable status is treated as not
  active. A tenant is usable only when its status is explicitly
  `active`.
- **Tenant isolation**: unchanged. Suspension narrows access; it never
  widens it.
- **Audit**: the tenant record's `updated_at` moves, and the status
  change is a normal API request captured in request telemetry.

## Operational Considerations

- No migration.
- Restoring is the same endpoint with `active`.
- Suspension takes effect on the next request; existing sessions are not
  separately revoked, because every request re-establishes the context.

## Testing / Validation

- A platform administrator can suspend and restore.
- A company administrator cannot change status through either endpoint.
- A member of a suspended tenant is refused on tenant-scoped routes.
- Restoring returns access, with no data lost.
- `PUT /tenants/{id}` still cannot change status.
- Platform routes still list and read a suspended tenant.

## Related Documents

- `docs/architecture/decisions/ADR-008-tenant-membership-and-application-rbac-roles.md`

## Related Work

- GitHub: #295

## Supersedes

<!-- none -->

## Superseded By

<!-- none -->
