# ADR-013: External Actions Through the Connector Architecture

## Status

Accepted

## Date

2026-09-24

## Decision Owners

- Platform engineering

## Context

`AGENT_TOOLS.md` §3 recorded the finding that governs this decision, and
it was one word: **nothing**. Arc could do nothing externally.

- The tool catalogue held two tools, `check_service_health` and
  `grant_temporary_access`, neither of which touched an external system.
- The `ProviderAdapter` contract had exactly one method, `fetch`. Slack,
  GitHub, Google Drive and Linear implemented it and nothing else. There
  was no `send`, `post`, `create`, `write` or `update` anywhere in the
  connector layer.

So "send an email", "file a ticket", "post to a channel" had no path in
Arc — not a permissions gap and not a configuration gap. The capability
did not exist at any layer.

§4 of the same document set out what building it would require, in
dependency order, and §5 recorded the build-vs-integrate decision: do not
add a broker; build the write side of the connector architecture Arc
already has, one real action end to end, and get evidence before
expanding.

The first item on that list — pass the tool registry into the proposal
prompt, so a newly added tool is not invisible to the Agent — shipped
separately. This ADR is the rest of the first slice.

The constraint that shapes it: an external action is the one thing Arc
does that a customer cannot undo by deleting a row. A wrong answer from
Ask Arc is embarrassing; a message posted in the company's Slack under
the company's name is not retractable. So the path to an action has to be
longer than the path to a read, and every step of it has to be somewhere
a human already made a decision.

## Decision

**Arc gains a write side to the connector architecture, and exactly one
external action tool: `post_channel_message`.**

### The adapter contract

A new `ProviderActionAdapter` protocol declares `act(credential, action)`,
returning a validated `ProviderActionResult` carrying the provider's own
reference for what was created. It is a **separate protocol** from
`ProviderAdapter`, not a second method on it:

- read-only adapters are not forced to grow a write method that raises;
- "can this provider act?" is answerable by shape rather than by calling
  it and catching an error.

`SlackProviderAdapter` implements it via `chat.postMessage`. The endpoint
is a code-defined constant checked against the existing provider
allowlist, and the channel is resolved by NAME through the same
`conversations.list` lookup `fetch` uses — never from a tenant-supplied
URL or channel ID.

### Read and act credentials are different credentials

`connector_credentials` gains a `scope` column, and uniqueness moves from
`(tenant, provider)` to `(tenant, provider, scope)`. Every query names
the scope it wants, and `read` is the default everywhere, so the sync path
behaves exactly as before.

This is the core security decision. A token that can read a Slack channel
is not a token that can post to it — the scopes differ at Slack, and more
importantly the blast radius differs at Arc: a leaked read credential
exposes data, a leaked act credential speaks as the company. There is
also **no ENV fallback for act credentials**. The read path allows one for
development convenience; a development convenience that posts to a real
workspace is not a convenience.

### Five gates, none of them the model

`ExternalActionService` is the only route from a tool to the outside
world, and an action passes all of:

1. **The platform allows it.** `external_action` is a capability
   (V2-ADR-004), so a platform administrator can switch off every
   outbound action for one tenant or for all, without a deploy.
2. **The caller is authorized.** A new `connector:act` permission,
   separate from `connector:sync`. `tool:execute` alone is not enough,
   and `ToolExecutionService` checks it before any handler runs.
3. **A human approved this exact call.** Every action tool is HIGH risk
   with `REQUIRE_HUMAN_APPROVAL` — enforced at ToolDefinition
   construction, so a later action tool cannot arrive ungated by
   oversight. The approval binds tenant, tool, version and a SHA-256
   digest of the validated arguments, and is single-use (ADR-005).
4. **An administrator chose the destination.** The target must match an
   ACTIVE connector the tenant configured, matched in SQL. A channel name
   proposed by a model — or by anything that reached the model's input —
   cannot address a destination nobody set up.
5. **The credential is the act credential**, resolved by scope as above.

The LLM is nowhere in that list. It may *propose* a tool call; the
proposal is untrusted data, parsed and validated before any of the five
gates is reached (ADR-004).

### Single use is the idempotency answer

`fetch` is safe to retry; posting a message is not. Rather than invent a
second idempotency mechanism for actions, the approval IS the guarantee:
it is consumed atomically BEFORE the handler runs, so the same approval
cannot post twice.

The consequence is deliberate and is documented in a test: if the action
fails after consumption, the approval is spent and the requester must ask
again. That direction can cost a re-request; the other direction can cost
a duplicate message in a customer's workspace.

### Handlers still cannot open channels of their own

`ToolDefinition` gains an optional async `action_handler` alongside the
synchronous `handler`; exactly one is required. An action handler receives
a `ToolInvocation` carrying the trusted `TenantContext` and the
external-action service — injected, not imported, so a handler cannot
acquire the capability by reaching for it, and a tool service built
without the boundary fails closed rather than looking like a success that
did nothing.

The security guard that asserted no handler contains `httpx`, `socket`,
`open(` or an import is unchanged and still applies to every handler,
including this one.

## Options Considered

### Option 1 — Integrate an external tool broker (Arcade or similar)

Description: adopt a third-party catalogue of pre-built integrations and
its auth broker.

Advantages:

- Many integrations at once, with per-user OAuth already solved.
- Less adapter code to write and maintain per provider.

Disadvantages:

- It does not solve Arc's blockers. Those were a prompt that could not
  see its own registry and an adapter contract with no write method —
  both inside Arc. A broker leaves both in place.
- It duplicates a secrets model Arc already has. Arc encrypts connector
  credentials with AES-256-GCM and key versioning, scoped per
  `(tenant, provider)`. A broker adds a second place tenant credentials
  live and a second trust boundary to audit.
- It sits inside the choke point the whole design rests on. Every action
  must pass `ToolExecutionService` for authorization, policy, approval
  and audit. A broker that executes actions itself either sits behind
  that boundary — in which case it is an adapter, and Arc's own adapter
  contract is the cheaper shape — or beside it, which breaks the
  guarantee.

### Option 2 — A generic `call_webhook` / `http_request` tool

Description: one tool that takes a URL, method and body, gated by
approval.

Advantages:

- One tool covers every integration anyone will ever ask for.
- No per-provider adapter work at all.

Disadvantages:

- It is an SSRF primitive with an approval dialog in front of it. The
  provider allowlist exists precisely so that no tenant input selects a
  network destination; this hands that back.
- Nothing can be validated. A per-provider adapter knows what a valid
  target and a valid response look like and fails closed on anything
  else; a generic caller can only pass bytes along.
- The approval summary becomes unreviewable. An approver can judge "post
  this text to #ops"; they cannot judge a JSON body against an arbitrary
  endpoint.

### Option 3 — Add `send` to the existing `ProviderAdapter` protocol

Description: one protocol, two methods, read-only adapters raise
`NotImplementedError` from `send`.

Advantages:

- No new protocol; one place to look for what an adapter does.

Disadvantages:

- Every read-only adapter grows a method that exists only to fail, and
  "can this act?" becomes a question you answer by calling and catching.
- It invites sharing the credential between the two methods, which is the
  one thing this decision most wants to prevent.

### Option 4 — One real action through a separate write protocol (chosen)

Description: as recorded under Decision.

Advantages:

- Proves or disproves the shape with one narrow, useful action, which is
  what §5 asked for before any broker is reconsidered.
- Every gate reuses machinery that already exists and is already tested:
  the capability ceiling, the RBAC matrix, the approval gate, the
  connector configuration, the credential encryption.
- Nothing that leaves Arc can leave without a named human decision bound
  to the exact bytes.

Disadvantages:

- One provider and one action. Email and document workflows, which the
  issue names, are not covered by this slice.
- Per-provider adapter work recurs for each new integration, and if
  several are wanted at once that cost is real — which is exactly the
  condition §5 names for reconsidering a broker.
- A schema change (the `scope` column) on a repository with no migration
  tooling, applied through the idempotent `schema.sql` pattern.

## Rationale

Option 2 is the one worth naming explicitly as rejected, because it is
the tempting shortcut: a single `http_request` tool would have satisfied
the issue's letter in an afternoon. It also would have made Arc's
allowlist decorative and its approval summaries unreviewable. An approver
who cannot understand what they are approving is not a gate.

Option 1 remains the right answer eventually, under conditions
`AGENT_TOOLS.md` §5 already wrote down: several integrations needed at
once, or per-user OAuth becoming a requirement. Neither is true today,
and adopting a broker now would leave Arc's own blockers in place while
adding a trust boundary.

Between Options 3 and 4, the separate protocol is chosen because the
credential separation is the decision's substance. Two methods on one
protocol with one credential parameter is an invitation to pass the read
token; two protocols, two credential scopes and a service that resolves
`ACT` explicitly make the safe thing the default thing.

## Consequences

### Positive

- Arc can take a real, audited, human-approved action on the outside
  world, and `AGENT_TOOLS.md` §3 no longer reads "nothing".
- The approval gate, the capability ceiling and the RBAC matrix all gain
  a use where the stakes are real rather than simulated.
- The destination of any action is tenant-administered configuration, so
  a prompt injection that reaches the proposal path still cannot choose
  where Arc speaks.
- Read and act credentials are separable, so a tenant can grant Arc
  read-only access and keep it that way — and revoking the act
  credential does not break connector sync.

### Negative

- One provider, one action. This is a foundation, not a feature set.
- Uniqueness on `connector_credentials` changed. The statements are
  idempotent, but they do run `DROP CONSTRAINT` on an existing database.
- An action that fails after its approval is consumed costs the requester
  a re-request.
- `ToolDefinition` now has two handler shapes, which is one more thing a
  contributor adding a tool has to understand.

### Risks

- **A future action tool added without a gate.** Mitigated at
  construction: an `action_handler` with anything other than HIGH risk
  raises, and a catalogue-wide test asserts every action tool carries
  `REQUIRE_HUMAN_APPROVAL` and `connector:act`.
- **The destination check being weakened for convenience** — for example
  to let a caller post to any channel the token can see. Mitigated by
  matching the connector in SQL inside the boundary, and by tests that
  assert an unconfigured and an inactive destination are both refused.
- **The act credential being made to fall back to the read credential**
  when unset, which would look like a helpful default. Mitigated by a
  test asserting a tenant with only a read credential cannot act.
- **An action handler growing its own HTTP client.** Mitigated by the
  existing source-level guard, extended to action handlers, plus a test
  that an action handler's only outward reference is
  `invocation.external_actions`.

## Security Considerations

- **Authentication / tenant isolation** unchanged. The action runs inside
  an established `TenantContext`; the destination lookup and the
  credential lookup are both tenant-scoped in SQL, and the handler
  receives the context type rather than a bare tenant string.
- **Authorization** widened by exactly one permission, `connector:act`,
  granted to `PLATFORM_ADMINISTRATOR`, `COMPANY_ADMINISTRATOR` and
  `OPERATIONS_USER`. `EMPLOYEE` and `WEBHOOK_PROCESSOR` do not hold it,
  so neither an employee via Agent nor a webhook-triggered execution can
  post.
- **Secrets.** The act credential is encrypted at rest with the same
  AES-256-GCM service and key versioning as the read credential,
  decrypted narrowly for one call, and never logged, returned, or
  included in an audit summary. The adapter receives a token; the tool
  handler never sees one.
- **SSRF.** No tenant input selects a destination host. The endpoint is a
  module constant, re-checked against the provider allowlist on every
  request, and the channel is a validated name resolved through the
  provider's own API.
- **Untrusted model output.** A proposal is a request. It is parsed,
  validated against the tool's schema, authorized, and then gated by a
  human approval bound to a digest of the validated arguments. A model
  cannot reach a destination nobody configured, cannot change an approved
  message, and cannot spend an approval twice.
- **Audit.** Every attempt — denied, gated, failed or executed — writes a
  `tool_execution_records` row with summaries only. A successful action
  records the provider's own reference, so the trail points at the real
  artifact rather than at Arc's claim that it created one.
- **Fail closed everywhere.** Missing capability, missing permission,
  missing approval, unconfigured destination, missing act credential,
  unwired boundary and any provider error all refuse, and none of them
  posts.

## Operational Considerations

- Schema: `scope` on `connector_credentials` and on
  `connector_credential_audit`, plus a wider unique index. Applied
  through the existing idempotent `schema.sql` pattern; safe on fresh and
  existing databases.
- Configuration: external actions require `CONNECTOR_ENCRYPTION_KEY`,
  because there is otherwise nowhere to keep an act credential. Without
  it the service is simply not wired and the tool fails closed with a
  named error kind.
- A latent bootstrap bug was fixed in passing: `schema.sql` is applied by
  splitting on `;`, and a semicolon inside a `--` comment produced a
  comment-only fragment that raised inside asyncpg — a failure that would
  have broken application STARTUP, far from its cause. The splitter is
  now shared between startup and the test bootstrap and skips fragments
  carrying no SQL.
- Monitoring: `external_action_performed` and `external_action_failed` are
  logged with tenant, provider, connector and error kind — never message
  content.
- Cost: one additional provider API call per action (channel resolution),
  the same one `fetch` already makes.

## Testing / Validation

- The whole chain end to end against real PostgreSQL, twice: at the
  service boundary, and over HTTP through the application's own wiring
  including the "Run it now" resume that sends no arguments. The only
  fake is the network.
- Every refusal test asserts the provider recorded **nothing**. For an
  action tool the side effect is the deliverable, so a test that checked
  only the returned error would not notice a message that was posted
  anyway.
- Specific invariants: the attempt alone posts nothing; approval alone
  posts nothing; a modified message or a changed channel after approval
  is refused; a second resume cannot post twice; a caller holding
  `tool:execute` but not `connector:act` is denied; an unconfigured or
  inactive destination is refused; another tenant's connector is not a
  destination; a tenant with only a read credential cannot act; the
  capability is checked before anything is decrypted; provider failures
  map to safe error kinds; an over-long message is refused rather than
  truncated.
- Each of the three enforcement points was verified load-bearing by
  removing it and confirming the relevant tests fail.

## Related Documents

- `docs/capabilities/AGENT_TOOLS.md` — §3 the finding, §4 the dependency
  order, §5 the build-vs-integrate decision this implements
- ADR-002 — connector provider selection (the four providers)
- ADR-004 — tool-calling execution contract (the LLM is untrusted)
- ADR-005 — Human Intervention approval gate (binding, single use)
- V2-ADR-015 — connector credential encryption at rest

## Related Work

- Linear:
- GitHub: #304

## Supersedes

## Superseded By
