# Arc — Agent and External Tools

What the Agent is, what it can and cannot reach, what would be required
to give Arc real external actions, and a decision on Arcade.

Findings below come from reading the running system, not from intent.

---

## 1. The Agent

One bounded orchestrator. Not a fleet, not a hierarchy.

```
goal
  |
Agent            chooses the next Skill, at most MAX_AGENT_STEPS (3)
  |
SkillExecutionService     the single action boundary
  |
ToolExecutionService      authorization, policy, approval, audit
  |
Tool
```

What the Agent explicitly does **not** hold: a tool registry, tool
handlers, or a reference to `ToolExecutionService`. Every action it can
cause flows through a Skill. This is enforced by construction — the
module imports neither.

Bounded outcomes: `succeeded`, `failed`, `approval_required`,
`max_steps_reached`. All are structured 200 responses.

The Agent requires a decision-capable LLM. The deterministic provider
declares itself not decision-capable, so agent runs fail closed with
`agent_decision_unavailable` — visible in the UI as *"No decision
capability is configured, so the agent stopped rather than guess."*

## 2. The security model, and where the model sits in it

```
Agent / LLM        proposes        <- untrusted data
  |
Arc authorization  decides         <- deterministic
  |
tenant policy      decides
  |
approval if required
  |
tool execution
  |
audit
```

Model output is a **proposal**, never a decision. It is parsed with a
strict schema and discarded if malformed. Authorization, risk, approval
and execution are decided by deterministic services afterwards
(V2-ADR-012). No prompt can widen what a caller may do, because the
prompt is not consulted when deciding what a caller may do.

## 3. What Arc can actually do externally today

**Nothing.** This is the finding that governs everything below.

### The tool catalogue

| Tool | Risk | Policy | Reaches |
|---|---|---|---|
| `check_service_health` | low | `ALLOW` | Simulated internal services |
| `grant_temporary_access` | high | `REQUIRE_HUMAN_APPROVAL` | Internal only |

Two tools, neither of which touches an external system.

### Connectors are read-only

The `ProviderAdapter` contract has exactly one method:

```python
async def fetch(credential, target, limit) -> ProviderFetchResult
```

Slack, GitHub, Google Drive and Linear adapters implement `fetch` and
nothing else. There is no `send`, `post`, `create`, `write` or `update`
anywhere in the connector layer. Connectors bring data **into** the
Company Brain; they cannot act on the outside world.

### The consequence

"Send an email", "file a ticket", "post to a channel" have **no path**
in Arc today — not a permissions gap, not a configuration gap. The
capability does not exist at any layer.

### A second blocker, in the Agent's own prompt

The tool-proposal prompt hardcodes the catalogue as an English string:

```
"Available tools: check_service_health (checks health of an external service)"
```

The prompt builder never receives the registry. `grant_temporary_access`
is therefore **invisible to the proposal path** — the model cannot
propose it because it is never told it exists. Every tool added to the
registry stays dead to the Agent until someone edits that string.

Adding external tools without fixing this yields tools no Agent can
ever choose.

## 4. What building external actions would require

In dependency order:

1. **Pass the registry into the prompt.** Until this is done, new tools
   are unreachable. Smallest change, largest unblock.
2. **Extend the adapter contract** with a write side — an `act()`
   alongside `fetch()`, with its own schema and its own permission.
   Read and write credentials should not be assumed interchangeable.
3. **Define external tools in the platform registry** with input
   schemas, required permissions, risk levels and execution policies.
   Anything that leaves the tenant boundary is `REQUIRE_HUMAN_APPROVAL`
   until there is evidence to relax it.
4. **Native tool calling.** Tool selection is currently *"return EXACTLY
   a JSON object"* followed by fence-stripping and parsing. Structured
   tool calling and `response_format` are supported by the configured
   provider and unused.
5. **Idempotency.** `fetch` is safe to retry; `send_email` is not. The
   bounded-retry logic in the LLM layer has no equivalent for actions,
   and an action tool needs an idempotency key before retries are safe.

## 5. Arcade — decision

**Recommendation: do not integrate Arcade now. Build the write side of
the existing connector architecture instead.**

The reasoning is about sequencing, not about Arcade's quality.

**Arc's blockers are not the ones Arcade solves.** Arcade provides a
catalogue of pre-built integrations and an auth broker. Arc's blockers
are (a) a prompt that cannot see its own registry and (b) an adapter
contract with no write method. Both are inside Arc. Adding Arcade would
leave both in place, and the new tools would be just as invisible to the
Agent as `grant_temporary_access` is.

**It would duplicate a secrets model Arc already has.** Arc encrypts
connector credentials with AES-256-GCM and key versioning, scoped one
credential per `(tenant, provider)`. An external tool broker introduces
a second place where tenant credentials live and a second trust boundary
to audit. That is a significant multi-tenant security decision to take
for convenience.

**It would sit inside the choke point Arc's model depends on.** Every
action must pass `ToolExecutionService` for authorization, policy,
approval and audit. A broker that executes actions itself either sits
behind that boundary — in which case it is an adapter, and Arc's own
adapter contract is the cheaper shape — or beside it, which breaks the
guarantee the whole design rests on.

**Evidence before expansion.** Arc has two tools and no external action.
The correct next step is one real external action end to end, through
the existing architecture, with approval and audit. That proves or
disproves the shape. Then reconsider a broker with evidence about which
integrations are actually wanted.

### What would change this

Reconsider if: several integrations are needed at once and the adapter
work becomes the bottleneck; per-user OAuth (rather than per-tenant
credentials) becomes a requirement, which is genuinely hard and is what
brokers are good at; or a compliance requirement makes a third-party
broker's attestations preferable to Arc's own.

Before any such integration: verify the licence permits commercial
multi-tenant use, confirm where credentials are stored and who can
decrypt them, confirm the data-retention position for tenant content
crossing the broker, and confirm actions can still be gated by Arc's
approval flow rather than the broker's.

## 6. Permissions, secrets and audit as they stand

| Concern | Current state |
|---|---|
| Tool permissions | Declared per tool; the caller must hold every one. `tool:execute` is not a master key. |
| Approval | Per-tool execution policy; see `APPROVALS.md` |
| Secrets | AES-256-GCM, key-versioned, one credential per `(tenant, provider)`, never returned by any API |
| Secrets and the LLM | No credential is ever placed in a prompt; the model receives only ApprovedContext |
| Audit | Every tool execution records tenant, principal, tool, version, risk, redacted input summary and outcome |

## 7. Summary

Arc's Agent security model is sound and already implemented. What Arc
lacks is not safety but **capability**: two internal tools, read-only
connectors, and a proposal prompt that cannot see the registry.

The first commit toward external actions is not an integration. It is
passing the tool registry into the prompt.
