# ADR-009: Tenant-Scoped Membership Administration

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

ADR-008 assigned every membership action to `PLATFORM_ADMINISTRATOR`:

| Action | Authority (ADR-008) |
|---|---|
| Create any membership role | PLATFORM_ADMINISTRATOR |
| Remove membership | PLATFORM_ADMINISTRATOR |

Both membership endpoints enforce this with `require_permission`
(global) rather than `require_tenant_permission` (tenant-scoped), and
`membership:create` is granted only to `PLATFORM_ADMINISTRATOR`.

The consequence in the product: **a company administrator cannot add or
remove anyone in their own workspace.** Every joiner and leaver in every
customer organisation requires the platform operator. That does not
scale past a handful of customers, and it puts the platform operator in
the middle of routine customer HR events they have no business knowing
about.

It also sits oddly beside ADR-003's plane separation, which holds that
platform administration and customer data are distinct: routing a
customer's joiner/leaver through the platform operator pushes customer
business into the platform plane rather than keeping it out.

## Decision

A company administrator may administer membership **within their own
tenant**.

1. A new permission `membership:manage` is granted to
   `COMPANY_ADMINISTRATOR` and `PLATFORM_ADMINISTRATOR`.
2. `POST /tenants/{tenant_id}/memberships` and
   `DELETE /tenants/{tenant_id}/memberships/{user_id}` accept **either**
   the existing global `membership:create` **or** tenant-scoped
   `membership:manage` in the tenant named by the trusted context.
3. Two invariants are enforced server-side, not in the UI:
   - A tenant must always retain at least one `OWNER`. Removing the last
     one is refused.
   - An administrator cannot remove their own membership. Self-removal
     is how someone locks themselves out of a workspace they are
     responsible for.
4. **User creation stays platform-only.** `user:create` is unchanged.
   Adding an existing Arc user to a workspace is membership
   administration; creating an Arc identity is provisioning, and
   conflating them would let a tenant administrator mint platform
   identities.

## Options Considered

### Option 1 — Leave authority with the platform operator

Description: keep ADR-008 unchanged.

Advantages:

- No change to the authorization model.
- The platform operator sees every membership change.

Disadvantages:

- Does not scale: every joiner and leaver is a platform ticket.
- Puts the platform operator inside customer HR events.
- The product cannot offer people management at all, which is table
  stakes for a multi-tenant SaaS.

### Option 2 — Grant tenant-scoped membership administration (chosen)

Description: a company administrator manages membership in their own
tenant; the platform operator retains global authority.

Advantages:

- Customers administer their own people, as they expect to.
- The tenant boundary is enforced by the same trusted-context mechanism
  every other tenant route uses — no new isolation mechanism.
- Keeps customer business out of the platform plane, consistent with
  ADR-003.

Disadvantages:

- Widens the authorization model; a compromised company-administrator
  account can now change membership in that tenant.
- Needs orphan-prevention invariants that did not previously exist.

### Option 3 — Grant it and also allow user creation

Description: as Option 2, plus `user:create` for company administrators
so they can invite people with no Arc account.

Advantages:

- Complete self-service onboarding.

Disadvantages:

- A tenant administrator could mint platform identities, which is a
  materially larger privilege than managing who is in their workspace.
- Invitation is a flow (token, expiry, acceptance), not a permission.
  Granting the permission without the flow would create accounts with no
  way for the person to claim them.

## Rationale

Option 2 changes *who* may perform an action that already exists, within
a boundary Arc already enforces on every other tenant route. It does not
introduce a new trust boundary, a new isolation mechanism, or a new
identity path.

Option 3 was rejected because it conflates two different privileges.
Creating an Arc identity is provisioning; putting an existing identity
into a workspace is administration. Invitation deserves its own design.

## Consequences

### Positive

- Company administrators manage their own workspace.
- The platform operator stops being a bottleneck for routine changes.
- Orphaned workspaces become impossible via this path.

### Negative

- A compromised company-administrator account can add or remove members
  in that tenant. Previously it could not.
- Two behaviours the API did not have before (last-owner and
  self-removal refusals) must be maintained.

### Risks

- A company administrator could add any **existing** Arc user by id,
  including a user belonging to another customer. This is mitigated but
  not eliminated: it grants that user access to the adding tenant only,
  never the reverse, and every membership is auditable. A future
  invitation flow should replace id-based addition.

## Security Considerations

- **Authorization**: the endpoints move from a global permission check to
  accepting a tenant-scoped one. The tenant is taken from the trusted
  context, never from the path, which is validated for consistency only.
- **Tenant isolation**: unchanged. A company administrator of tenant A
  holds `membership:manage` in tenant A alone; the same request against
  tenant B fails context establishment before reaching the handler.
- **Privilege escalation**: `user:create` and `ApplicationRole`
  assignment remain platform-only, so this grants no route to creating
  identities or changing what someone can do platform-wide.
- **Availability**: the last-owner invariant prevents a workspace being
  left with no administrator.

## Operational Considerations

- No migration. The permission is added to the in-code role matrix.
- Membership changes are already recorded; no new telemetry is required.

## Testing / Validation

- A company administrator can add and remove members in their own tenant.
- The same administrator is refused against another tenant.
- Removing the last OWNER is refused.
- Self-removal is refused.
- A platform administrator retains existing behaviour.
- An employee and an operations user remain unable to manage membership.

## Related Documents

- `docs/architecture/decisions/ADR-008-tenant-membership-and-application-rbac-roles.md`

## Related Work

- GitHub: #298

## Supersedes

Partially supersedes ADR-008: the *Assignment Authority* rows for
"Create any membership role" and "Remove membership". All other ADR-008
decisions, including the independence of `UserRole` and
`ApplicationRole`, are unchanged.

## Superseded By

<!-- none -->
