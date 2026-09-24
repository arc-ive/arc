# Arc — Skills

What a Skill is, how it differs from a Tool and from the Agent, and
which Skills are justified by the product as it stands today.

Every behaviour below was executed against a running instance. Observed
statuses are quoted from real responses.

---

## 1. What a Skill is

A Skill is a **tenant-owned business procedure**, expressed as data
rather than code. It is the company's way of saying "this is how we do
this", in a form Arc can execute under its own rules.

A Skill declares:

| Field | Meaning |
|---|---|
| `purpose` | What the procedure is for |
| `inputs` | Named inputs the caller must supply |
| `preconditions` | What must be true before it may run |
| `steps` | The human-readable procedure |
| `constraints` | What it must not do |
| `allowed_tools` | The **only** tools it may call |
| `approval_required` | Whether the Skill itself is gated |
| `expected_output` | What a successful run produces |
| `failure_behavior` | What happens when it fails |
| `risk` | Advisory classification |

Skills are **tenant-owned**: each company writes its own, and they never
cross a tenant boundary.

## 2. Skills vs Tools vs Agents

The three are frequently confused, and the distinction is the whole
security model.

| | Owned by | What it is | Can it act? |
|---|---|---|---|
| **Tool** | Platform | A concrete capability with an input schema, required permissions, risk level and execution policy | Yes — the only thing that acts |
| **Skill** | Tenant | A procedure that orchestrates permitted tools | Only through tools it declares |
| **Agent** | Platform | A bounded orchestrator that chooses which Skill to run next | Only through Skills |

The chain is strict:

```
Agent  ->  SkillExecutionService  ->  ToolExecutionService  ->  Tool
```

- The Agent holds **no** tool registry and **no** reference to
  `ToolExecutionService`. Every action it can cause flows through a
  Skill.
- A Skill cannot reach a tool it did not declare.
- `ToolExecutionService` is the single choke point where authorization,
  policy, approval, validation, execution and audit happen.

A tenant writing a Skill therefore cannot grant itself capability. It
can only compose capability the platform already approved.

## 3. Who can invoke a Skill, and what it requires

| Action | Permission |
|---|---|
| Read Skills | `skill:read` |
| Create / update / delete | `skill:create` / `skill:update` / `skill:delete` |
| Execute | `skill:execute` **and** every permission the called tools declare |

`skill:execute` is not a master key. A caller holding it but missing a
permission a tool declares is refused at the tool boundary.

In the reference environment both `company_administrator` and
`operations_user` hold `skill:execute`; `employee` does not.

## 4. What is enforced, measured

Executed against `ref-acme-technologies-incident-response`:

| Attempt | Observed |
|---|---|
| Declared tool, preconditions satisfied, inputs supplied | `status: succeeded`, 1 step |
| Tool **not** in `allowed_tools` | `status: denied`, `error_kind: disallowed_tool` |
| Precondition not asserted | `status: precondition_failed` |
| Declared inputs missing | `status: failed`, `error_kind: invalid_skill_inputs` |

All four are structured **200** responses. A controlled outcome is not
an error — the same convention as `POST /agent/runs`.

## 5. Approval

Two independent gates, which V2-ADR-011 says must not be merged:

- **Skill-level** — `approval_required: true` stops the Skill before any
  tool call.
- **Tool-level** — a tool whose policy is `REQUIRE_HUMAN_APPROVAL` stops
  that call, even inside a Skill that is not itself gated.

This is why a low-risk-looking Skill cannot smuggle a high-risk action:
the tool's own policy still applies. See `APPROVALS.md`.

## 6. Execution recording

Every run produces a `skill_execution_records` row carrying the tenant,
principal, skill id and version, status, error kind and per-step
outcomes. Persistence is best-effort — a write failure is logged, not
raised — so the record is an audit aid rather than an authoritative
ledger.

## 7. Tenant boundaries

Skills are tenant-scoped in the path, the SQL and the trusted context. A
Skill belonging to one tenant is not visible or executable from another,
and the tenant is never taken from the request body.

## 8. Which Skills are justified today

**Deliberately few.** The platform tool catalogue currently holds three
tools (the third, `post_channel_message`, is the first that acts outside
Arc — ADR-013):

| Tool | Risk | Policy |
|---|---|---|
| `check_service_health` | low | `ALLOW` |
| `grant_temporary_access` | high | `REQUIRE_HUMAN_APPROVAL` |
| `post_channel_message` | high | `REQUIRE_HUMAN_APPROVAL` |

A Skill can only compose what tools allow, so the honest answer is that
Arc supports a handful of real Skills, not a catalogue. Inventing more
would be writing procedures for capabilities that do not exist.

A Skill that reaches `post_channel_message` gains no shortcut: the tool's
own `REQUIRE_HUMAN_APPROVAL` policy stops the call even inside a Skill
that is not itself gated (§5), and the Skill's caller must still hold
`connector:act`. That is the point of keeping the two approval gates
separate.

### Recommended now

**1. Service health check** *(exists in shape as Incident Response)*
Allowed tools: `check_service_health`. No approval. The simplest
end-to-end proof that the chain works.

**2. Incident triage** *(the current reference Skill)*
Allowed tools: `check_service_health`. Preconditions assert the caller
is entitled to run incident procedures. Demonstrates preconditions,
declared inputs and step recording.

**3. Temporary access request**
Allowed tools: `grant_temporary_access`. Skill-level approval stays
**false** deliberately — the tool's own `REQUIRE_HUMAN_APPROVAL` policy
is what gates it, and setting both would be the merge V2-ADR-011
forbids. This is the Skill that demonstrates the full approval and
resume loop.

### Not yet justified

Knowledge retrieval, document workflows and email workflows are all
reasonable Skills — and none of them has a tool behind it. Knowledge
retrieval happens through Ask Arc's retrieval path rather than a tool,
and there is no document or email tool in the registry. They become
Skills when issue #304 adds the tools, not before.

## 9. A design observation worth knowing

`satisfied_preconditions` is **supplied by the caller**. The Skill
declares what must be true; the caller asserts that it is. Arc checks
that the assertion covers the declared preconditions, not that the
assertion is true.

This is sound where preconditions are procedural ("the change window is
open") and weaker where one restates an authorization fact — the
reference Skill's `user_has_incident_response_permission` reads like a
permission check but is not one. Real authorization is enforced
separately and unconditionally at the tool boundary, so an untrue
assertion cannot widen what actually runs; it can only make the audit
trail read better than reality.

Worth tightening if preconditions ever start carrying security meaning.
