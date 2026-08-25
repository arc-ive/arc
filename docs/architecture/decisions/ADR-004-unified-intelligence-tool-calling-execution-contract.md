# ADR-004: Unified Intelligence Tool-Calling Execution Contract

## Status

Accepted

## Date

2026-08-25

## Decision Owners

- Bala (Person A) — AI/Intelligence architecture, AI Tools architecture, author
- Joe (Person B) — Skills Engine / Unified Intelligence consumer review
- Bharath (Person C) — Observability / audit infrastructure review

## Context

Arc currently has two completed subsystems that do not yet touch:

1. **Unified Intelligence** (`src/arc/services/intelligence.py`): an
   authenticated tenant-scoped query API that retrieves knowledge strictly
   through `RetrievalService.approved_search`, assembles the Approved Context
   Contract, and reasons over it with a configurable LLM provider
   (deterministic provider today). Its docstring explicitly states that tool
   calling is not implemented.
2. **AI Tools** (`src/arc/services/tools.py`): a platform-owned static tool
   registry with per-tool JSON schemas, double authorization
   (`tool:execute` AND every tool-declared permission), ALLOW/DENY/
   REQUIRE_HUMAN_APPROVAL execution policies, pydantic input validation,
   and redacted tenant-scoped `tool_execution_records` auditing — exposed
   today only through `POST /tenants/{tenant_id}/tools/{name}/execute`.

TRD §8 (Unified Intelligence flow) and §39 (minimum demonstration) require
these to connect: reasoning may select and execute an approved tool under
application control. PRD §14/§15 define the same relationship at product
level. ADR-001 already fixes the governing principle ("the LLM must not
bypass authorization, tenant isolation, approved Tools, or human-approval
requirements, and must not execute arbitrary code") and records "custom
lightweight tool-calling Agent" as the direction with any framework kept
non-permanent.

This ADR defines the **execution contract** for that connection before any
implementation exists, so the implementation engineer makes no further
architectural decisions. It deliberately scopes V1 to a single tool
execution iteration.

## Decision

### 1. Central invariant

> **The LLM may PROPOSE an action; only the APPLICATION validates,
> authorizes, and executes it.**

Model output is untrusted data end-to-end. A proposal is a request, never
a grant. Nothing in the model's output can influence tenant identity, user
identity, role, permission evaluation, registry membership, schemas, or
policy outcomes.

### 2. Tool proposal schema

The LLM layer emits at most one structured proposal per query, validated by
a strict pydantic model in the domain layer:

```text
ToolProposal:
    tool_name: str          (required)  — resolves against the platform registry
    arguments: dict         (required)  — validated later against the tool schema
```

- No additional fields in V1. `reason`/`proposal_id`/`metadata` are
  rejected as speculative: `reason` risks laundering untrusted content into
  prompts/audit, ids are minted server-side, and no consumer exists.
- Malformed proposals (wrong shape, unknown fields when the model forbids
  them, non-string names, non-dict arguments) fail closed to the defined
  "no usable proposal" outcome — they never raise out of the intelligence
  path nor reach the tool subsystem.

The deterministic provider produces the proposal deterministically from the
approved context (e.g., an explicit structured block), keeping tests
deterministic and making the production-provider swap safe: whatever the
model emits must parse into this schema or the proposal is discarded.

### 3. Execution pipeline (single authority path)

```text
LLM output
    ↓ parse + validate ToolProposal            (application; untrusted)
    ↓ resolve tool_name through ToolRegistry    (unknown → controlled failure)
    ↓ validate arguments against tool schema    (application; pydantic)
    ↓ authorize                                 (AuthorizationService, reused)
    ↓ apply execution policy                    (ALLOW / DENY / REQUIRE_HUMAN_APPROVAL)
    ↓ execute                                   (ToolExecutionService)
    ↓ observation                               (bounded, structured, untrusted)
    ↓ one final reasoning pass
    ↓ final answer (+ citations, + execution reference)
```

Unified Intelligence MUST call `ToolExecutionService.execute_tool(...)` —
passing the trusted `TenantContext`, the authenticated principal, and the
existing `AuthorizationService` exactly as the controller does today. It
MUST NOT re-implement authorization, duplicate permission logic, touch the
registry internals, import handlers, access repositories/credentials on the
model's behalf, or construct dynamic dispatch from model output. Unknown
tool names resolve to nothing: no dynamic lookup, no import, no execution;
the outcome is a controlled failure observation and the standard audit
trail already produced by the tool subsystem.

Tenant/user identity for any execution comes exclusively from the trusted
`TenantContext`/principal held by the application. A proposal argument
named or resembling `tenant_id`, `user_id`, `role`, or `permissions` is
ordinary untrusted argument data: it is either rejected by the tool schema
or ignored — it can never redirect execution across tenants because the
execution boundary derives isolation from the trusted context, not from
arguments.

### 4. Argument validation

Arguments are validated exclusively by the resolved tool's declared pydantic
schema inside the existing execution service — malformed shapes, missing
required fields, unexpected fields, wrong types, invalid values, and
oversized inputs fail closed exactly as they do for direct API execution
today. The model's claim that arguments are valid has zero authority.

### 5. Execution policy (V1)

- **ALLOW** — executes after the full pipeline above passes.
- **DENY** — never executes; produces a controlled observation and the
  existing audited denial semantics.
- **REQUIRE_HUMAN_APPROVAL** — V1 has no approval workflow, so this mode
  FAILS CLOSED identically to its existing stub behavior: no execution, a
  controlled observation, audited outcome. This ADR preserves the extension
  point: a future Human Intervention slice replaces the stub with an approval
  lookup; until then no bypass path exists or may be added.

### 6. Single-iteration boundary (V1)

Exactly one optional propose→authorize→execute→observe cycle per query,
followed by one final reasoning pass, then STOP. Explicitly deferred:
multi-tool chains, recursive/model-driven retries, autonomous planning,
long-running agents, dynamic delegation, memory/state, Skill selection
(Skills are not executable today), connectors-as-tools. Any of these
requires a future ADR amendment.

### 7. Observation contract

The second reasoning pass receives a bounded, structured observation
derived from the execution result/record — success/failure kind, sanitized
summary fields already enforced by the tool's output model and audit
redaction. It NEVER receives: secrets/credentials, internal authorization
detail beyond coarse outcome, raw database/provider errors, other tenants'
data, unbounded output, or hidden system state. The observation is untrusted
data in the prompt, clearly delimited from system instructions; because
authorization and policy live entirely in the application, a manipulated
observation cannot convert into privilege.

### 8. Failure semantics (all fail closed)

| Condition | Behavior |
|---|---|
| Invalid/unparseable proposal | Treated as no proposal; normal cited answer path |
| Unknown tool | Controlled failure observation; no execution; audited by tool subsystem |
| Invalid arguments | Controlled failure observation; handler never ran |
| Authorization denied | Controlled denial observation; audited DENIED |
| DENY policy | Same as denied |
| REQUIRE_HUMAN_APPROVAL | Fail-closed denial observation; audited |
| Tool execution failure | Failure observation; audited failed status |
| Second-pass LLM failure | Existing LLM failure semantics (generic error, no partial answer) |

No internal details, stack traces, or provider errors leak through the API;
external behavior remains the established generic-error contract.

### 9. Auditing

Reuse `tool_execution_records` unchanged — every attempt (granted or
denied) already produces who/tool/version/outcome/risk/redacted summaries.
Proposals that never resolve to a real tool produce no new audit type; the
intelligence answer marks degraded mode. No second audit system. Never
logged/stored: secrets, credentials, sensitive argument values, raw prompt
content, PII, unsafe full outputs (existing redaction/truncation applies).

### 10. Prompt-injection stance

Retrieved documents, user input, and tool observations are untrusted and
may manipulate the proposal. The architectural defense is structural, not
filtering: regardless of what the model says, execution requires registry
resolution + schema validation + application authorization + tenant context
+ policy enforcement, all outside the model's control. Broader injection
hardening remains deferred to production-provider/agent-security work and
is NOT claimed by this ADR.

### 11. Future API contract (not implemented here)

`POST /tenants/{tenant_id}/intelligence/query` gains ADDITIVE response
fields only (e.g., a bounded `tool_executions` reference list mirroring
safe metadata). Request shape, permissions (`knowledge:read`), error codes,
and all existing fields remain unchanged. No new public endpoints.

## Alternatives Considered

- **A — LLM directly invokes tools (function-calling runtime):** rejected —
  dissolves the application authority boundary ADR-001 mandates; the model
  could choose tenants/permissions and execute unvalidated code paths.
- **B — Unified Intelligence implements its own authorization/execution for
  proposed tools:** rejected — duplicates the tool subsystem's security
  logic, creating two divergent enforcement points for one invariant.
- **C — Central execution boundary (SELECTED):** reuse
  `ToolExecutionService` as the single choke point; intelligence becomes
  one more authorized caller alongside the REST controller. Smallest trust
  surface, single audit trail, direct reuse of reviewed code.
- **D — Full autonomous agent loop now:** rejected/deferred — unbounded
  iteration multiplies risk before the one-shot contract is proven; ADR-001
  keeps agent frameworks non-permanent and the lightweight direction intact.

## Consequences

### Positive

- Closes the TRD §8/§39 reasoning→action gap with zero new infrastructure.
- Deterministic-testable end to end; production-provider swap stays safe.
- Every safety property inherited from already-reviewed code paths.

### Negative

- One tool in catalog; single iteration limits demonstrated capability.
- Proposal parsing adds a strict validation step to the LLM layer.

### Risks

Deterministic proposal fidelity differs from production models (mitigated
by schema-strict parsing); ownership of agent-side Skill selection overlaps
Joe's future Skills execution work (coordination required before that
extension); scope creep toward a full agent loop (guarded by §6).

## Security Considerations

Threats and mitigations: prompt-injected malicious proposal → registry+
schema+authz+policy gates; unauthorized tool request → per-tool permissions
denied and audited; cross-tenant arguments → trusted-context isolation,
argument cannot override; unknown tool → no dynamic resolution; schema/policy/
human-approval bypass → impossible without modifying application code; output
poisoning → observation is untrusted, delimited, non-privileged; sensitive
output leakage → existing output models + audit redaction; repeated/recursive
execution → single-iteration bound; audit bypass → audits occur inside the
execution boundary intelligence must call.

## Testing / Validation (implementation readiness)

The contract makes these tests mechanical: valid proposal happy path;
malformed proposal treated as absent; unknown tool; invalid arguments;
unauthorized caller; cross-tenant attempt; DENY; REQUIRE_HUMAN_APPROVAL;
handler execution failure; successful observation folded into answer;
second-pass failure semantics; audit rows present for granted/denied;
one-iteration termination; additive-response backward compatibility.

## Related Documents

ADR-001 (governing principles), ADR-002, ADR-003; PRD §14/§15/§26;
TRD §8, §14, §17.3, §25, §39; PRs #31 (tools), #33 (intelligence).

## Supersedes / Superseded By

None / None.
