# ARC V2 — PRODUCT REQUIREMENTS DOCUMENT (PRD)

**Status:** Proposed Final / Governing V2 Baseline  
**Version:** 2.0  
**Date:** 2026-09-10  
**Product:** Arc Enterprise AI Platform  
**Architecture:** Modular monolith, Docker-first  
**Primary stack:** FastAPI/Python, PostgreSQL + pgvector, React  
**Audience:** Joe, Bala, Bharath, all Arc contributors and coding agents

---

## 1. Purpose

Arc V2 is the production-oriented evolution of Arc from a collection of implemented subsystems into a coherent enterprise AI platform.

The V2 objective is not to add features for the sake of feature count. The objective is to make the important AI workflows work end-to-end, securely, observably, and predictably.

V2 must preserve the strong existing foundations around:

- multi-tenancy
- trusted TenantContext
- fail-closed authorization
- PII boundaries
- ApprovedContext
- ToolExecutionService
- bounded Agent execution
- human approval controls
- webhook authentication
- PostgreSQL/pgvector

The current implementation already contains many of these foundations; V2 completes and connects them.

## 2. Product Definition

Arc provides organizations with a secure AI workspace that can:

1. ingest and maintain company knowledge;
2. retrieve approved company knowledge;
3. answer questions using enterprise context;
4. connect external systems to the Company Brain;
5. execute approved workflows through Skills and Tools;
6. use bounded AI Agents to orchestrate those workflows;
7. require humans for risky actions;
8. process authenticated inbound events;
9. provide tenant and platform operational visibility.

Arc is a multi-tenant SaaS platform. Customer data is tenant-scoped. Platform administration is a separate control-plane concern.

## 3. V2 Product Principles

### P1 — End-to-end over isolated features

A feature is not considered complete merely because its UI, API, or service exists.

A production feature must have a valid end-to-end path.

### P2 — AI paths receive production-grade engineering

AI domains receive stronger requirements for:

- security
- evaluation
- deterministic contracts
- failure handling
- observability
- cost/usage tracking
- model/provider abstraction
- retrieval quality
- execution safety
- regression testing

### P3 — Non-AI infrastructure is well engineered, not over-engineered

Use the simplest architecture that provides:

- correctness
- security
- maintainability
- testability
- reliable operation

Do not introduce microservices, distributed orchestration, complex event infrastructure, or other enterprise machinery without a demonstrated requirement.

### P4 — Fail closed

Uncertainty must not result in unauthorized access, fabricated answers, unsafe execution, or cross-tenant data exposure.

### P5 — Security boundaries are preserved

No V2 feature may bypass:

- TenantContext
- RBAC
- ToolExecutionService
- PII controls
- ApprovedContext
- approval policy

### P6 — Evidence before expansion

New capabilities are added only after the existing workflow is operational enough to justify them.

## 4. Users and Roles

Arc V2 supports:

### Platform Administrator

Global Arc operator.

Can manage platform-level tenants, users, platform configuration, capabilities/availability, and platform observability.

Platform administration does not automatically grant unrestricted access to tenant business data.

### Company Administrator

Tenant administrator.

Manages the organization's users, knowledge, connectors, skills, and tenant configuration subject to platform-level availability and entitlements.

### Operations User

Tenant operational role.

Monitors tenant operations and handles operational workflows permitted by policy.

### Employee

Normal business user.

Can search approved company knowledge and initiate permitted low-risk AI workflows.

Employee access must be mediated by tenant RBAC and AI execution policy. High-risk actions require the same approval controls as every other principal.

### Viewer

Read-oriented role where applicable.

## 5. Tenant Model

Tenant isolation is mandatory.

Every tenant-scoped request must derive a trusted TenantContext and verify the requested tenant against it.

Cross-tenant requests must fail closed and should not disclose whether another tenant's resource exists.

Tenant ownership must be present on tenant-scoped:

- knowledge
- chunks
- connectors
- skills
- tools/execution records
- approvals
- webhook events
- observability data
- agent runs
- skill executions

## 6. Platform Control Plane

The `/platform/*` surface is the single Platform Administrator control plane.

V2 should improve the existing platform surface rather than introduce a second admin surface.

Platform Admin responsibilities:

- tenant lifecycle administration
- global user directory
- platform-level operational visibility
- global availability of Arc capabilities
- platform configuration
- entitlement administration where implemented
- audit/administrative visibility

Platform Admin should not become the everyday administrator of every customer's private workspace.

### Capability and entitlement model

V2 establishes this conceptual hierarchy:

Platform capability
→ commercial entitlement
→ tenant configuration
→ tenant RBAC

A global capability disable is a hard ceiling.

A globally enabled capability is not automatically enabled for every tenant.

Tenant configuration determines whether an entitled tenant uses the capability.

Pricing is not determined by arbitrary UI toggles. Pricing attaches to plans, entitlements, and/or measured usage.

The detailed commercial billing system is outside V2 unless separately approved.

## 7. Company Brain

Company Brain is the authoritative tenant knowledge layer.

Supported ingestion sources include:

- direct knowledge documents
- connector-sourced content
- future authenticated ingestion sources

Requirements:

- tenant isolation
- deterministic document identity
- idempotent ingestion
- PII inspection before persistence/embedding where applicable
- atomic document/chunk persistence
- source metadata
- provenance
- update/delete semantics
- ingestion status
- clear failure states

A document must not become searchable until its searchable representation is valid.

## 8. Secure RAG V2

RAG is a core production AI capability.

### Required architecture

```text
Query
  ↓
TenantContext + RBAC
  ↓
Query normalization
  ↓
Dense retrieval
  +
Lexical retrieval
  ↓
RRF fusion
  ↓
Policy / tenant validation
  ↓
ApprovedContext
  ↓
LLM
  ↓
Answer + citations
```

V2 uses:

- semantic/dense retrieval
- lexical retrieval
- Reciprocal Rank Fusion (RRF)
- ApprovedContext as the controlled LLM boundary

Reranking is explicitly deferred from the V2 critical path.

### RAG security requirements

- tenant filter at retrieval
- defensive tenant validation on returned results
- no raw arbitrary database content to the LLM
- only ApprovedContext reaches generation
- empty retrieval must not cause fabricated answers
- prompt injection from retrieved content must be treated as untrusted data
- citations must map to authoritative source records
- retrieval failures fail closed rather than silently generating unsupported answers

### RAG quality requirements

V2 must include an evaluation/regression set covering:

- relevant retrieval
- irrelevant retrieval
- no-match behavior
- tenant isolation
- citation correctness
- lexical-only matches
- semantic-only matches
- hybrid ranking behavior
- adversarial/untrusted content

## 9. PII and AI Data Boundary

PII protection is an AI security boundary, not merely an ingestion feature.

PII controls must cover, as applicable:

- knowledge ingestion
- connector sync
- skill creation
- webhook payload processing
- tool inputs/results where persisted
- observability metadata
- LLM context construction

The production LLM must not receive unsanitized tenant content outside the approved data contract.

## 10. LLM Layer

Arc V2 introduces a production LLM provider behind the existing provider abstractions.

Target architecture:

```text
Arc AI services
      ↓
OmniRoute
      ↓
OpenRouter
      ↓
Configured model
```

The provider layer must remain replaceable.

Requirements:

- provider abstraction
- model configuration
- request timeout
- bounded retries where safe
- structured output validation
- failure classification
- usage/token capture
- latency capture
- correlation IDs
- no provider-specific logic leaking into domain services
- no partial answer on provider failure
- safe handling of malformed model output

Model selection must be configuration-driven, not hardcoded throughout application logic.

## 11. Unified Intelligence

Unified Intelligence is the primary conversational AI boundary.

It may use:

- Company Brain / RAG
- Skills
- Tools
- Agent orchestration where appropriate

Every AI action must remain subject to authorization, tenant scope, PII policy, and execution policy.

The system must distinguish:

- knowledge answer
- proposed action
- executed action
- approval-required action
- denied action
- failed action

The model may propose; deterministic application services decide whether execution is permitted.

## 12. Skills

Skills represent reusable business procedures.

V2 requirements:

- tenant scope
- explicit risk classification
- versioning
- allowed tools
- input validation
- bounded tool calls
- authorization
- approval policy
- persisted execution history
- deterministic failure states

Skill execution must continue to use SkillExecutionService.

A Skill cannot directly bypass ToolExecutionService.

## 13. Tools

Tools are platform-owned executable capabilities.

Each tool must define:

- stable name
- description
- input schema
- required permissions
- risk/policy classification
- handler
- timeout/failure semantics
- audit behavior

All tool execution must pass through ToolExecutionService.

Tool policy states include:

- ALLOW
- REQUIRE_HUMAN_APPROVAL
- DENY

Authorization and human approval are separate controls.

Approval never substitutes for authorization.

## 14. AI Agent

The Agent is a bounded orchestrator.

V2 Agent requirements:

- bounded maximum steps
- bounded execution time
- explicit decision schema
- fail-closed model output parsing
- SkillExecutionService as execution boundary
- ToolExecutionService for actual tools
- tenant context propagation
- authorization at every execution boundary
- execution persistence
- step-level traceability
- retry only where operation semantics permit it
- no unrestricted tool registry
- no autonomous security-policy override

Agent memory is not a V2 requirement unless a concrete product workflow requires it.

### Agent flow

```text
User
 ↓
Agent authorization
 ↓
Agent decision
 ↓
Skill
 ↓
Tool authorization + policy
 ↓
Approval if required
 ↓
Tool execution
 ↓
Persist step/result
 ↓
Bounded next step
 ↓
Final result
```

## 15. Human Intervention

Human approval is part of the execution lifecycle.

Required states:

```text
pending
approved
rejected
expired
consumed
```

Approval must bind to:

- tenant
- requested tool
- tool/version
- arguments digest
- requesting principal
- relevant policy context

Approval consumption must revalidate authorization and execution preconditions.

An approval is not an authorization bypass.

Skill-level `approval_required` and tool-level `REQUIRE_HUMAN_APPROVAL` remain separate concepts:

- Skill-level gate stops skill execution.
- Tool-level gate creates the approval request.

## 16. Connectors

V2 retains the existing provider adapter architecture.

Initial providers:

- GitHub
- Slack
- Linear

Simulated providers remain useful for development/test environments.

Live adapters must be usable through production configuration.

Primary V2 improvement:

**tenant-isolated credential management.**

Credentials must not rely on one shared global credential set for all tenants.

V2 credential requirements:

- encrypted at rest
- tenant scoped
- access only through connector service
- never returned through normal APIs
- rotation support
- key configuration/rotation strategy
- audit events for credential changes

Google Drive is deferred unless explicitly promoted.

## 17. Webhooks

V2 supports authenticated inbound webhook processing.

Pipeline:

```text
Request
 ↓
HMAC verification
 ↓
Replay/idempotency validation
 ↓
Persist event
 ↓
Tenant resolution
 ↓
Configured skill
 ↓
SkillExecutionService
 ↓
ToolExecutionService
```

Webhook processing does not need Agent routing in V2.

Requirements:

- authenticated endpoint
- tenant binding from trusted endpoint configuration
- replay resistance
- idempotency
- processing state
- bounded retries
- exponential backoff
- dead-letter/final-failure state
- operational visibility
- safe duplicate handling

Configuration supports:

- environment configuration for compatibility
- DB-backed configuration for runtime management

Precedence:

DB configuration → environment configuration fallback.

## 18. Observability

Observability must answer:

- what happened?
- when?
- for which tenant?
- which principal initiated it?
- which AI/model/provider was involved?
- what was retrieved?
- what was executed?
- was approval required?
- did it succeed?
- how much did it cost?
- how long did it take?

AI observability must include, where safe:

- request correlation
- agent run
- skill execution
- tool execution
- retrieval metrics
- model/provider
- token usage
- latency
- errors
- approval transitions

Raw tenant content must not be used as a general observability store.

A dedicated incidents table is not mandatory unless product requirements later establish incidents as a first-class persistent entity.

## 19. API and Platform Reliability

Non-AI APIs should follow normal production engineering:

- pagination for list endpoints
- consistent validation
- stable error contracts
- authentication and authorization
- tenant consistency checks
- bounded request sizes
- timeouts
- idempotency where appropriate
- structured logs
- API documentation
- health checks

No microservice split is required.

## 20. Database

PostgreSQL + pgvector remains the primary data store.

V2 database requirements:

- explicit tenant ownership
- foreign keys
- appropriate indexes
- unique constraints for idempotency
- migration discipline
- append-only audit semantics where appropriate
- safe deletion semantics
- no unnecessary schema duplication

V2 adds:

- `skill_execution_records`

Existing:

- `agent_run_records`
- `tool_execution_records`

must be reused.

## 21. Security Requirements

Mandatory:

- fail-closed authorization
- trusted TenantContext
- cross-tenant isolation
- secure authentication/session handling
- CSRF protections where applicable
- HMAC webhook validation
- replay protection
- encrypted connector credentials
- PII boundary enforcement
- ApprovedContext LLM boundary
- tool allowlisting
- schema validation
- approval revalidation
- no secrets in seed/reference data
- auditability of privileged operations

## 22. Testing Strategy

V2 testing is layered.

### Unit

Domain/service behavior.

### Integration

Database, authorization, retrieval, provider adapters, execution services.

### Security

Tenant isolation, RBAC, PII, prompt/data boundaries, approval bypass attempts, webhook forgery/replay.

### AI evaluation

Golden datasets and regression tests for:

- retrieval quality
- answer grounding
- citations
- tool selection
- structured model output
- refusal/fail-closed behavior
- prompt injection resistance
- agent boundedness

### End-to-end

Representative workflows must run from user action to final outcome.

Minimum critical E2E flows:

1. document → PII → chunk → embedding → RAG → grounded answer
2. connector → sync → PII → Company Brain → RAG
3. employee → AI → low-risk Skill → Tool
4. AI → high-risk Tool → approval → consumption → execution
5. Agent → Skill → Tool → persisted trace
6. webhook → authenticated event → Skill → Tool
7. tenant A attempting tenant B access → denied

## 23. Definition of Done

A V2 capability is done only when:

- product behavior is defined
- backend behavior is implemented
- authorization is enforced
- tenant isolation is tested
- failure behavior is defined
- observability exists where appropriate
- tests exist
- E2E path works where applicable
- documentation is updated
- no hidden dependency on another unfinished feature exists

## 24. V2 Non-Goals

Do not expand V2 with:

- microservices
- Kubernetes
- RLS solely for architectural fashion
- unnecessary distributed queues
- agent memory without a product requirement
- reranking in the critical RAG path
- Google Drive without explicit prioritization
- billing/Stripe unless separately approved
- dedicated incident entities without a concrete requirement
- speculative enterprise features

## 25. V2 Success Criteria

Arc V2 is successful when the platform can demonstrate:

1. secure multi-tenant operation;
2. reliable Company Brain ingestion;
3. production-grade hybrid RAG with grounded answers;
4. production LLM integration;
5. usable low-risk employee AI workflows;
6. safe AI tool execution;
7. bounded Agent orchestration;
8. complete human approval lifecycle;
9. reliable authenticated webhook execution;
10. tenant-isolated connector credentials;
11. meaningful AI observability and usage tracking;
12. repeatable E2E and AI evaluation coverage.

---

# FINAL PRODUCT RULE

**Arc V2 is not a feature checklist. It is a set of working, connected, secure workflows.**

AI domains must meet production-grade standards.

Non-AI domains must be correct, secure, maintainable, and appropriately engineered without unnecessary complexity.

This PRD governs product scope. The TDR governs implementation architecture. ADRs govern binding architectural decisions.
