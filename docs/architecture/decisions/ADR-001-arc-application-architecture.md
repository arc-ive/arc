# ADR-001: Arc Application Architecture and AI Runtime Foundation

## Status

Proposed

## Date

2026-08-14

## Decision Owners

- Joe — Product + Roadmap
- Bala — Engineering + AI
- Bharath — Platform + DevOps

---

## Context

Arc is a 7-day, placement-oriented enterprise AI project for demonstrating an end-to-end AI platform.

The primary goal is not to build a commercially complete SaaS product or production-scale enterprise infrastructure. The goal is to build a working, understandable system demonstrating how company knowledge, PII protection, secure retrieval, skills/procedures, AI agents, AI tools, webhooks, automated actions, observability, and human intervention can operate together.

The team is primarily composed of Python developers and has an implementation window of approximately seven days.

The architecture therefore needs to balance:

1. AI capability
2. Learning value
3. Implementation speed
4. Simplicity
5. Maintainability
6. Local reproducibility
7. Placement/interview value

The project should avoid infrastructure that is not justified by current requirements.

The conceptual architecture is:

```text
ARC ENTERPRISE AI PLATFORM
             |
    +--------+--------+
    |        |        |
 Multi-   Auth/     Connectors
 Tenant    RBAC
    |        |        |
    +--------+--------+
             |
         PII GUARD
             |
             v
      COMPANY BRAIN
             |
      +------+------+
      |             |
   SECURE RAG   SKILLS ENGINE
      |             |
      +------+------+
             |
          AI AGENT
             |
      +------+------+
      |             |
   AI TOOLS      WEBHOOKS
      |             |
      +------+------+
             |
       OBSERVABILITY
             |
       HUMAN REVIEW
```

This is a conceptual product architecture. It does not imply that every box must become a separate service or container.

---

## Problem

The project needs a clear application architecture that allows the team to implement the AI-focused workflow without spending most of the seven-day period building infrastructure.

Without an architectural baseline, the team could introduce unnecessary complexity such as:

- multiple microservices
- Kubernetes
- Kafka
- Redis
- separate vector databases
- large observability stacks
- cloud infrastructure
- complex AI agent frameworks

These choices could consume implementation time and make the project harder for the team to understand.

At the same time, the architecture must support the core workflow:

```text
Company Information
       |
    PII Guard
       |
  Company Brain
       |
   Secure RAG
       |
     Skill
       |
    AI Agent
       |
    AI Tool
       |
     Action
       |
 Observability
       |
Human Intervention
```

---

## Decision

The proposed architecture is a Python-first, containerized application with:

- Python 3.12
- FastAPI
- PostgreSQL + pgvector
- a hybrid Company Brain
- Secure RAG
- OmniRoute → OpenRouter → configurable AI model
- a custom lightweight tool-calling Agent
- Docker/Docker Compose for local execution

The proposed initial shape is:

```text
Docker Compose
      |
+-----+----------------+
|                      |
v                      v
Arc Application     PostgreSQL
Python 3.12         + pgvector
|
+-- FastAPI
+-- Company Brain
+-- Secure RAG
+-- Skills Engine
+-- AI Agent
+-- AI Tools
+-- Webhooks
+-- PII Guard
+-- Observability
|
v
OmniRoute
|
v
OpenRouter
|
v
Configurable AI Model
```

These are initially logical application components. They are not automatically independent deployable services.

---

## Decision 1 — Application Language

### Python 3.12

Python 3.12 is proposed as the standard application runtime.

### Reason

All developers are primarily Python developers.

Python also provides the ecosystem required for:

- AI/LLM integration
- FastAPI
- Pydantic
- database access
- vector search
- PII detection
- testing
- data processing

Using one application language reduces unnecessary learning and integration overhead.

---

## Decision 2 — Backend Framework

### FastAPI

FastAPI is proposed as the application API framework.

It will provide HTTP functionality for:

- application APIs
- Company Brain operations
- Secure RAG
- Agent execution
- AI tool endpoints where appropriate
- webhook endpoints
- health endpoints
- observability endpoints

FastAPI does not determine the internal architecture of the AI components.

The initial application may remain a modular monolith.

---

## Decision 3 — Application Architecture

### Modular Application Rather Than Microservices

The initial implementation will use a modular application structure.

Conceptually:

```text
app/
|
+-- api/
+-- auth/
+-- tenancy/
+-- pii/
+-- company_brain/
+-- rag/
+-- skills/
+-- agent/
+-- tools/
+-- webhooks/
+-- observability/
```

These modules represent logical responsibilities. They do not automatically represent separate deployable services.

A component should only become a separate service if a concrete requirement demonstrates that separation is useful.

---

## Decision 4 — Company Brain

### Hybrid Structured + Semantic Knowledge

The Company Brain will not be implemented as only a vector store.

It will conceptually contain:

- knowledge
- procedures
- policies
- skills
- decisions
- incidents
- solutions
- provenance
- permissions
- tenant context
- semantically searchable content

The proposed representation is hybrid:

```text
Structured Company Information
            +
     Searchable Content
            +
        Embeddings
```

The Company Brain is intended to represent both:

- what the company knows
- how the company operates

It is the central knowledge layer used by Secure RAG and the AI Agent.

---

## Decision 5 — Database and Vector Search

### PostgreSQL + pgvector

PostgreSQL with pgvector is proposed as the initial persistence layer.

PostgreSQL will store structured information such as:

- tenants
- users
- knowledge metadata
- procedures
- policies
- skills
- incidents
- audit events
- agent executions
- tool executions
- usage information

pgvector will support embedding storage and vector similarity retrieval for Secure RAG.

This avoids introducing a separate vector database during the initial implementation.

The proposed storage architecture is:

```text
PostgreSQL
|
+-- Structured application data
+-- Tenant data
+-- Knowledge metadata
+-- Agent/tool records
+-- Embeddings via pgvector
```

---

## Decision 6 — Secure RAG

Secure RAG will use the same application authorization and tenant context as the rest of Arc.

The intended retrieval flow is:

```text
User
  |
Authentication
  |
Tenant Context
  |
Authorization
  |
User Query
  |
Embedding
  |
Vector Retrieval
  |
Tenant Filtering
  |
Permission Filtering
  |
Approved Context
  |
AI Model
  |
Response
```

Authentication alone must not determine whether knowledge can be retrieved.

Retrieval must respect:

- tenant
- user
- role
- permissions
- knowledge access rules

Cross-tenant retrieval must be prevented.

---

## Decision 7 — AI Provider Routing

### OmniRoute → OpenRouter → Configurable Model

The proposed AI request path is:

```text
Arc
 |
OmniRoute
 |
OpenRouter
 |
Configurable Model
```

The application should not hard-code a specific model into the Agent implementation.

The model should be configurable.

The exact model remains an implementation decision based on:

- availability
- tool-calling support
- performance
- cost
- project requirements

OpenRouter is intended as the primary external model provider.

OmniRoute provides a routing/abstraction layer between the application and model providers.

This allows model/provider changes without rewriting the Agent.

### Development Tool Distinction

OpenCode is a development/coding assistant used by the team. It is not an Arc runtime component.

```text
OpenCode
   |
helps developers build Arc

OmniRoute
   |
used by Arc as the AI gateway

OpenRouter
   |
used by Arc as an AI model provider
```

---

## Decision 8 — AI Agent

### Custom Lightweight Tool-Calling Agent

The initial AI Agent will be implemented as a lightweight application-controlled tool-calling loop rather than relying on a large agent framework.

The conceptual flow is:

```text
Task / Event
     |
   Agent
     |
Company Brain
     |
   Skill
     |
    LLM
     |
Tool Decision
   /     \
 No       Yes
 |          |
Response   Tool
             |
        Tool Result
             |
            LLM
             |
      +------+------+
      |             |
    Finish       Continue
      |
Human escalation when required
```

The Agent will use controlled tools rather than directly accessing arbitrary infrastructure.

Examples:

- search_company_knowledge
- get_incident_history
- check_service_health
- create_incident
- update_ticket
- restart_service
- send_notification
- escalate_to_human

The Agent must respect authorization and tool-level restrictions.

---

## Decision 9 — Skills Engine

The Skills Engine will represent executable or semi-executable company procedures.

A Skill may contain:

- name
- purpose
- inputs
- preconditions
- steps
- constraints
- allowed tools
- risk level
- approval requirements
- failure behavior
- expected output
- provenance/version

Example:

```text
Skill: Service Recovery

Preconditions:
- service is unhealthy

Steps:
1. Check current health
2. Retrieve recent incidents
3. Determine whether restart is allowed
4. Restart service
5. Verify health

Failure:
- escalate to human
```

The exact storage format for Skills remains an implementation detail.

---

## Decision 10 — PII Guard

PII Guard will be implemented as a processing boundary for sensitive information.

The conceptual flow is:

```text
Input
  |
PII Detection
  |
Redaction
  |
Sanitized Data
  |
Downstream AI Processing
```

The exact PII detection library remains open.

The first implementation should prioritize:

- common PII detection
- predictable redaction
- avoiding unnecessary sensitive-data logging
- integration with AI workflows

Complex reversible tokenization is not required unless a concrete workflow requires it.

---

## Decision 11 — Webhooks

Webhooks will initially be treated as application-level HTTP event endpoints.

The intended workflow is:

```text
External / Simulated Event
          |
       Webhook
          |
      Validation
          |
     Tenant Context
          |
        Agent
          |
        Skill
          |
        Tool
          |
        Action
          |
      Verification
          |
     Observability
```

The initial implementation does not require a dedicated message broker.

Controlled or simulated external events are acceptable for the placement project.

---

## Decision 12 — Observability

Observability will initially be implemented at a lightweight application level.

The system should capture enough information to understand:

- API requests
- AI requests
- agent executions
- tool calls
- webhook events
- latency
- failures
- successful automated actions
- human escalations
- tenant usage
- service health
- incidents

A large observability stack is not required unless later requirements justify it.

The exact observability technology remains open.

---

## Decision 13 — Deployment

The initial deployment target is local Docker.

The project does not require AWS deployment for the current implementation scope.

The development environment should be reproducible through Docker/Docker Compose.

The initial target is:

```text
Developer
   |
Docker Compose
   |
Arc Application
   |
PostgreSQL + pgvector
   |
External AI Gateway/Provider
```

Cloud infrastructure remains outside the current implementation requirement.

---

## Decision 14 — Infrastructure Simplicity

The following are NOT automatically required:

- Kubernetes
- Redis
- Kafka
- RabbitMQ
- Elasticsearch
- separate vector database
- separate object storage
- Prometheus
- Grafana
- AWS infrastructure
- multiple application containers
- one container per logical module

Additional infrastructure may be introduced only when a concrete requirement and architecture decision justify it.

---

## Options Considered

### Option 1 — Modular Monolith + PostgreSQL/pgvector

Description:

One primary Python application containing the logical Arc components, backed by PostgreSQL with pgvector.

Advantages:

- fastest to implement
- easiest for the team to understand
- easiest to debug
- simple local deployment
- fewer moving parts
- suitable for seven-day scope
- demonstrates AI architecture clearly
- avoids premature microservice complexity

Disadvantages:

- components are less independently deployable
- scaling individual components independently is limited
- future service extraction may be required if the product grows

### Option 2 — Microservices

Description:

Separate deployable services for components such as:

- Company Brain
- RAG
- Agent
- Webhooks
- PII
- Observability

Advantages:

- independent deployment
- independent scaling
- stronger service isolation

Disadvantages:

- significantly more infrastructure
- networking complexity
- service discovery/configuration
- distributed debugging
- more Docker configuration
- more failure modes
- less time available for AI implementation
- higher learning overhead

### Option 3 — Serverless / Cloud-First Architecture

Description:

Build the system primarily around managed cloud services.

Advantages:

- managed infrastructure
- potentially easier production scaling

Disadvantages:

- unnecessary for current project scope
- cloud dependency
- additional configuration
- possible cost
- reduced local reproducibility
- distracts from AI implementation

---

## Rationale

Option 1 is proposed because it best matches the actual project constraints.

The project has approximately seven days.

The team needs to understand the complete system rather than specialize in infrastructure.

The main learning and demonstration value comes from:

```text
Company Brain
     |
 Secure RAG
     |
   Skills
     |
 AI Agent
     |
 AI Tools
     |
 Webhooks
     |
Automated Action
     |
Observability
     |
Human Intervention
```

A modular monolith allows these components to be developed and understood as one connected system without requiring distributed-system infrastructure.

PostgreSQL + pgvector provides both structured persistence and vector retrieval without introducing a separate vector database.

A custom Agent loop allows the team to understand tool calling and agent behavior directly.

OmniRoute + OpenRouter provides model/provider flexibility without coupling the Agent directly to one model.

---

## Consequences

### Positive

- fast implementation
- simple local development
- easy debugging
- low infrastructure overhead
- strong AI learning value
- easy end-to-end demonstration
- clear logical component boundaries
- model/provider flexibility
- structured and semantic Company Brain
- Secure RAG can share tenant and authorization context
- easier onboarding for team members

### Negative

- initial application may become larger as capabilities grow
- independent scaling is limited
- some components may eventually need extraction into services
- PostgreSQL may become insufficient for very large workloads
- custom Agent implementation requires more engineering than using a framework

### Risks

- team may still over-engineer module boundaries
- Company Brain schema may become too complex
- Agent behavior may become difficult to control
- AI provider availability may change
- free AI models may have inconsistent quality
- permission filtering may be implemented incorrectly
- PII detection may produce false positives/negatives
- automated actions may require stronger approval controls

---

## Security Considerations

### Authentication

Protected functionality must require authentication.

### Authorization

Authorization must be enforced server-side.

### Tenant Isolation

Tenant context must be enforced across:

- APIs
- Company Brain
- RAG
- Skills
- Agent
- Tools
- Webhooks
- observability data

Cross-tenant access must be rejected.

### AI Security

The Agent must not bypass authorization.

Retrieved context must be filtered before being provided to the AI model.

### Tool Security

Tools must have defined:

- permissions
- input validation
- risk level
- allowed usage

High-risk actions should require human intervention.

### PII

PII must not be unnecessarily exposed to AI providers.

Sensitive information must not be unnecessarily written to logs.

### Secrets

API keys and credentials must not be committed to Git.

Secrets must be provided through environment configuration.

---

## Operational Considerations

### Local Development

The project should run through Docker/Docker Compose.

### Monitoring

The application must expose enough operational information to understand:

- health
- errors
- AI usage
- agent activity
- tool activity
- webhook activity
- incidents

### Failure Recovery

The system should explicitly handle:

- AI provider failures
- retrieval failures
- tool failures
- webhook failures
- invalid inputs
- human escalation

### Cost

The architecture should prefer:

- free/open-source tools
- low-cost AI providers/models
- local infrastructure

### Maintenance

The application should use clear module boundaries without requiring separate services.

---

## Testing / Validation

This architecture will be validated through end-to-end workflows.

### Validation 1 — Basic Application

Verify:

- application starts
- health endpoint works
- database connection works
- schema initialization works

### Validation 2 — Company Brain

Verify:

- knowledge can be stored
- knowledge has tenant context
- knowledge can be retrieved
- provenance is preserved

### Validation 3 — Secure RAG

Verify:

- authorized information is retrieved
- unauthorized information is filtered
- cross-tenant information cannot be retrieved
- retrieved context reaches the model

### Validation 4 — Agent

Verify:

- Agent can receive a task
- Agent can retrieve relevant knowledge
- Agent can identify a Skill
- Agent can call a Tool
- Agent can process Tool results
- Agent can finish or continue

### Validation 5 — Automated Action

Verify:

```text
Event
  |
Agent
  |
Skill
  |
Tool
  |
Action
  |
Verification
```

### Validation 6 — Human Intervention

Verify:

- high-risk action is not automatically executed
- human approval can be requested
- Agent can continue after approval

### Validation 7 — Observability

Verify that an Agent execution can be investigated after completion.

The team should be able to answer:

- What triggered the Agent?
- Which tenant was involved?
- Which knowledge was retrieved?
- Which Skill was selected?
- Which Tool was called?
- What action occurred?
- Did it succeed?
- Was human intervention required?

---

## Related Documents

- `docs/requirements/Arc_PRD.md`
- `docs/requirements/TRD.md`
- `PROJECT_CONTEXT.md`
- `CURRENT_STATE.md`
- `SECURITY.md`

---

## Related Work

- Linear: Arc Foundation / implementation issues
- GitHub: Arc repository

---

## Supersedes

N/A

---

## Superseded By

N/A

---

## Implementation Boundary

This ADR establishes the proposed architectural baseline.

It does NOT finalize:

- exact AI model
- exact PII library
- exact authentication implementation
- exact connector selection
- exact observability technology
- exact Skill schema
- exact Company Brain schema
- exact Agent state/memory implementation
- exact webhook event schema

Those decisions should be recorded separately when they become necessary.

---

## Review Required

Before this ADR changes from `Proposed` to `Accepted`:

### Bala must review

- Python 3.12
- FastAPI
- PostgreSQL + pgvector
- Hybrid Company Brain
- Secure RAG architecture
- OmniRoute/OpenRouter
- custom Agent loop
- AI security implications

### Bharath must review

- Docker
- Docker Compose
- local environment
- PostgreSQL + pgvector container
- environment variables
- reproducibility
- CI implications

### Joe must review

- alignment with product scope
- seven-day implementation feasibility
- AI-first priorities
- product boundaries

---

## Acceptance Condition

This ADR may be marked `Accepted` when:

1. Bala approves the technical/AI architecture.
2. Bharath confirms the platform/environment is reproducible.
3. Joe confirms the architecture remains within the approved product scope.
4. No unresolved decision blocks the first implementation slice.
