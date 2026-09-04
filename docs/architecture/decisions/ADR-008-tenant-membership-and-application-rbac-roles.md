# ADR-008: Tenant Membership Roles and Application RBAC Roles — Independent Role Systems

## Status

Accepted

## Date

2026-09-04

## Decision Owners

- Bala — Engineering and architecture review
- Joe — Product scope and requirements
- Bharath — Platform, Docker, CI, and delivery review

## Context

Issue #60 asks for clarification on the provisioning and mapping between
the two role systems in Arc:

1. **Tenant membership roles** (`UserRole`): OWNER, MEMBER, VIEWER —
   defined in `src/arc/domain/models.py`. Stored in the `memberships`
   table. Controls a user's relationship to a specific tenant.

2. **Application RBAC roles** (`ApplicationRole`): PLATFORM_ADMINISTRATOR,
   COMPANY_ADMINISTRATOR, OPERATIONS_USER, EMPLOYEE — defined in
   `src/arc/security/models.py`. Not stored in the database; configured
   via the `APPLICATION_ROLE_ASSIGNMENTS` environment variable. Controls
   platform-level permissions.

The current architecture intentionally treats these as independent systems.
Multiple source files document this independence explicitly:

- `src/arc/security/models.py:8-10`: "It is deliberately separate from
  the X-10 membership UserRole (OWNER/MEMBER/VIEWER) and must never be
  derived from or mapped to it."
- `src/arc/security/models.py:21-22`: "There is NO mapping between the
  two role systems."
- `src/arc/security/authorization.py:84-85`: "ApplicationRole is
  completely independent of the X-10 membership UserRole. No mapping
  exists between them."
- `tests/test_rbac.py:48-52`: Automated test asserting
  `ApplicationRole` and `UserRole` values are disjoint.

Issue #58 (PR #74) introduced automatic OWNER membership creation when a
tenant is created via `POST /tenants`. The creator receives a `UserRole.OWNER`
membership but does NOT receive any `ApplicationRole`. This is intentional:
the two systems remain independent.

The current architecture lacks an explicit Architecture Decision Record
formalizing this relationship, the provisioning model, and the design
rationale.

## Decision

**UserRole (tenant membership) and ApplicationRole (application RBAC)
are and must remain completely independent role systems.**

There is NO automatic mapping between them. Membership in a tenant does
NOT grant application-level permissions. ApplicationRole assignment does
NOT grant tenant-level access.

### Role-System Relationship

```
UserRole (tenant membership)          ApplicationRole (platform RBAC)
─────────────────────────────         ─────────────────────────────────
OWNER    — tenant owner               PLATFORM_ADMINISTRATOR — full access
MEMBER   — tenant member              COMPANY_ADMINISTRATOR  — tenant-scoped admin
VIEWER   — tenant viewer              OPERATIONS_USER        — operational access
                                       EMPLOYEE               — self-scoped only
```

These systems answer different questions:

- **UserRole**: "What is this user's relationship to this tenant?"
  (tenant-scoped, persisted in `memberships` table)
- **ApplicationRole**: "What can this user do on the platform?"
  (global, configured via environment, checked by `AuthorizationService`)

### Provisioning Model

| Mechanism | UserRole | ApplicationRole |
|---|---|---|
| Tenant creation (POST /tenants) | OWNER membership auto-created for creator (PR #74) | Not affected |
| Membership provisioning (POST /internal/dev/.../memberships) | Any role assignable by PLATFORM_ADMINISTRATOR | Not affected |
| User creation (POST /users) | No membership created | Not assigned |
| Environment configuration | N/A | `APPLICATION_ROLE_ASSIGNMENTS` JSON |
| Future: SSO/SCIM/IdP | N/A | External identity provider assigns |

### Default Provisioning Behavior

1. **Newly created user**: No `UserRole` membership, no `ApplicationRole`.
   The user is denied by default for all application permissions and has
   no tenant access.

2. **Tenant creator** (POST /tenants after PR #74): Receives
   `UserRole.OWNER` membership for the newly created tenant. Does NOT
   receive any `ApplicationRole`. The creator can access the tenant they
   created but has no platform-level application permissions unless
   separately assigned.

3. **Membership provisioning**: A PLATFORM_ADMINISTRATOR can create
   memberships for any user in any tenant via the development-only
   endpoint. This grants `UserRole` only.

### Assignment Authority

| Action | Authority | Mechanism |
|---|---|---|
| Assign/change ApplicationRole | PLATFORM_ADMINISTRATOR | Environment configuration (current); API (future) |
| Create tenant OWNER membership | Authenticated PLATFORM_ADMINISTRATOR | Automatic via POST /tenants |
| Create any membership role | PLATFORM_ADMINISTRATOR | POST /internal/dev/.../memberships |
| Remove membership | PLATFORM_ADMINISTRATOR | DELETE endpoint (future) |

### Authorization Flow

```
Request
  → Authentication: JWT → AuthenticatedPrincipal (user_id from JWT sub)
  → For global permissions:
      AuthorizationService.has_permission(principal, permission)
        → looks up ApplicationRole from role_assignments
        → checks ROLE_PERMISSIONS matrix
        → DENY if unknown user/role/permission
  → For tenant-scoped permissions:
      get_trusted_tenant_context → TenantContext (from persisted membership)
        → TenantContextService.create_tenant_context verifies membership
        → role derived from database, never from caller input
      AuthorizationService.has_permission(principal, permission)
        → same ApplicationRole check as above
```

The two checks are independent. A user can pass the membership check but
fail the permission check, or vice versa. Both must pass for access.

### Behavior When Only One System Is Present

| Scenario | Behavior |
|---|---|
| User has OWNER membership but NO ApplicationRole | User can list/access the tenant but has NO application permissions (cannot create knowledge, execute skills, etc.) |
| User has ApplicationRole but NO membership | User has application permissions but CANNOT access any tenant (all tenant-scoped requests are denied 403) |
| User has both | User has application permissions AND tenant access (both checks pass) |
| User has neither | User is denied by default for everything |

### Multi-Tenant Behavior

A user can have:
- Multiple tenant memberships with the SAME role across tenants
- Multiple tenant memberships with DIFFERENT roles across tenants
- An OWNER membership in Tenant A and a MEMBER membership in Tenant B
- An OWNER membership in Tenant A and no membership in Tenant B

Each membership is independent. The user's role in each tenant is
determined by the specific membership row for that (user, tenant) pair.

ApplicationRole is global and does not vary by tenant. A
COMPANY_ADMINISTRATOR has the same platform permissions regardless of
which tenant they are operating in.

### Compatibility with Existing Architecture

This decision is CONSISTENT with:

- ADR-001: Arc Unified Intelligence architecture — RBAC is application-level
- X-10: Tenant membership boundary — UserRole controls tenant access
- X-11: Authentication and application RBAC — ApplicationRole controls permissions
- PR #56: Final product and architecture specification
- PR #74: Tenant onboarding owner auto-assignment — OWNER membership created, no ApplicationRole mapping
- CURRENT_STATE.md: Both systems documented as independent

This decision does NOT conflict with any existing ADR, PRD, or TRD.

## Options Considered

### Option A — Membership-Derived Application Roles (Rejected)

Map UserRole directly to ApplicationRole:
- OWNER → COMPANY_ADMINISTRATOR
- MEMBER → OPERATIONS_USER
- VIEWER → EMPLOYEE

**Advantages:**
- Simplified onboarding (create tenant → creator gets platform permissions)
- Single role concept for administrators

**Disadvantages:**
- Violates the architectural independence of the two role systems
- Privilege escalation: OWNER of a test tenant becomes COMPANY_ADMINISTRATOR with broad platform permissions
- Ambiguous for multi-tenant users (OWNER in Tenant A + MEMBER in Tenant B → which ApplicationRole?)
- Collapses two orthogonal concerns (tenant relationship vs. platform capabilities)
- Conflicts with all existing documentation and tests asserting independence
- Breaks the fail-closed security model (membership becomes a second permission path)

### Option B — Completely Independent Systems (Selected)

No mapping. UserRole and ApplicationRole are independent. ApplicationRole
is assigned explicitly through environment configuration (current) or
API (future).

**Advantages:**
- Clean separation of concerns (tenant relationship vs. platform permissions)
- No privilege escalation through membership
- Supports multi-tenant scenarios correctly
- Compatible with future SSO/SCIM/IdP integration
- Consistent with existing architecture and all tests
- Least privilege: membership alone grants no platform permissions

**Disadvantages:**
- Requires separate provisioning for each role system
- More administrative steps for onboarding (must assign both membership and ApplicationRole)
- No automatic platform permission grant on tenant creation

### Option C — Hybrid with Explicit Provisioning (Equivalent to Option B)

Similar to Option B but with an explicit provisioning mechanism that
creates both a membership and an ApplicationRole in a single operation.

**Advantages:**
- Convenience for common provisioning patterns
- Single API call for full onboarding

**Disadvantages:**
- Same as Option B (the provisioning mechanism is a convenience wrapper, not an architectural change)
- Adds complexity without changing the fundamental role relationship
- Implementation is premature — the current environment-based configuration is sufficient for the foundation phase

## Rationale

Option B is selected because:

1. **The current architecture is correct.** The two role systems answer
   different questions and should remain independent.

2. **No privilege escalation.** A user cannot gain platform permissions
   through tenant membership alone.

3. **Multi-tenant correctness.** A user's role in each tenant is
   independent, and their platform permissions are global.

4. **Future extensibility.** Database-backed ApplicationRole assignment,
   SSO/SCIM integration, and per-tenant application roles can be added
   later without changing the fundamental relationship.

5. **Tested and proven.** The independence is verified by automated tests
   (`test_application_roles_are_independent_of_membership_roles`,
   `test_membership_role_never_grants_application_permissions`) and has
   been reviewed across PRs #19, #56, and #74.

## Consequences

### Positive

- Clean, defensible RBAC architecture with no ambiguous role paths
- No privilege escalation through membership
- Consistent with all existing documentation, ADRs, and tests
- Supports future production provisioning mechanisms (database-backed, SSO/SCIM)
- Tenant isolation remains intact regardless of ApplicationRole

### Negative

- Requires separate provisioning for membership and application roles
- More administrative steps during onboarding
- No automatic platform permission grant on tenant creation (intentional)

### Risks

- None identified. The current architecture already implements this model.

## Security Considerations

- **No privilege escalation through OWNER membership**: An OWNER has
  tenant-level access but NO platform permissions. A PLATFORM_ADMINISTRATOR
  can create tenants but must separately be assigned the ApplicationRole.
- **No client-controlled role assignment**: Both UserRole (derived from
  database) and ApplicationRole (from environment config) are server-side
  only.
- **Fail-closed default**: Unknown users, unknown roles, and unlisted
  permissions are always denied.
- **Tenant isolation**: ApplicationRole is global; tenant access is
  controlled exclusively by UserRole through the membership table.
- **No cross-tenant ApplicationRole escalation**: A user who is OWNER in
  Tenant A does not automatically gain access to Tenant B.

## Operational Considerations

- **Deployment**: ApplicationRole assignments are environment-configured.
  Changing them requires a configuration change and application restart.
- **Future production**: Database-backed ApplicationRole assignment will
  allow runtime changes without restart.
- **Auditability**: The two role systems are audited independently:
  membership in `memberships` table, ApplicationRole in configuration.
- **Monitoring**: No changes required. Existing permission-denied logging
  captures both membership and ApplicationRole failures.

## Testing / Validation

The following tests already verify this decision:

- `test_application_roles_are_independent_of_membership_roles`: Asserts
  ApplicationRole and UserRole value sets are disjoint.
- `test_membership_role_never_grants_application_permissions`: Asserts
  that no UserRole grants any application permission.
- `test_permission_matrix`: Verifies the complete permission matrix for
  all four ApplicationRoles.
- `test_tenant_creation_assigns_owner_membership`: Verifies OWNER
  membership is created on tenant creation without any ApplicationRole
  change.
- `test_tenant_isolation_after_creation`: Verifies cross-tenant isolation
  is maintained.

No new tests are required. The existing tests comprehensively verify the
independence of the two role systems.

## Related Documents

- `src/arc/security/models.py:8-10` — ApplicationRole independence statement
- `src/arc/security/models.py:21-22` — No-mapping assertion
- `src/arc/security/authorization.py:84-85` — Independence documented
- `src/arc/domain/models.py:9-14` — UserRole definition
- `tests/test_rbac.py:48-52` — Automated independence test
- `tests/test_rbac.py:206-212` — Membership-does-not-grant-permissions test

## Related Work

- GitHub: Issue #60 — "clarify(auth): define provisioning and mapping between application RBAC roles and tenant membership roles"
- GitHub: Issue #58 — "Tenant Onboarding Owner Auto-Assignment" (PR #74)
- GitHub: Issue #14 — "Authentication and RBAC Foundation" (PR #19)
- CURRENT_STATE.md — X-10 and X-11 sections

## Supersedes

None

## Superseded By

None
