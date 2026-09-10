# ARC V2 — TECHNICAL REQUIREMENTS & DESIGN (TRD)

**Status:** Proposed Final / Governing V2 Baseline  
**Version:** 2.0  
**Date:** 2026-09-10  
**Architecture:** Modular monolith  
**Primary stack:** FastAPI/Python + PostgreSQL/pgvector + React

---

## 1. Technical Objective

Implement the Arc V2 product requirements without replacing stable foundations unnecessarily.

The technical strategy is:

```text
                    ARC V2
                      │
        ┌─────────────┴─────────────┐
        │                           │
  Control Plane                AI Platform
        │                           │
 Tenancy/Auth/RBAC          Company Brain / RAG
 Platform Admin             LLM / Intelligence
 Configuration              Skills / Tools
 Observability              Agent / Approvals
 Connectors                  Webhooks
        │                           │
        └─────────────┬─────────────┘
                      ↓
               PostgreSQL/pgvector
```

## 2. Architecture Style

Remain a modular monolith.

Logical modules:

- authentication
- tenancy
- authorization
- platform administration
- knowledge
- PII
- retrieval
- LLM
- intelligence
- skills
- tools
- agent
- approvals
- connectors
- webhooks
- observability

Modules communicate through explicit service boundaries.

Do not introduce network boundaries between modules unless scale or isolation requirements prove necessary.

## 3. Trust Boundaries

Every request must pass through the applicable chain:

```text
Authentication
 ↓
AuthenticatedPrincipal
 ↓
TenantContext
 ↓
RBAC
 ↓
Domain service
 ↓
Policy / validation
 ↓
Execution boundary
```

AI execution adds:

```text
AI proposal
 ↓
deterministic validation
 ↓
authorization
 ↓
risk policy
 ↓
human approval if required
 ↓
execution
```

The model never becomes the authority for authorization.

## 4. Tenant Context

TenantContext is authoritative for tenant identity.

Requirements:

- derive from trusted authentication/membership state
- never trust arbitrary request body tenant IDs
- verify path tenant IDs
- propagate through service calls
- use for retrieval filters
- use for connector operations
- use for execution records
- use for observability attribution

## 5. RBAC

Keep the existing permission-based model.

V2 must make Employee usable without creating a security bypass.

### Decision

Employee receives:

- `knowledge:read`
- `agent:execute`

Employee must **NOT** receive:

- `skill:execute`
- `tool:execute`

This is the final stakeholder architecture decision, superseding the prior C-1 interpretation that concluded Employee should receive only `knowledge:read`. See V2-ADR-005 for full rationale.

Employee-facing workflows use Unified Intelligence / Agent as the single execution boundary. The Employee initiates an Agent workflow; the Agent orchestrates Skills and Tools through SkillExecutionService and ToolExecutionService. Direct skill/tool invocation is not available to Employee.

SkillExecutionService and ToolExecutionService remain independently authorization-aware and enforce deterministic execution policy. High-risk actions require human approval regardless of the requesting principal's base permissions.

### Security Model

```text
Employee
  ↓
Agent (bounded, decision schema, skill allowlisting)
  ↓
SkillExecutionService (preconditions, principal policy, allowed tools)
  ↓
ToolExecutionService (authorization, policy, validation, execution, audit)
```

One execution path. One set of controls. One audit trail.

## 6. Execution Policy

Introduce/standardize a deterministic execution policy layer that can evaluate:

- principal role
- tenant policy
- skill risk
- tool risk
- declared permissions
- approval requirement
- platform capability availability

The policy must fail closed.

Suggested result:

```text
ALLOW
REQUIRE_HUMAN_APPROVAL
DENY
```

This policy is not an LLM decision.

## 7. Company Brain Data Flow

```text
Source
 ↓
Normalize
 ↓
PII inspection
 ↓
Persist document
 ↓
Chunk
 ↓
Embedding
 ↓
Persist chunks
 ↓
Searchable
```

Ingestion should be idempotent.

Failed embedding must not expose incomplete chunks as searchable content.

Connector ingestion uses the same Company Brain boundary.

## 8. Retrieval V2

Do not create `HybridRetrievalService`.

Extend the existing RetrievalService abstraction.

```text
RetrievalService
├── dense_search()
├── lexical_search()
└── approved_search()
        │
        └── RRF fusion
              ↓
        tenant validation
              ↓
        ApprovedContext
```

### Dense retrieval

Existing pgvector HNSW remains the semantic retrieval mechanism.

### Lexical retrieval

Add database-native lexical search appropriate for PostgreSQL.

The implementation must preserve tenant filtering.

### RRF

Fuse dense and lexical ranked lists using Reciprocal Rank Fusion.

RRF must be deterministic for identical inputs and data state.

### Reranking

Explicitly deferred.

Do not add a reranker dependency to the V2 critical path.

## 9. ApprovedContext

ApprovedContext is the only supported data contract from retrieval into production LLM generation.

It contains:

- sanitized content
- source/citation identifiers
- necessary provenance metadata

It must not contain arbitrary database records or security-sensitive internal metadata.

No retrieval result means no grounded answer.

## 10. Prompt Injection / Untrusted Content

Retrieved documents, connector content, webhook payloads, and external tool outputs are untrusted data.

AI prompts must structurally distinguish:

- system instructions
- trusted application instructions
- untrusted retrieved content
- tool results

The model must not be able to turn untrusted content into an authorization decision.

Tool arguments proposed by the model are data until validated by application code.

## 11. LLM Provider Architecture

Interfaces:

```text
LlmProvider
ToolProposingLlm
SkillSelectingLlm
```

Target runtime:

```text
AI Service
 ↓
OmniRoute
 ↓
OpenRouter
 ↓
configured model
```

Provider implementation must support:

- timeout
- safe retries
- structured output
- usage accounting
- latency
- provider error mapping
- model identifier
- correlation ID

Do not leak OpenRouter-specific request structures into domain services.

## 12. LLM Reliability

Use bounded retries only for retry-safe failures.

Never blindly retry:

- tool execution
- state-changing actions
- approval consumption

Provider calls should have:

- explicit timeout
- bounded retry count
- backoff
- failure classification

If the provider fails, return a controlled failure. Never fabricate an answer from incomplete execution.

## 13. LLM Cost/Usage

Record at minimum:

- provider
- model
- input tokens when available
- output tokens when available
- total tokens when available
- latency
- request timestamp
- tenant
- principal/run correlation

Do not store raw prompts/responses as observability by default.

## 14. Skills

Skill schema should include:

- id
- tenant
- name
- description
- version
- risk
- approval behavior
- allowed tools
- input schema
- lifecycle status

Execution:

```text
SkillExecutionService
 ↓
preconditions
 ↓
principal policy
 ↓
allowed tools
 ↓
ToolExecutionService
```

Skill-level `approval_required` is a gate.

It does not create the tool approval request itself.

## 15. Skill Execution Persistence

Add:

```text
skill_execution_records
```

Minimum fields:

- id
- tenant_id
- skill_id
- skill_version
- principal/user
- agent_run_id where applicable
- status
- started_at
- completed_at
- failure code/message
- bounded metadata
- PII-safe result summary

Use existing:

```text
agent_run_records
tool_execution_records
```

Do not recreate agent run persistence.

## 16. Tool Execution

Every tool call:

```text
resolve
 ↓
principal authorization
 ↓
declared tool permissions
 ↓
policy
 ↓
input schema
 ↓
handler
 ↓
audit record
```

No code path may invoke a tool handler while bypassing ToolExecutionService.

## 17. Human Approval

Approval object:

```text
tenant
principal
tool
tool version
arguments digest
policy decision
status
timestamps
```

Lifecycle:

```text
pending
 ↓
approved / rejected / expired
 ↓
consumed
```

Consumption must revalidate:

- tenant
- tool
- version
- arguments digest
- current authorization
- current tool policy
- input schema

Approval cannot be replayed.

## 18. Agent

Agent must remain bounded.

Controls:

- MAX_AGENT_STEPS = 3
- maximum execution duration
- explicit decision schema
- explicit allowed skills
- no unrestricted tools
- per-step authorization
- per-step persistence

Agent should use:

```text
Agent
 ↓
SkillExecutionService
 ↓
ToolExecutionService
```

The Agent does not directly create tool approval requests.

The tool execution path owns tool-level human approval creation.

## 19. Agent Trace

`agent_run_records` must capture enough metadata to reconstruct:

- trigger
- tenant
- principal
- steps
- selected skill
- tool invocations
- approval references
- result state
- failure state
- duration

Avoid storing raw tenant content unless explicitly required and PII protected.

## 20. Connectors

Provider interface:

```text
Connector
├── authenticate
├── validate
├── sync
└── normalize
```

Existing GitHub/Slack/Linear adapter architecture remains.

Credential architecture:

```text
Tenant
 ↓
ConnectorCredential
 ↓
EncryptionService
 ↓
ConnectorProvider
```

Credential storage must be tenant scoped.

Use envelope/key management that can support future key rotation.

Never expose decrypted credentials through API responses or logs.

## 21. Webhook Pipeline

```text
HTTP
 ↓
HMAC verification
 ↓
endpoint lookup
 ↓
tenant binding
 ↓
replay/idempotency check
 ↓
persist event
 ↓
processing state
 ↓
configured Skill
 ↓
SkillExecutionService
 ↓
ToolExecutionService
```

Webhook system principal remains minimal.

No arbitrary tenant from request payload.

## 22. Webhook Reliability

Persist processing states such as:

```text
received
processing
succeeded
retrying
failed
dead_letter
```

Retry policy:

- bounded
- exponential backoff
- only retry transient failures
- never retry authentication failures
- never duplicate state-changing work without idempotency

Webhook event IDs must provide a deduplication key.

## 23. Webhook Configuration

Support:

```text
DB configuration
      ↓
ENV fallback
```

DB configuration takes precedence.

Configuration includes:

- endpoint identifier
- tenant
- secret reference
- event type
- skill mapping
- enabled state
- retry policy

Secrets themselves are not returned by configuration APIs.

## 24. Observability Architecture

Collect structured metadata from:

- API requests
- retrieval
- LLM calls
- agent runs
- skill executions
- tool executions
- approvals
- connectors
- webhooks

Use a correlation ID across a workflow.

Example:

```text
request_id
   ↓
agent_run_id
   ↓
skill_execution_id
   ↓
tool_execution_id
```

Observability writes should not break the primary business workflow unless the record is itself a required audit artifact.

## 25. API Requirements

All list APIs should support pagination.

Recommended contract:

```text
items
page
page_size
total
```

or cursor pagination where dataset size/ordering requires it.

Validate:

- query parameters
- request body
- path parameters
- content length
- enum values

Use consistent HTTP error semantics.

## 26. Database Requirements

PostgreSQL + pgvector.

Required:

- tenant indexes
- foreign keys
- uniqueness constraints
- indexes for retrieval
- indexes for execution history
- migration scripts
- transactional writes for coupled records

Do not add PostgreSQL RLS simply because it is available. The application TenantContext boundary remains authoritative unless a measured requirement justifies RLS as a defense-in-depth layer.

## 27. Background Work

Use background execution only where necessary:

- webhook retry processing
- approval expiry sweep
- connector synchronization
- embedding jobs where asynchronous ingestion is required

Keep jobs idempotent.

A simple worker/job mechanism is sufficient for V2 unless operational scale proves otherwise.

## 28. API Documentation

OpenAPI must accurately reflect:

- auth
- tenant requirements
- permissions
- request/response schemas
- error codes
- pagination
- webhook behavior

Documentation changes follow API changes.

## 29. Configuration

Separate:

- application configuration
- provider configuration
- secrets
- tenant runtime configuration

Never use application environment variables as a substitute for tenant-isolated secrets.

Environment variables remain appropriate for infrastructure-level defaults.

## 30. Production Readiness Gates

### AI gates

An AI domain cannot be marked production-ready until:

- security boundary tested
- failure behavior tested
- evaluation set exists
- latency measured
- token/cost usage captured
- malformed model output handled
- prompt/data boundary reviewed
- E2E flow passes

### Non-AI gates

Must have:

- tests
- validation
- auth/RBAC
- tenant checks
- migration correctness
- predictable errors
- logging
- documentation where externally visible

## 31. Technical Non-Goals

Do not implement solely for perceived enterprise maturity:

- microservices
- service mesh
- Kubernetes
- Kafka
- distributed tracing infrastructure beyond current needs
- vector database migration
- reranking model
- agent long-term memory
- Google Drive
- dedicated incident database
- RLS
- speculative caching layer

## 32. Implementation Dependency Order

### Foundation / independent

- pagination
- API validation
- lifespan/logging
- tenant/platform UI correctness

### AI core

- RAG V2
- skill execution persistence
- production LLM
- AI usage telemetry
- AI evaluation suite

### Execution

- Employee AI workflow policy
- connector credential isolation
- human approval completion
- Agent execution hardening

### Event-driven

- webhook DB configuration
- webhook reliability/retries

### Final integration

- complete E2E workflows
- observability verification
- security regression
- deployment validation

Parallel work is allowed when contracts are stable.

## 33. Definition of Technical Done

A PR is done only when:

- scope is narrow
- architecture follows this TRD
- tests cover behavior and failure
- security boundaries are preserved
- migrations are safe
- logs/metrics are appropriate
- no unrelated refactor is included
- documentation is updated where needed
- E2E impact is understood

---

# TECHNICAL RULE

**Prefer the existing abstraction if it is correct. Extend it before replacing it.**

V2 should make Arc substantially more capable and production-ready without turning the modular monolith into an unnecessary distributed system.
