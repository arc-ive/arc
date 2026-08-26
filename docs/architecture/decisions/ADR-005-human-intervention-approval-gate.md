# ADR-005: Human Intervention Approval Gate

## Status

Proposed

## Date

2026-08-26

## Decision Owners

- Bala (Person A) — AI/Intelligence architecture, AI Tools integration,
  security architecture; author
- Bharath (Person C) — AI Tools platform boundary; approval-gate foundation
  implementer
- Joe (Person B) — Skills orchestration; future consumer of this contract

## Context

Arc's AI Tools subsystem enforces a three-mode execution policy
(`ToolExecutionPolicyMode`: ALLOW / DENY / REQUIRE_HUMAN_APPROVAL). Today
`REQUIRE_HUMAN_APPROVAL` fails closed inside
`ToolExecutionService.execute_tool(...)`: the attempt is denied with an
audited `error_kind="requires_human_approval"` record and a controlled
`ToolDeniedError` (`src/arc/services/tools.py`). This was a deliberate V1
stub recorded by ADR-004, which defined the bounded Intelligence→Tools
calling contract and explicitly deferred the approval workflow.

TRD §17.3 and PRD §21 now require that deferred piece: high-risk or
policy-restricted actions must be executable AFTER an explicit human
approval, without weakening any existing boundary:

```text
LLM proposal
    ↓ application validation
ToolExecutionService authorization/policy
    ↓ REQUIRE_HUMAN_APPROVAL
approval request (persisted, untrusted-data-free)
    ↓ human decision (RBAC-gated)
subsequent AUTHORIZED call through ToolExecutionService
    ↓ binding re-validation + one-time consumption
execution + existing audit trail
```

Constraints that shape this ADR:

- ToolExecutionService is, and remains, the SINGLE authorization/
  execution/audit choke point (ADR-001, PR #40 review consensus).
- The LLM is untrusted (ADR-004): a proposal is a request, never a grant;
  the same applies to approvals — the LLM can never create, approve,
  consume, or reference-manipulate approval state.
- Skills are a separate orchestration layer (Joe): they will consume the
  same ToolExecutionService boundary and receive NO special approval
  mechanism.
- No background workers/schedulers/queues exist in Arc today, and none may
  be introduced by this decision (lazy expiration instead).
- The repository has an established audit convention:
  `tool_execution_records` owns ACTUAL executions; this ADR adds a
  separate, non-overlapping lifecycle record for APPROVALS only.

## Problem

Today a REQUIRE_HUMAN_APPROVAL tool can NEVER be executed, so high-risk
capability cannot ship even when a human explicitly wants it executed.
Worse, without a persisted approval artifact there is no way to audit that
a human decision occurred. What is missing is a precise contract for:

1. what an approval request IS (identity, binding, contents);
2. who may create/read/decide/consume one;
3. how a decision binds to the EXACT validated request that later executes;
4. how one-time consumption is atomic under concurrency;
5. how the whole mechanism fails closed.

## Decision

### 1. Approval request model

A new tenant-scoped aggregate, conceptually persisted as
`approval_requests`, is CREATED BY ToolExecutionService itself at the
moment its policy evaluation returns REQUIRE_HUMAN_APPROVAL (replacing
today's bare denial on that path — the attempt remains denied/failed-closed
in the SAME call; creation of the request does not authorize anything).

Persisted fields (metadata-only):

| Field | Purpose |
|---|---|
| id | server-minted UUID (PK); opaque, non-enumerable intent |
| tenant_id | trusted tenant; NOT NULL; FK to tenants |
| requester_user_id | trusted principal whose invocation triggered the policy |
| tool_name | resolved registered tool name |
| tool_version | resolved tool version at proposal time |
| arguments_digest | SHA-256 hex of the CANONICAL VALIDATED arguments (see §2) |
| input_summary | existing redacted `_summarize(raw_input)` payload |
| status | PENDING / APPROVED / REJECTED / EXPIRED / CONSUMED |
| expires_at | created_at + TTL (V1: 24 h) |
| decided_by / decided_at | approver identity + decision timestamp (nullable) |
| consumed_by / consumed_at | principal + timestamp of the consuming execution (nullable) |
| execution_record_id | FK-reference to the `tool_execution_records` row of the consuming execution (nullable) |
| created_at | immutable |

Deliberately NOT persisted: raw tool arguments (only digest + redacted
summary), prompts, LLM output, model identifiers, secrets, credentials,
content bodies, cross-tenant references.

### 2. Canonical serialization and digest

After the tool's pydantic input model VALIDATES `raw_input`, the validated
model is serialized canonically:

```text
canonical_bytes = UTF-8(
    json.dumps(validated_model.model_dump(mode="json"),
               sort_keys=True, separators=(",", ":"))
)
arguments_digest = SHA-256(canonical_bytes) as lowercase hex
```

The digest is computed over the POST-validation form — the exact value the
consuming execution will re-validate — so approval binds to what will run,
not to whatever the LLM emitted. Because serialization is canonical
(sorted keys, no whitespace), the same logical arguments always produce the
same digest regardless of key order or formatting in the original payload.

### 3. What is being approved

An approval authorizes ONE future execution of `(tool_name,
tool_version, canonical arguments)` for ONE tenant — nothing else. It does
not confer permissions, does not select tenants/principals, does not
authorize any other tool, and does not survive tool/schema/policy changes
(§ Binding validity).

### 4. State machine

```text
PENDING ──approve──► APPROVED ──consume──► CONSUMED (terminal)
   │
   ├──reject──► REJECTED (terminal)
   └──expire───► EXPIRED  (terminal)
```

- Transitions are total and irreversible: no terminal state ever returns
  to PENDING/APPROVED.
- **CONSUMED is an explicit terminal STATE**, not side-metadata.
  Rationale: "one-time consumable" then becomes a queryable state-machine
  invariant (`status='CONSUMED'`) enforced by a single conditional UPDATE
  (`WHERE status='APPROVED' ... SET status='CONSUMED'`), which is atomic
  under concurrency and trivially auditable; metadata-only consumption
  would need additional nullable-column reasoning to prove the same
  guarantee.
- Expiration is LAZY: `expires_at` is checked at every read/decision/
  consume touchpoint; an expired PENDING request transitions to EXPIRED at
  that touchpoint (controlled write, no background worker).

### 5. Authorization model

New centralized permissions (existing matrix conventions, default DENY):

| Permission | Granted to | Purpose |
|---|---|---|
| `approval:read` | PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER | list/get approval requests for the tenant |
| `approval:decide` | PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR | approve/reject decisions |

OPERATIONS_USER deliberately does NOT receive `approval:decide`: current
authoritative documentation (PRD §7, TRD §7) assigns incident response and
monitoring to operations, but final authority over high-risk actions rests
with administrators; extending decide-rights later is a one-line matrix
change behind the same review gate. EMPLOYEE: nothing.

**Requester ≠ approver**: a principal MAY NOT decide a request they
requested. Enforced in the service on every decision (tenant-scoped lookup
compares `requester_user_id` to the deciding principal's trusted user_id);
violation yields the same generic denial as any other unauthorized
decision. Rationale: eliminates the single-principal compromise path and
the confused-deputy case where an operator approves their own blocked
action.

### 6. Request binding and consumption semantics

A subsequent authorized caller executes an approved action by invoking
`ToolExecutionService.execute_tool(...)` with the proposed tool/arguments
PLUS the `approval_id` reference. Before ANY execution, the service
atomically consumes the approval via one guarded transition:

```text
UPDATE approval_requests
SET status='CONSUMED', consumed_by=:principal, consumed_at=now(),
    execution_record_id=:audit_ref
WHERE id=:approval_id
  AND tenant_id = :trusted_tenant          -- tenant binding
  AND requester_user_id = :trusted_user    -- optional V1 rule: same
                                           -- requester must re-present
  AND tool_name = :tool_name               -- binding checks
  AND tool_version = :tool_version
  AND arguments_digest = :fresh_digest     -- canonical args re-digested
  AND status = 'APPROVED'
  AND expires_at > now()
```

Zero rows updated ⇒ the approval was missing/expired/consumed/mismatched ⇒
fail closed with a controlled observation (no execution, no partial state).
One row ⇒ consumption is atomically exclusive: a concurrent consumer loses
(the row is already CONSUMED) and receives a controlled failure. Only after
successful consumption does the normal pipeline proceed: schema
re-validation, per-tool authorization, ALLOW-policy confirmation, handler
execution, existing audit record.

Consumption therefore RE-VALIDATES everything; the approval merely unlocks
a policy mode. It never substitutes for authentication, authorization,
schema validation, tenant isolation, or auditing — all of which run again
on the consuming call.

Binding validity rules (all fail closed):
- tool definition/schema changed since approval → fresh digest differs →
  mismatch → fail closed (new approval required).
- tool version changed → `tool_version` mismatch → fail closed.
- underlying policy changed → policy is RE-EVALUATED on the consuming
  call; approval only satisfies the REQUIRE_HUMAN_APPROVAL precondition —
  if policy has since become DENY, execution still fails closed.
- tenant context differs → tenant binding mismatch → fail closed.

### 7. Creation, reading, deciding

- CREATION: exclusively by ToolExecutionService on a
  REQUIRE_HUMAN_APPROVAL policy outcome. Not callable by Intelligence,
  Skills, the LLM, users, or any API. There is deliberately no
  "create approval request" endpoint.
- READ (list/get): tenant-scoped, `approval:read`, path-tenant
  consistency enforced as everywhere else. Responses carry safe metadata
  only (id, tool name/version, status, timestamps, redacted summary,
  requester/approver ids) — never arguments, digests-as-data beyond the
  opaque hex, or outcomes of other tenants.
- DECIDE (approve/reject): tenant-scoped, `approval:decide`,
  requester ≠ approver, PENDING-only, not expired (expired decisions are
  themselves refused — the transition to EXPIRED wins). Decisions are
  idempotent-hostile by design: deciding an already-decided request is a
  controlled failure, not a silent repeat.

### 8. Relationship with ADR-004

ADR-004 defined REQUIRE_HUMAN_APPROVAL as fail-closed and deferred the
mechanism. This ADR COMPLETES that contract without weakening it:

- the denial-with-audit behavior at policy time is preserved (now paired
  with request creation);
- execution continues to require a fully authorized
  `ToolExecutionService.execute_tool(...)` call — the approval only flips
  the policy mode's answer from "never" to "yes, once, for this exact
  bound request";
- ADR-004's single-iteration and untrusted-LLM invariants apply unchanged
  to the consuming call.
ADR-004 requires no modification; this ADR references it as the parent
contract.

### 9. Relationship with Skills

Skills remain a separate orchestration layer (Joe). Skills receive NO
special approval mechanism, CANNOT bypass ToolExecutionService, and MUST
use the same application-owned boundary. When Skill execution needs
approved actions it consumes THIS contract (same request format, same
consumption call) rather than creating another approval system. No
Intelligence-specific approval logic exists: the gate lives entirely in
the tools/platform layer.

## Alternatives Considered

1. **Approval state inside `tool_execution_records`** — rejected: conflates
   lifecycle audit (append-only facts about attempts) with mutable
   workflow state; would force mutable rows into an append-only audit
   contract and couple two retention policies.
2. **Approval directly inside UnifiedIntelligenceService** — rejected:
   duplicates policy/state machinery inside Intelligence, creates an
   Intelligence-specific executor temptation, and breaks the Skill
   symmetry (Skills would need their own copy or a dependency on
   Intelligence).
3. **Approval directly inside Skills** — rejected: same duplication in
   reverse; Skills execution does not exist yet, and pre-building it here
   would couple the gate to an unimplemented orchestrator.
4. **External workflow system (e.g., dedicated approval service/queue)** —
   rejected for V1: new infrastructure violates the no-new-infrastructure
   constraint and ADR-001's proportionality; revisitable if multi-system
   workflows emerge.
5. **Synchronous human approval inside `execute_tool`** (block the HTTP
   call until a human decides) — rejected: couples request lifetime to
   human latency, requires holding transactions/connections open, invites
   timeout/deadlock failure modes, and turns the execution choke point
   into a waiting room. Async request→decide→re-execute keeps every call
   short-lived and auditable.
6. **Metadata-only consumption (no CONSUMED state)** — rejected: a single
   guarded state transition is easier to prove atomic and audit than
   nullable-column reasoning; chosen explicitly over the alternative.

## Threat Model

| # | Threat | Mitigation |
|---|---|---|
| 1 | Approval replay | One-time CONSUMED transition; conditional atomic UPDATE; replay ⇒ zero rows ⇒ fail closed |
| 2 | Argument substitution | Fresh canonical digest recomputed from re-validated args; mismatch ⇒ fail closed |
| 3 | Tenant substitution | Trusted-context tenant must equal approval tenant; model/user-supplied tenant values are inert data |
| 4 | Privilege escalation | Approval grants no permission; consuming caller still needs `tool:execute` + all tool-declared permissions |
| 5 | Unauthorized decision | `approval:decide` + tenant scope + requester≠approver; generic denials |
| 6 | Requester self-approval | Prohibited (requester ≠ approver), service-enforced |
| 7 | Stale approval | 24 h TTL, lazy expiry at every touchpoint; expired ⇒ EXPIRED, cannot execute |
| 8 | Tool-version mismatch | Version bound in request + consumption check |
| 9 | Concurrent consumption | Single conditional UPDATE; exactly one winner |
| 10 | Approval-ID enumeration | Server-minted UUIDs; reads require `approval:read` + tenant scope; unknown/wrong-tenant IDs indistinguishable |
| 11 | LLM manipulation of approvals | LLM output never touches approval state: creation is internal to the policy path, decisions are RBAC-human-only, consumption requires a trusted authorized caller |
| 12 | Prompt injection via observation | Observation stays untrusted data; approval decisions are made by humans in the approval surface, never parsed from model text |
| 13 | Audit tampering | Two complementary records: immutable lifecycle (approvals) + immutable execution facts (tool_execution_records); neither writable through model output |
| 14 | Sensitive argument leakage | Raw arguments never persisted; redacted summary reuses existing minimization; digest is one-way |
| 15 | Bypassing ToolExecutionService | Structurally impossible: consumption transitions occur only inside ToolExecutionService during an otherwise-normal authorized execution |

## Testing Strategy (for the implementation slice)

Creation on REQUIRE_HUMAN_APPROVAL (request row + unchanged denial
observation) · digest determinism and sensitivity · TTL expiry lazy
transition · approve/reject/idempotency-conflict · requester≠approver ·
role matrix for read/decide · tenant scoping incl. cross-tenant refusal ·
binding mismatches (args/version/policy/tenant) each failing closed ·
concurrent double-consumption (exactly one winner) · execution-after-
consumption produces a normal audited `tool_execution_records` entry ·
archived/expired replay attempts · regression: ALLOW/DENY paths untouched.

## Rollout / Migration Considerations

New table + two matrix permissions land together in the foundation
implementation slice; bootstrap remains idempotent (`CREATE TABLE IF NOT
EXISTS` convention; no semicolons in SQL comments). Existing databases
gain the table additively; no backfill is required because no historical
approval state exists. Behavior change is strictly additive: tools that
previously hard-failed on REQUIRE_HUMAN_APPROVAL now additionally persist
an approval request — the denial-in-that-call semantics are preserved.

## Consequences

### Positive

High-risk tools become usable under explicit dual control · complete
human-decision auditability · concurrency-safe one-time consumption ·
Skill-symmetric by construction · no new infrastructure.

### Negative

Two-step execution latency for gated tools · requester≠approver requires
two distinct principals in demos · catalog growth must consider which
tools deserve REQUIRE_HUMAN_APPROVAL.

## Non-Goals / Future Work

Frontend/UI · notifications (email/Slack/web) · background expiry workers ·
queues · autonomous execution · multi-step workflows · delegation ·
escalation chains · multiple/quorum approvers · external approval systems ·
agent loops · Skill execution · production LLM providers · connector
redesign · any second execution boundary · approval-specific metrics
(later observability slice) · restore/unarchive APIs (explicitly out of
scope; see recovery-semantics note — archival reversibility belongs to the
Company Brain lifecycle, not this gate).
