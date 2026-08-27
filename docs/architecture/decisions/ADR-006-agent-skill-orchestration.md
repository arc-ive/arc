# ADR-006: Bounded Agent Skill Orchestration

## Status

Draft / Proposed

## Context

PRD 14 defines Unified Intelligence as the combined Company Brain + Agent
system; the Agent capability provides reasoning, Skill selection,
execution, failure handling, and escalation (TRD 8.3). ADR-004 delivered
the first bounded tool-calling iteration inside Unified Intelligence and
explicitly deferred Skill selection and agent loops until the Skills
Engine could execute Skills.

That dependency now exists: the Skills Engine MVP provides
`SkillExecutionService` (tenant-scoped resolution, `Skill.allowed_tools`
gating, delegation to `ToolExecutionService`, structured
`SkillExecutionResult`), with `agent`-visible failure semantics already
fail-closed (approval-gated Skills stop execution).

## Decision

1. **Separate orchestration service.** The Agent is a new
   `AgentExecutionService` (`arc.services.agent`) that sits strictly
   ABOVE `SkillExecutionService`. It is a sibling of the Intelligence
   service under the Unified Intelligence umbrella — not an extension of
   `UnifiedIntelligenceService.answer_query`, whose ADR-004 V1 contract
   (single tool-calling iteration, additive response field) remains
   unchanged.
2. **Bounded execution.** At most `MAX_AGENT_STEPS = 3` delegated Skill
   executions per run. Every controlled engine outcome is terminal:
   failures stop immediately with no retries; `APPROVAL_REQUIRED`
   propagates verbatim as an escalation state for the future Human
   Intervention capability; a provider decline ends the run; reaching
   the bound fails closed (`max_steps_reached`). There is no autonomous
   looping.
3. **Dedicated permission.** `agent:execute` authorizes the Agent API.
   It is intentionally distinct from `skill:execute`: it authorizes
   orchestration only. The Agent can do nothing beyond what Skill
   execution permits, so it never grants direct tool access and never
   bypasses `Skill.allowed_tools` or per-tool RBAC. Granted to
   PLATFORM_ADMINISTRATOR, COMPANY_ADMINISTRATOR, OPERATIONS_USER;
   EMPLOYEE has none.
4. **Fail-closed decision parsing.** Model output is untrusted data:
   `AgentDecision.parse` accepts exactly
   `{skill_id, tool_calls, satisfied_preconditions}` and rejects every
   deviation without coercion (mirroring `ToolProposal.parse`). The
   selected `skill_id` must exist in the trusted tenant's own catalog
   snapshot; deep request validation stays owned by
   `SkillExecutionService` (single validation authority).
5. **Decision seam.** A new optional `SkillSelectingLlm` protocol
   (`propose_skill(goal, catalog_snapshot)`) mirrors ADR-004's
   `ToolProposingLlm`. The deterministic provider gains an optional test
   script; unarmed — the production default — the Agent fails closed
   with `agent_capability_unavailable`.
6. **No second audit path, no new persistence.** Tool-level audit rows
   remain owned exclusively by `ToolExecutionService`
   (`tool_execution_records`). Durable agent-run records and Agent
   observability are deferred (consistent with the Skills slice).
7. **Tenant isolation unchanged.** Identity and tenant come only from
   the trusted X-10 `TenantContext`; model output never sees tenant
   identifiers and can never override the boundary.

## Consequences

- The end-to-end chain is now: authenticated request → Agent decision →
  `SkillExecutionService` → `ToolExecutionService` → platform handler →
  audit, with every layer independently tested.
- Agent behavior is deterministic under the scripted provider and safely
  inert under the default configuration.
- Multi-step autonomy remains structurally capped; widening the bound or
  adding planning/memory requires a future ADR amendment plus Human
  Intervention controls.

## Alternatives considered

- **Extend `UnifiedIntelligenceService`** — rejected: would entangle the
  reviewed ADR-004 single-iteration contract with loop orchestration and
  change its response schema semantics.
- **Reuse `skill:execute` for the Agent** — rejected: direct Skill
  execution and higher-level autonomous-style orchestration are distinct
  capabilities; separate permissions keep blast radius explicit.
- **Full autonomous agent loop now** — rejected (consistent with
  ADR-004 §6): unbounded iteration multiplies risk before bounded
  orchestration is proven.

## Scope exclusions

Human Intervention workflow (next phase) · durable agent-run records ·
production LLM providers · connector/webhook-triggered runs · memory or
planning state.
