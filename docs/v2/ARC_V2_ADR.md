# ARC V2 — ARCHITECTURE DECISION RECORDS (ADR)

**Status:** Proposed Final / Governing V2 Decisions  
**Version:** 2.0  
**Date:** 2026-09-10

This document consolidates the V2 architectural decisions resulting from the reconciled Bala/Bharath audits and the product direction agreed for Arc.

When this ADR conflicts with an older draft ADR, this V2 ADR is authoritative for V2 implementation.

---

# ADR-001 — Modular Monolith

**Status:** Accepted

## Context

Arc contains many cooperating domains but does not currently require independent deployment or independent scaling boundaries.

## Decision

Keep Arc as a modular monolith.

Use explicit domain/service boundaries inside one application.

## Consequences

Positive:

- simpler development
- simpler local deployment
- easier transactions
- easier end-to-end testing
- fewer operational dependencies

Negative:

- module boundaries must be enforced by code discipline
- future extraction may require explicit interfaces

Microservices are not a V2 requirement.

---

# ADR-002 — Tenant Isolation Through Trusted TenantContext

**Status:** Accepted

## Decision

TenantContext remains the authoritative tenant boundary.

Tenant-scoped routes must verify path tenant IDs against trusted TenantContext.

Tenant identity must never be accepted solely from arbitrary request payloads.

Cross-tenant access fails closed.

## Consequences

All domain services receiving tenant-scoped data must either receive TenantContext or an equivalent trusted tenant identity.

---

# ADR-003 — Platform Admin Is a Separate Control Plane

**Status:** Accepted

## Decision

`/platform/*` is the single Platform Administrator surface.

Platform Admin can operate the Arc platform without automatically receiving unrestricted tenant business-data access.

Platform administration and tenant workspace administration remain distinct.

## Consequences

Platform Admin product screens should expose administrative metadata and control-plane functions.

Tenant data access requires its own explicit authorization model.

---

# ADR-004 — Capability, Entitlement, Tenant Configuration, RBAC

**Status:** Accepted

## Decision

Use this hierarchy:

```text
Platform Capability
        ↓
Commercial Entitlement
        ↓
Tenant Configuration
        ↓
Tenant RBAC
```

A disabled platform capability is unavailable to all tenants.

A globally enabled capability does not imply that every tenant is entitled to or configured to use it.

Pricing is attached to entitlements/plans/usage, not UI switches.

## Consequences

The capability registry should not be implemented as a replacement for working feature domains.

Capability controls are applied after the underlying feature works.

Billing implementation is outside the current V2 scope.

---

# ADR-005 — Employee Execution Model

**Status:** Accepted

## Context

Bala recommended keeping Employee execution behind Agent/Unified Intelligence.

Bharath identified that SkillExecutionService and ToolExecutionService independently enforce execution permissions.

Giving Employee no execution permissions would make permitted low-risk workflows impossible through the current service contracts.

## Decision

Employee receives:

```text
knowledge:read
agent:execute
skill:execute
tool:execute
```

but employee execution is constrained by deterministic execution policy.

The preferred product path is:

```text
Employee
 ↓
Unified Intelligence / Agent
 ↓
Skill
 ↓
Tool
```

Direct skill/tool calls remain subject to principal-aware policy and cannot execute high-risk operations without approval.

## Consequences

This preserves:

- Bala's bounded AI workflow model
- Bharath's lower-layer authorization requirements

while avoiding an authorization bypass.

No employee receives approval-decision authority merely from these permissions.

---

# ADR-006 — Production LLM Provider

**Status:** Accepted

## Decision

Use:

```text
Arc
 ↓
OmniRoute
 ↓
OpenRouter
 ↓
Configured model
```

The existing provider protocols remain the domain abstraction.

## Requirements

- provider configurable
- model configurable
- usage tracked
- latency tracked
- timeouts
- bounded retry
- structured output validation
- provider-specific failures mapped to stable application errors

## Consequences

OpenRouter is the initial production provider without coupling Arc's domain layer to OpenRouter.

---

# ADR-007 — Hybrid Retrieval Without Reranking

**Status:** Accepted

## Decision

V2 retrieval uses:

```text
Dense retrieval
+
Lexical retrieval
↓
RRF fusion
↓
ApprovedContext
```

Do not introduce reranking into the V2 critical path.

Do not create `HybridRetrievalService`.

Extend `RetrievalService`.

## Rationale

The reconciled architecture and existing ADR direction do not require reranking for V2.

Avoid additional model latency, infrastructure, dependency, and evaluation burden until retrieval evaluation demonstrates that RRF is insufficient.

---

# ADR-008 — ApprovedContext as the LLM Boundary

**Status:** Accepted

## Decision

Production LLM generation receives only ApprovedContext or explicitly approved application data.

Raw database queries or arbitrary tenant records must never be passed directly to the model.

## Consequences

Retrieval, sanitization, provenance, and tenant validation happen before generation.

No-match conditions produce no fabricated grounded answer.

---

# ADR-009 — AI Proposal Is Not Authorization

**Status:** Accepted

## Decision

LLM output is an untrusted proposal.

Application services make all final decisions about:

- authorization
- tenant scope
- tool availability
- input validity
- risk
- human approval
- execution

## Consequences

Prompt injection cannot directly grant permissions.

Tool arguments from the model are treated as untrusted input.

---

# ADR-010 — ToolExecutionService Is the Execution Boundary

**Status:** Accepted

## Decision

All tool execution passes through ToolExecutionService.

Required sequence:

```text
authorization
→ declared permissions
→ policy
→ validation
→ execution
→ audit
```

No Agent, Skill, webhook, controller, or background job may directly invoke tool handlers as a shortcut.

---

# ADR-011 — Separate Skill Approval and Tool Human Approval

**Status:** Accepted

## Decision

There are two gates:

### Skill-level gate

`skill.approval_required`

Stops skill execution.

Does not itself create the tool approval request.

### Tool-level gate

`REQUIRE_HUMAN_APPROVAL`

Creates a human approval request.

The Agent propagates the approval-required result but does not own approval creation.

## Consequences

The two concepts must not be merged in future implementation.

---

# ADR-012 — Approval Is Not Authorization

**Status:** Accepted

## Decision

Approval consumption revalidates:

- tenant
- tool
- version
- arguments digest
- current authorization
- current policy
- input schema

Approval permits continuation past the human gate. It does not replace authorization.

---

# ADR-013 — Agent Remains Bounded

**Status:** Accepted

## Decision

Agent maximum steps remain bounded at 3.

Agent must:

- parse structured decisions
- fail closed on malformed output
- execute through SkillExecutionService
- use ToolExecutionService
- propagate TenantContext
- persist execution traces
- stop on failure
- stop at maximum steps

Long-term memory is deferred.

---

# ADR-014 — Reuse Existing Agent Run Persistence

**Status:** Accepted

## Decision

Reuse existing:

```text
agent_run_records
```

Do not create a second agent-run table.

Add:

```text
skill_execution_records
```

to complete the execution hierarchy:

```text
Agent
 ↓
agent_run_records
 ↓
Skill
 ↓
skill_execution_records
 ↓
Tool
 ↓
tool_execution_records
```

---

# ADR-015 — Tenant-Isolated Connector Credentials

**Status:** Accepted

## Context

The connector service is tenant-scoped, but a shared global connector credential configuration is insufficient for production multi-tenancy.

## Decision

Credentials are stored per tenant and encrypted at rest.

```text
Tenant
 ↓
ConnectorCredential
 ↓
EncryptionService
 ↓
Provider
```

Requirements:

- tenant isolation
- encrypted storage
- no secret in normal responses
- no secret in logs
- rotation strategy
- credential audit

This decision must be implemented before production connector use.

---

# ADR-016 — Existing Connector Adapter Architecture Is Retained

**Status:** Accepted

## Decision

Keep the existing adapter architecture for GitHub, Slack, and Linear.

Simulated providers remain supported for development/testing.

Live adapters remain available for production configuration.

Do not replace the architecture merely because the default local mode is simulated.

---

# ADR-017 — Webhook Processing Does Not Route Through Agent in V2

**Status:** Accepted

## Decision

Webhook events route to the configured Skill:

```text
Webhook
 ↓
SkillExecutionService
 ↓
ToolExecutionService
```

Do not introduce Agent routing into the webhook pipeline for V2.

## Rationale

The deterministic webhook → skill path is simpler, more predictable, and already aligned with the execution architecture.

Agent routing may be evaluated later.

---

# ADR-018 — Webhook Configuration Supports DB + Environment

**Status:** Accepted

## Decision

Support both:

```text
DB configuration
ENV fallback
```

DB configuration takes precedence.

## Consequences

Existing deployments do not need immediate migration.

Platform/tenant administration can eventually manage webhook configuration at runtime.

---

# ADR-019 — Webhook Reliability Is First-Class

**Status:** Accepted

## Decision

Webhook processing includes:

- event persistence
- idempotency
- replay protection
- bounded retries
- exponential backoff
- processing states
- terminal failure/dead-letter state

Only transient failures are retryable.

State-changing actions require idempotency guarantees before retry.

---

# ADR-020 — Reranking Is Deferred

**Status:** Accepted

## Decision

No reranking model is required for V2.

Reranking can be reconsidered when:

- RRF evaluation shows material retrieval-quality limitations
- latency budget permits it
- operational cost is justified
- an evaluation dataset demonstrates measurable benefit

---

# ADR-021 — No Dedicated Incident Entity for V2

**Status:** Accepted

## Decision

Do not add an `incidents` table solely because incident concepts appear in product documentation.

Current observability derives operational information from authoritative records including:

- tool execution
- approvals
- webhook processing
- connector state
- API errors
- agent/skill traces

A first-class incident entity requires a separate product requirement.

---

# ADR-022 — Pagination Is Standard

**Status:** Accepted

## Decision

Production list APIs use pagination.

Small local datasets do not justify returning unlimited collections.

Use offset/page pagination initially unless a specific endpoint requires cursor pagination.

---

# ADR-023 — AI Evaluation Is a Release Requirement

**Status:** Accepted

## Decision

Production AI features require regression evaluation.

At minimum:

### RAG

- retrieval relevance
- no-match correctness
- citation correctness
- tenant isolation
- groundedness

### LLM

- structured output validity
- failure handling
- instruction adherence

### Tools

- correct tool selection
- invalid argument rejection
- policy enforcement

### Agent

- step bounds
- correct skill selection
- authorization preservation
- approval behavior
- termination

### Security

- prompt injection
- data exfiltration attempts
- cross-tenant retrieval
- unauthorized execution

No AI feature is considered production-ready solely because unit tests pass.

---

# ADR-024 — AI Observability Includes Usage and Cost Signals

**Status:** Accepted

## Decision

Track model/provider usage where available:

- input tokens
- output tokens
- total tokens
- model
- provider
- latency
- tenant
- workflow/run correlation

Avoid storing raw prompts/responses by default.

Cost is calculated from provider/model pricing configuration rather than hardcoded into domain logic.

---

# ADR-025 — PII Guard Is a Cross-Domain Boundary

**Status:** Accepted

## Decision

PII protection applies beyond initial knowledge ingestion.

Review and enforce the boundary for:

- connectors
- webhooks
- tools
- skill outputs
- Agent traces
- observability
- LLM context

No domain may silently create a new path around PII controls.

---

# ADR-026 — No Unnecessary Enterprise Infrastructure

**Status:** Accepted

## Decision

V2 will not introduce:

- microservices
- Kubernetes
- Kafka
- service mesh
- distributed workflow engines
- separate vector databases
- complex caching systems

unless a measured product or operational requirement appears.

The architecture must remain understandable by the team.

---

# ADR-027 — V2 PR Discipline

**Status:** Accepted

Every implementation change follows:

```text
feature branch
 ↓
tests
 ↓
commit
 ↓
push branch
 ↓
PR
 ↓
review
 ↓
merge
```

Never push directly to `main`.

PRs must be narrowly scoped.

Do not combine unrelated refactors with V2 feature work.

---

# ADR-028 — V2 Definition of Production-Ready

**Status:** Accepted

A feature is production-ready only when:

1. its end-to-end workflow works;
2. tenant isolation is verified;
3. authorization is verified;
4. failures are controlled;
5. observability exists;
6. AI features have evaluation coverage;
7. secrets are handled correctly;
8. data boundaries are preserved;
9. tests pass;
10. documentation matches behavior.

---

# FINAL DECISION HIERARCHY

When documents disagree:

```text
V2 ADR
  ↓
V2 TRD
  ↓
V2 PRD
  ↓
Current implementation
```

The current implementation is evidence of what exists, not permission to preserve a broken behavior.

If a new repository fact contradicts these documents, stop the affected implementation and create/update an ADR before silently changing architecture.

---

# V2 ARCHITECTURE NORTH STAR

```text
                         ARC PLATFORM
                              │
              ┌───────────────┴────────────────┐
              │                                │
       PLATFORM CONTROL PLANE             TENANT WORKSPACE
              │                                │
      Tenants / Users /                 Knowledge / Connectors
      Capabilities /                    Intelligence / Skills
      Observability                     Tools / Agent
              │                                │
              └───────────────┬────────────────┘
                              │
                       TRUST BOUNDARIES
                              │
                  Auth → TenantContext → RBAC
                              │
                       PII / Policy
                              │
                         AI LAYER
                              │
            ┌─────────────────┼──────────────────┐
            │                 │                  │
          RAG              LLM              Agent
            │                 │                  │
       Dense + Lexical   OmniRoute →       bounded steps
            │             OpenRouter            │
            ↓                 │                 ↓
           RRF                │              Skills
            ↓                 │                 ↓
     ApprovedContext          │              Tools
            └─────────────────┴─────────────────┘
                              │
                    Human Approval when needed
                              │
                       Execution + Audit
                              │
                       Observability
                              │
                    PostgreSQL + pgvector
```

**This is the governing V2 architecture.**
