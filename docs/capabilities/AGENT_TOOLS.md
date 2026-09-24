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

**One thing, and it is gated.** Arc can post a message to a Slack
channel the tenant has configured as a connector.

This section previously read "**Nothing**", and that finding is what
drove ADR-013. It is worth keeping the history visible: the gap was never
a permissions gap or a configuration gap — the capability did not exist
at any layer.

### The tool catalogue

| Tool | Risk | Policy | Reaches |
|---|---|---|---|
| `check_service_health` | low | `ALLOW` | Simulated internal services |
| `grant_temporary_access` | high | `REQUIRE_HUMAN_APPROVAL` | Internal only |
| `post_channel_message` | high | `REQUIRE_HUMAN_APPROVAL` | **Slack, for real** |

### Connectors now have a write side

The read contract is unchanged:

```python
async def fetch(credential, target, limit) -> ProviderFetchResult
```

Alongside it, a **separate** protocol declares the write side:

```python
async def act(credential, action) -> ProviderActionResult
```

Separate rather than a second method on the same protocol, for two
reasons. Read-only adapters are not forced to grow a method that exists
only to raise; and "can this provider act?" is answerable by shape rather
than by calling it and catching an error. Today only Slack implements it.

### Read and act are different credentials

`connector_credentials` is keyed by `(tenant, provider, scope)`. A token
that can read a channel is not a token that can post to it — the scopes
differ at Slack, and the blast radius differs at Arc: a leaked read
credential exposes data, a leaked act credential speaks as the company.

There is no ENV fallback for act credentials. The read path allows one for
development convenience; a development convenience that posts to a real
workspace is not a convenience.

### What still has no path

Email and document workflows. Both need a provider Arc does not have,
which means a new credential type and a new trust boundary — a decision
of its own, not an extension of this one.

### The prompt blocker, for the record

The tool-proposal prompt used to hardcode the catalogue as an English
string, so `grant_temporary_access` was invisible to the proposal path and
any tool added to the registry stayed dead to the Agent. The prompt
builder now receives the registry (name, description and input schema
only — risk level, required permissions and execution policy are
authorization state and never reach a prompt).

## 4. What building external actions required

In dependency order, as scoped before the work started. Items 1–3 and 5
are done; item 4 is not.

1. ~~**Pass the registry into the prompt.**~~ Done. Until it was, new
   tools were unreachable — the smallest change and the largest unblock.
2. ~~**Extend the adapter contract** with a write side.~~ Done:
   `ProviderActionAdapter.act`, its own credential scope, its own
   permission (`connector:act`).
3. ~~**Define external tools in the platform registry.**~~ Done:
   `post_channel_message`. Anything that leaves the tenant boundary is
   `REQUIRE_HUMAN_APPROVAL`, and that is now enforced at ToolDefinition
   construction rather than left to reviewer diligence.
4. **Native tool calling.** Still outstanding. Tool selection is
   *"return EXACTLY a JSON object"* followed by fence-stripping and
   parsing. Structured tool calling and `response_format` are supported
   by the configured provider and unused.
5. ~~**Idempotency.**~~ Resolved without a second mechanism. `fetch` is
   safe to retry and posting a message is not, so the **single-use
   approval** is the guarantee: it is consumed atomically before the
   handler runs, and the same approval cannot post twice. The cost is
   deliberate — an action that fails after consumption leaves the
   approval spent, so a failure can cost a re-request and can never cost
   a duplicate message.

## 4a. The five gates an action passes

None of them is the model.

| Gate | What it is | What it stops |
|---|---|---|
| Capability | `external_action` (V2-ADR-004) | A platform administrator switching off all outbound actions, per tenant or globally, without a deploy |
| Permission | `connector:act`, declared by the tool | `tool:execute` alone; an employee via Agent; a webhook-triggered execution |
| Approval | HIGH risk + `REQUIRE_HUMAN_APPROVAL`, bound to a digest of the validated arguments, single use | Acting without a named human decision; editing the message or the channel after approval; posting twice |
| Destination | The target must match an ACTIVE connector the tenant configured, matched in SQL | A channel name proposed by a model — or by anything that reached the model's input — addressing a destination nobody set up |
| Credential | Resolved at `CredentialScope.ACT` | Borrowing the read token to post |

Measured, with the fake provider recording what would have been sent:

| Attempt | Result | Posted |
|---|---|---|
| Attempt the action | 200 `approval_required` + approval id | nothing |
| Approve it | 200 `approved` | nothing |
| Requester spends it, sending no arguments | 200 `executed` + provider reference | the message, once |
| Spend it again | refused | nothing further |
| Resume with a different message | refused (digest mismatch) | nothing |
| Resume with a different channel | refused (digest mismatch) | nothing |
| `tool:execute` without `connector:act` | denied, `authorization_denied` | nothing |
| Destination not configured | failed | nothing |
| Read credential only | failed, `missing_act_credential` | nothing |
| Capability disabled | failed, `capability_disabled` | nothing, and nothing decrypted |

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

**Evidence before expansion.** When this was written Arc had two tools and
no external action, and the correct next step was one real external action
end to end, through the existing architecture, with approval and audit.

That has now been done (ADR-013), and the shape held: every gate the
action passes was machinery Arc already had. The recommendation therefore
stands unchanged, but for a better reason than "we have not tried yet" —
the adapter route works, so a broker would have to earn its extra trust
boundary against a working alternative rather than against a gap.

The open question is no longer architectural. It is which integrations
customers actually want, and whether several are wanted at once — the
first of the conditions below.

### What would change this

Reconsider if: several integrations are needed at once and the adapter
work becomes the bottleneck (each provider is its own `act`
implementation, and that cost recurs); per-user OAuth (rather than per-tenant
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
| Secrets | AES-256-GCM, key-versioned, one credential per `(tenant, provider, scope)`, never returned by any API |
| Act credentials | A separate row from the read credential, no ENV fallback, decrypted narrowly for one call (ADR-013) |
| Secrets and the LLM | No credential is ever placed in a prompt; the model receives only ApprovedContext |
| Audit | Every tool execution records tenant, principal, tool, version, risk, redacted input summary and outcome |

## 7. Summary

Arc's Agent security model is sound and already implemented. What Arc
lacked was not safety but **capability**: two internal tools, read-only
connectors, and a proposal prompt that could not see the registry.

All three are addressed. Arc now has one real external action, and it
reaches the outside world through five gates that all existed already —
the capability ceiling, the RBAC matrix, the approval gate, the connector
configuration and the credential encryption. Nothing new was invented to
make it safe; the write side was built to fit what was already there.

That is the evidence ADR-013 wanted before reconsidering a broker. The
shape holds. The next question is not "is this safe" but "which
integrations do customers actually want", and the conditions for
revisiting the broker decision are in §5.
