# ADR-001: Arc Unified Intelligence and Secure Application Architecture

## Status
Proposed

## Date
2026-08-14

## Decision Owners
- Joe — Product scope and requirements
- Bala — Engineering and AI architecture review
- Bharath — Platform, Docker, CI, and delivery review
- All three developers — Architecture, security, quality, and final implementation review

## Context

Arc is a 7-day placement-oriented enterprise AI engineering project. The
approved PRD/TRD direction requires authenticated multi-tenant access,
tenant-aware RBAC, PII/security protection, Company Brain, Secure RAG,
Skills, Unified Intelligence, controlled AI Tools, webhook workflows,
observability, automated actions, human intervention, reproducible Docker
execution, CI validation, and AWS deployment after local validation.

Unified Intelligence is the **single intelligence layer**. Company Brain
and AI Agent are functional capabilities within it, not separate
intelligence systems.

External company-source data and webhook/event payloads must not appear to
enter protected Company Brain or Unified Intelligence processing through an
unrestricted path.

The project is intentionally limited to seven days. Logical components do
not automatically become separate microservices, containers, databases, or
repositories.

The PRD is the product source of truth and contains the canonical
high-level architecture diagram. The TRD defines technical direction and
explicitly leaves several implementation decisions open. This ADR records
the significant architecture decisions without silently finalizing those
open decisions.

## Decision

Arc will use a **modular application architecture with Unified
Intelligence as the single intelligence layer**, while preserving explicit
security and data-processing boundaries around external inputs.

### Canonical architecture

```text
                         ARC ENTERPRISE AI PLATFORM
                                      |
                 +--------------------+--------------------+
                 |                    |                    |
           Multi-Tenancy        Authentication            RBAC
                 |                    |                    |
                 +--------------------+--------------------+
                                      |
                         EXTERNAL INPUT / DATA BOUNDARY
                                      |
          +---------------------------+---------------------------+
          |                                                       |
          v                                                       v
 External Company Sources / Connectors                  External Webhooks /
          |                                             Operational Events
          v                                                       |
 Data Ingestion / Validation                                      |
          |                                                       |
          +---------------------------+---------------------------+
                                      |
                                  PII GUARD
                           (where applicable/required)
                                      |
                                      v
             +-----------------------------------------------+
             |             UNIFIED INTELLIGENCE              |
             |                                               |
             |  +-------------------------------------------+|
             |  |              COMPANY BRAIN                ||
             |  | Knowledge / Procedures / Policies        ||
             |  | Decisions / Incidents / Solutions        ||
             |  | Relationships / Provenance / Memory      ||
             |  +----------------------+--------------------+|
             |                         |                     |
             |                 Secure RAG / Knowledge       |
             |                         |                     |
             |                    Embeddings                |
             |                         |                     |
             |  +----------------------v-------------------+ |
             |  |               AI AGENT                    | |
             |  | Reasoning / Planning / Skill Selection  | |
             |  | Tool Selection / Execution / Escalation | |
             |  +----------------------+-------------------+ |
             |                         |                     |
             |                        LLM                    |
             +-------------------------+---------------------+
                                       |
                                Controlled AI Tools
                                       |
                                 Tool Execution
                                       |
                         +-------------+-------------+
                         |                           |
                         v                           v
                  Internal Arc Systems       Approved External Systems

Data Ingestion --> protected Company Brain / RAG
Webhooks --------> validation + applicable PII/security --> Unified Intelligence

Structured Company Data <--> PostgreSQL
Semantic Knowledge     <--> pgvector / Embeddings

Relevant application events/metrics --> Observability
Local Docker-first ------------------> AWS follow-on
```

### Interpretation

- **Unified Intelligence** is the single intelligence layer.
- **Company Brain** provides company knowledge, procedures, policies,
  decisions, incidents, solutions, relationships, provenance, memory, and
  operational context.
- **AI Agent** provides reasoning, planning, Skill selection, Tool
  selection, execution coordination, failure handling, and escalation.
- **LLM** provides configurable reasoning, language understanding, planning,
  and generation.
- **Secure RAG** retrieves relevant knowledge while preserving tenant and
  permission boundaries.
- **Embeddings** support semantic representation and retrieval.
- **Memory** is part of Company Brain/Unified Intelligence; its exact
  implementation remains open.
- **AI Tools / Tool Execution** are controlled action interfaces.
- External data and events must pass through the applicable ingestion,
  validation, and PII/security boundary before protected AI processing.
- Observability records relevant usage and operational events while
  respecting sensitive-data handling requirements.

## Connector / Data Ingestion Security Boundary

The required conceptual flow is:

```text
External Company Sources / Connectors
              |
              v
    Data Ingestion / Validation
              |
              v
          PII Guard
              |
              v
      Company Brain / RAG
              |
              v
      Unified Intelligence
```

Connector data must not bypass the applicable PII/security boundary.

The PII Guard is a logical security boundary. The exact PII technology is
an implementation decision unless separately approved.

Tenant isolation and authorization remain application responsibilities.

## Webhook / Operational Event Security Boundary

The required conceptual flow is:

```text
External Webhook / Event Source
              |
              v
       Webhook Endpoint
              |
              v
    Validation / Ingestion
              |
              v
      PII Guard where applicable
              |
              v
      Tenant / Authorization Context
              |
              v
      Unified Intelligence
              |
              v
   Company Brain / Tools / Actions
```

Webhook payloads are untrusted external input. They must be validated and
subjected to the applicable authentication, authorization, tenant, and
PII/data-protection controls before protected processing.

Webhook authentication/signature details, retry strategy, and event schema
remain open.

## Unified Intelligence Boundary

Company Brain and Agent are capabilities inside one intelligence system:

```text
                 UNIFIED INTELLIGENCE
                         |
             +-----------+-----------+
             |                       |
        Company Brain           AI Agent
             |                       |
      Knowledge / RAG          Reasoning / Planning
      Memory / Context         Skill / Tool Selection
             |                       |
             +-----------+-----------+
                         |
                        LLM
                         |
                  Approved Tools
```

They are not independent intelligence layers.

## AI Provider and Model Boundary

The Arc runtime path is:

```text
Arc
 |
 v
OmniRoute
 |
 v
OpenRouter
 |
 v
Configurable LLM
```

- **OmniRoute** is the Arc AI routing/gateway layer where configured.
- **OpenRouter** is the external model provider/gateway.
- **LLM** is the configurable model used by Unified Intelligence.
- The exact model is not fixed by this ADR.

Model selection remains configurable and may be evaluated using
tool-calling capability, reasoning quality, latency, availability, cost,
context window, and reliability.

### OpenCode boundary

OpenCode is a **developer/coding assistant**, not an Arc runtime
component.

Developer workflow:

```text
Developer -> OpenCode -> OmniRoute -> OpenRouter -> Model Pool
```

Arc runtime:

```text
Arc -> OmniRoute -> OpenRouter -> Configurable LLM
```

OpenCode must not be represented as part of the deployed Arc Agent or
runtime architecture.

## Technology / Decision Scope

### Approved architecture decisions

The current PRD/TRD direction establishes:

- Python 3.12
- FastAPI
- Unified Intelligence
- Company Brain + AI Agent as capabilities within Unified Intelligence
- Hybrid Company Brain
- PostgreSQL + pgvector
- Secure RAG with tenant/permission boundaries
- Controlled AI Tools
- OmniRoute -> OpenRouter -> configurable LLM
- Docker / Docker Compose as the initial deployment/development shape
- AWS as the follow-on deployment target
- External-input ingestion, validation, and applicable security/PII
  boundaries

### Implementation recommendations

These are current technical directions, not irreversible architecture
commitments:

- PostgreSQL schema organization
- pgvector indexing strategy
- FastAPI package structure
- Docker Compose service arrangement
- open-source libraries for agent/tool implementation
- ingestion pipeline implementation
- observability libraries/dashboard
- connector adapters

They should remain proportional to the 7-day scope.

### Open / deferred decisions

The following must remain explicitly open:

- exact AI model
- exact PII implementation
- authentication implementation
- connector selection
- observability implementation
- frontend implementation
- Skill schema/serialization
- Company Brain schema
- Agent state/memory implementation
- webhook event schema
- webhook authentication/signature strategy
- webhook retry strategy
- exact embedding model
- exact AI Tool framework/library
- exact backend package structure
- exact AWS service mapping
- exact human-approval implementation

An implementation choice does not automatically become an architecture
decision. If it materially changes the approved architecture, review it
and record it through an ADR.

## Company Brain

Company Brain is a hybrid knowledge system:

```text
                 COMPANY BRAIN
                       |
          +------------+------------+
          |                         |
   Structured Knowledge       Semantic Knowledge
          |                         |
     PostgreSQL              Embeddings / pgvector
          |                         |
          +------------+------------+
                       |
                Secure Retrieval
                       |
              Unified Intelligence
```

It is not merely a vector database. It combines structured records,
semantic knowledge, relationships, provenance, procedures, policies,
decisions, incidents, solutions, operational context, and memory.

The exact schema remains open.

## Secure RAG

```text
Request / Event
      |
      v
Authentication
      |
      v
Tenant Context
      |
      v
Authorization
      |
      v
PII / Data Protection
      |
      v
Knowledge Retrieval
      |
      v
Tenant + Permission Filtering
      |
      v
Approved Context
      |
      v
Unified Intelligence / LLM
```

The LLM, embeddings layer, and vector store are not authorization systems.

## AI Agent

The Agent is a functional capability inside Unified Intelligence.

Responsibilities:

- interpret requests/events
- determine required context
- retrieve/request knowledge
- select Skills
- plan workflows
- select approved Tools
- coordinate execution
- interpret Tool results
- handle failures
- escalate to humans

The Agent must not bypass authorization, tenant isolation, approved Tools,
or human-approval requirements, and must not execute arbitrary code.

The current direction is a **custom lightweight tool-calling Agent**.
An agent framework is not a permanent architecture dependency.

## AI Tools

```text
Unified Intelligence
        |
        v
   Tool Selection
        |
        v
 Authorization / Validation
        |
        v
   Tool Execution
        |
        v
 Internal / Approved External System
        |
        v
       Result
```

The AI Tool architecture remains framework/tool agnostic. Suitable
open-source libraries may be used where they provide clear value.

The LLM must not receive unrestricted Python, OS, shell, database, or
network access.

## PII Guard

The architecture requires a PII/security protection layer.

The exact implementation is **not finalized by this ADR**.

Microsoft Presidio is the current TRD technology direction/candidate, but
this ADR does not convert it into an irreversible architecture commitment.

If Presidio is selected, the initial text flow is:

```text
Input
  |
  v
Presidio Analyzer
  |
  v
PII Detection
  |
  v
Presidio Anonymizer
  |
  v
Sanitized Content
  |
  v
Protected AI / Data Processing
```

PII protection is not the complete security boundary. Authentication,
authorization, tenant isolation, data minimization, and secure logging
remain necessary.

## Logical Components Are Not Automatically Services

The following are logical components:

- PII Guard
- Data Ingestion
- Company Brain
- Secure RAG
- Skills Engine
- Unified Intelligence
- AI Agent capability
- AI Tools
- Webhooks
- Observability

They do not automatically require separate microservices, containers,
databases, or repositories.

Use the smallest practical deployment shape that demonstrates the required
behavior.

## Deployment

```text
Local Docker-first
        |
        v
Validation / Demonstration
        |
        v
AWS follow-on
```

The exact AWS service mapping remains open and must not block local work.

## Alternatives Considered

### Option 1 — Modular application architecture

Clear logical modules within a small application.

**Advantages**
- Fits the 7-day project.
- Easier end-to-end understanding.
- Preserves security and responsibility boundaries.
- Avoids unnecessary distributed-system complexity.

**Disadvantages**
- Logical components do not independently scale.
- Some boundaries are application-level.

### Option 2 — Microservice per conceptual component

Separate services for PII, Company Brain, RAG, Skills, Agent, Tools,
Webhooks, Observability, etc.

**Advantages**
- Strong independent service boundaries.
- Independent deployment/scaling.

**Disadvantages**
- Excessive for seven days.
- Adds networking, deployment, service-discovery, and operational work.
- Conflicts with the requirement to keep the system understandable.

### Option 3 — Undifferentiated monolith

Implement everything without explicit logical boundaries.

**Advantages**
- Fastest initial implementation.

**Disadvantages**
- Weak security and responsibility boundaries.
- Harder to test and explain.
- Conflicts with the modular Unified Intelligence design.

## Rationale

Option 1 is selected because it best matches the approved scope.

The project demonstrates enterprise-AI behavior rather than distributed
systems infrastructure. The architecture therefore preserves important
security and responsibility boundaries without unnecessary service
decomposition.

The most important constraints are:

1. external data/events cannot bypass applicable security/PII controls;
2. Company Brain and Agent remain one Unified Intelligence system;
3. the Arc runtime AI path is distinct from developer AI tooling;
4. open implementation decisions remain open.

## Consequences

### Positive

- Clear single-intelligence architecture.
- Explicit connector and webhook security boundaries.
- Clear separation between runtime AI and development tooling.
- Configurable LLM architecture.
- Open decisions are not accidentally finalized.
- Practical for the 7-day project.

### Negative

- Some implementation details remain undecided.
- Application-level boundaries provide less isolation than separate services.
- PII, authentication, connectors, observability, and memory still require
  implementation decisions.

### Risks

- Connector/webhook code could accidentally bypass PII/security controls.
- A model could become accidentally hard-coded.
- OpenCode could be mistaken for a runtime component.
- An AI framework could become unnecessarily coupled.
- RAG could leak unauthorized/cross-tenant information.
- Automated PII detection may miss sensitive values.

## Security Considerations

### Authentication
Authentication establishes identity. Enterprise SSO is **Out of Scope**.
The exact implementation remains open.

### Authorization / RBAC
Authorization determines whether an authenticated user may access a
resource or perform an action. Tenant context must be established before
tenant-scoped data access.

### Connector Security
Connector data must pass through ingestion, validation, and applicable
PII/security controls before protected Company Brain/Unified Intelligence
processing.

### Webhook Security
Webhook requests are untrusted external input. Validation and applicable
authentication, authorization, tenant, and PII controls must be applied
before protected processing.

### Secure RAG
Retrieved content must be tenant- and permission-filtered before being
provided to the LLM.

### AI Security
The LLM cannot bypass authorization, tenant isolation, approved Tools, or
human approval requirements and cannot execute arbitrary code.

### Secrets
Credentials must remain outside Git.

## Operational Considerations

### Local Development
The project is Local Docker-first and must be reproducible.

### Observability
Relevant AI and operational events should include usage, token counts
where available, agent runs, tool calls, webhook events, latency,
success/failure, tenant usage, health, incidents, actions, and human
escalations. Exact implementation remains open.

### AWS
AWS follows local validation. Exact service mapping remains open.

## Testing / Validation

### Connector security
- Connector data enters through ingestion/validation.
- Applicable PII/security processing occurs.
- Tenant context is preserved.
- Cross-tenant data cannot enter another tenant's context.

### Webhook security
- External events reach the webhook boundary.
- Events are validated.
- Applicable PII/security controls run.
- Tenant/authorization controls run before protected processing.

### Unified Intelligence
- Company Brain context can be retrieved.
- Agent capability can select a Skill.
- Agent capability can select an approved Tool.
- Tool execution is controlled.
- Results return to Unified Intelligence.
- Failure/high-risk conditions can escalate.

### AI provider
- Arc can use OmniRoute where configured.
- OmniRoute can route to OpenRouter.
- The LLM model can be changed without changing product architecture.

### Secure RAG
- Authorized knowledge is retrieved.
- Unauthorized knowledge is filtered.
- Cross-tenant retrieval fails.

### PII
- The selected PII implementation detects supported test PII.
- Sanitization occurs before protected processing.
- Sensitive values are not unnecessarily logged.

### Tool security
- Authorized tool execution succeeds.
- Invalid inputs are rejected.
- Unauthorized tool execution is blocked.
- Arbitrary code execution is unavailable.

### Reproducibility
- Docker startup works as documented.
- CI builds/tests the application.
- Developers can explain the major architecture and flows.

## Related Documents

- `docs/requirements/PRD.md`
- `docs/requirements/TRD.md`
- `docs/architecture/decisions/ADR_TEMPLATE.md`

The PRD defines product behavior and contains the canonical product-level
architecture diagram.

The TRD defines technical requirements and implementation direction.

ADRs record significant architecture decisions.

## Related Work

- Linear: Arc implementation and architecture work
- GitHub: Arc repository and pull requests

## Supersedes
None.

## Superseded By
None.

## Review Notes

This ADR remains **Proposed** until architecture review is complete.

It intentionally does not finalize the exact AI model, PII
implementation, authentication implementation, connectors, observability,
frontend, Skill schema, Company Brain schema, Agent memory/state, webhook
schema/security details, embedding model, AI Tool framework, backend
package structure, AWS service mapping, or human-approval implementation.

If a future decision materially changes this architecture, record it in a
new ADR rather than silently changing the historical decision.
