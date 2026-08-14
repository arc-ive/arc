# ARC — Technical Requirements Document (TRD)

**Project:** Arc Enterprise AI Platform
**Project Type:** 7-day placement-oriented engineering project
**Domain:** IT Services / Enterprise AI
**Status:** Revised — PR Review Changes Incorporated
**Primary Technical Focus:** PII Guard, Company Brain, Secure RAG, Unified Intelligence, Skills, AI Tools, Webhooks, Observability
**Deployment Strategy:** Local Docker-first → AWS deployment
**Primary Development Language:** Python 3.12
**AI Provider:** OpenRouter with configurable model selection
**AI Routing:** OmniRoute / configurable routing where used

---

# 1. Purpose

This Technical Requirements Document translates the Arc Product Requirements Document into a practical technical implementation direction.

The TRD defines:

- technical responsibilities of the major Arc components
- proposed technology choices and why they are suitable
- AI and RAG responsibilities
- Unified Intelligence architecture
- PII protection
- AI tool execution
- webhook processing
- observability
- local Docker development
- CI requirements
- AWS deployment direction

This document is intentionally designed for a **7-day placement-oriented engineering project**.

The goal is to demonstrate that the team understands and can implement an end-to-end enterprise AI workflow.

The TRD does **not** require every conceptual component to become a separate service or container.

---

# 2. Technical Objectives

Arc should technically demonstrate:

1. authenticated user access
2. simple tenant-aware RBAC
3. PII detection and protection
4. Company Brain
5. permission-aware Secure RAG
6. Skills Engine
7. Unified Intelligence
8. AI tool calling
9. webhook-driven workflows
10. automated actions
11. human intervention / escalation
12. usage-based observability
13. service health monitoring
14. incident response
15. reproducible Docker-based development
16. CI validation
17. Local Docker-first deployment
18. AWS deployment after local validation

The technical implementation should prioritize:

- learning
- correctness
- security
- end-to-end integration
- demonstrability

over unnecessary infrastructure complexity.

---

# 3. Technical Stack

The following is the current proposed technical direction.

| Area | Technology / Direction | Reason |
|---|---|---|
| Language | Python 3.12 | All developers are Python developers and Python has a strong AI, API, data, and testing ecosystem. |
| Backend API | FastAPI | Lightweight Python API framework suitable for rapid development and async/webhook workloads. |
| Database | PostgreSQL | Provides reliable structured persistence for tenants, users, skills, incidents, audit records, and Company Brain metadata. |
| Vector Search | pgvector | Allows semantic retrieval while keeping vector storage close to PostgreSQL instead of introducing a separate vector database. |
| PII Protection | Microsoft Presidio | Open-source PII detection/anonymization tooling that integrates naturally with Python and can run locally or in Docker. |
| LLM Provider | OpenRouter | Provides configurable access to multiple models through a common API. |
| LLM Model | Configurable | Prevents the project from being tied to one model and allows model selection based on quality, availability, tool-calling support, and cost. |
| Embeddings | Configurable embedding model | Keeps semantic retrieval independent of one fixed embedding provider/model. |
| AI Tools | Tool-agnostic interfaces | Allows suitable open-source tools/frameworks to be integrated or replaced without changing the product-level architecture. |
| Webhooks | FastAPI HTTP endpoints | Provides a simple and locally testable mechanism for receiving external events. |
| Containers | Docker | Provides reproducible development and execution environments. |
| Local orchestration | Docker Compose | Allows the application and required local dependencies to run consistently. |
| Testing | Pytest | Standard Python testing framework suitable for unit and integration tests. |
| Formatting/Linting | Ruff | Fast Python linting and formatting with minimal configuration. |
| CI | GitHub Actions | Provides automated testing and validation for pull requests. |
| Cloud | AWS | Provides a practical cloud deployment target after local Docker validation. |

These are **implementation proposals for the current project scope**. Any technology that becomes architecture-significant should be confirmed through the appropriate engineering review/ADR process.

---

# 4. Architecture Principles

## 4.1 Logical Components Are Not Automatically Services

The conceptual architecture contains:

- PII Guard
- Company Brain
- Secure RAG
- Skills Engine
- Unified Intelligence
- AI Tools
- Webhooks
- Observability

These are logical product/technical components.

They do not automatically require:

- separate microservices
- separate containers
- separate databases
- separate repositories

The implementation should use the simplest structure that demonstrates the required behavior.

---

## 4.2 Unified Intelligence

Company Brain and AI Agent are not independent intelligence layers.

They form one **Unified Intelligence**.

The Unified Intelligence has different capabilities:

### Company Brain side

Responsible for:

- company knowledge
- procedures
- policies
- decisions
- previous incidents
- solutions
- relationships
- provenance
- operational context
- retrieved knowledge

### Agent side

Responsible for:

- reasoning
- deciding what information is needed
- selecting Skills
- deciding when a Tool is appropriate
- executing approved workflows
- handling failures
- requesting human intervention

The distinction is therefore about responsibility, not separate intelligence systems.

---

# 5. High-Level Technical Architecture

```text
                    ARC ENTERPRISE AI PLATFORM
                              |
             +----------------+----------------+
             |                |                |
        Multi-Tenant       Auth/RBAC       Connectors
             |                |                |
             +----------------+----------------+
                              |
                         PII GUARD
                              |
                              v
                    +-------------------+
                    | UNIFIED INTELLIGENCE|
                    |                   |
                    | Company Brain     |
                    | Secure RAG         |
                    | Skills             |
                    | Reasoning          |
                    | Agent Execution    |
                    +---------+---------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
               AI Tools             Webhooks
                    |                   |
                    +---------+---------+
                              |
                       Observability
                              |
                         Docker / AWS
```

The diagram represents logical responsibilities, not a mandatory deployment topology.

---

# 6. Runtime Boundaries

The minimum technical runtime should contain:

```text
Arc Application
    |
    +-- API
    +-- Auth / RBAC
    +-- Tenant Context
    +-- PII Guard
    +-- Company Brain
    +-- Secure RAG
    +-- Skills
    +-- Unified Intelligence
    +-- AI Tools
    +-- Webhooks
    +-- Observability
```

External dependencies may include:

```text
PostgreSQL + pgvector
OpenRouter / OmniRoute
External connector APIs
```

Only dependencies actually required by the implementation should be provisioned.

---

# 7. Multi-Tenancy and RBAC

Arc will simulate approximately:

- 3 tenants
- 3–5 users per tenant
- synthetic company data

Tenant isolation is primarily an application-level security requirement.

Every tenant-scoped operation must establish tenant context before accessing protected resources.

RBAC should distinguish at least:

### Platform Administrator

Responsibilities:

- manage tenants
- manage users
- configure platform-level settings

Access boundary:

- platform-level operations
- authorized tenant administration

### Tenant Administrator

Responsibilities:

- manage users within their tenant
- view tenant configuration
- manage tenant-level settings

Access boundary:

- own tenant only

### Employee / End User

Responsibilities:

- use permitted company knowledge
- request approved workflows
- interact with Unified Intelligence

Access boundary:

- own tenant
- permissions assigned to the user

### Operations / Service User

Responsibilities:

- monitor operational activity
- investigate incidents
- use authorized operational knowledge
- approve or intervene in relevant workflows

Access boundary:

- authorized tenant and operational resources

Exact role names and permissions remain governed by the PRD and implementation review.

---

# 8. Unified Intelligence

## 8.1 Definition

Unified Intelligence is the combined Company Brain + Agent capability of Arc.

It is a living intelligence system that:

1. receives company information
2. understands company context
3. retrieves relevant knowledge
4. identifies applicable procedures/Skills
5. reasons about the current request or event
6. selects approved actions
7. invokes permitted AI Tools
8. observes the result
9. escalates to a human when required

---

## 8.2 Company Brain Responsibilities

The Company Brain portion manages:

- knowledge
- procedures
- policies
- decisions
- incidents
- solutions
- relationships
- provenance
- operational context

It is not simply a vector database.

It combines structured company information with semantic retrieval.

---

## 8.3 Agent Responsibilities

The Agent portion provides:

- reasoning
- workflow selection
- Skill selection
- tool selection
- execution planning
- result interpretation
- failure handling
- escalation

The Agent must operate using Company Brain context for company-specific workflows.

---

## 8.4 Unified Intelligence Flow

```text
User / Event
     |
     v
Tenant + User Context
     |
     v
PII Guard
     |
     v
Unified Intelligence
     |
     +---- Company Brain
     |        |
     |        +-- Structured Knowledge
     |        +-- Semantic Retrieval
     |        +-- Procedures
     |        +-- Incidents
     |        +-- Provenance
     |
     +---- Skills
     |
     +---- Reasoning
     |
     +---- AI Tools
              |
              v
          Action / Result
              |
              +--> Success
              |
              +--> Retry / Recovery
              |
              +--> Human Escalation
```

---

# 9. Company Brain Technical Requirements

The Company Brain requires both structured and semantic information.

## 9.1 Structured Information

Examples:

- tenant
- user
- department
- policy
- procedure
- Skill
- incident
- incident resolution
- decision
- tool
- relationship
- source
- provenance
- version

Structured records provide deterministic information and relationships.

---

## 9.2 Semantic Information

Documents and knowledge can be represented through embeddings to support semantic retrieval.

Examples:

- company policies
- support procedures
- incident reports
- troubleshooting documents
- internal knowledge
- historical solutions

---

## 9.3 Company Brain Storage Model

The initial implementation should use a hybrid approach:

```text
Structured Data
       |
       v
PostgreSQL
       |
       +---- metadata
       +---- procedures
       +---- incidents
       +---- skills
       +---- provenance
       |
       +---- pgvector
              |
              +---- embeddings
              +---- semantic retrieval
```

The Company Brain must not be treated as only a vector store.

---

# 10. LLM Layer

## 10.1 Role

The LLM provides language understanding, reasoning, planning, and generation capabilities for Unified Intelligence.

The LLM may be used for:

- understanding user requests
- summarization
- reasoning over retrieved context
- Skill selection
- tool selection
- generating responses
- interpreting tool results

---

## 10.2 LLM Responsibilities

The LLM should:

1. receive authorized context
2. reason over that context
3. produce a response or structured decision
4. request approved tool calls where required
5. interpret tool results

---

## 10.3 LLM Security Boundary

The LLM is **not** the authorization system.

The application must enforce:

- tenant isolation
- authentication
- RBAC
- permission checks
- tool authorization
- data filtering

before information is passed to the LLM.

---

## 10.4 LLM Request Flow

```text
User Request
     |
     v
Authentication
     |
     v
Tenant / Permission Context
     |
     v
PII Guard
     |
     v
Secure Retrieval
     |
     v
Allowed Context
     |
     v
LLM
     |
     v
Response / Tool Request
```

---

# 11. Embeddings Layer

## 11.1 Purpose

Embeddings convert text into numerical vector representations.

They allow semantically similar knowledge to be retrieved even when the query does not use exactly the same words as the stored content.

---

## 11.2 Embedding Responsibilities

The embedding layer is responsible for:

- embedding company knowledge
- embedding queries
- storing vectors
- similarity retrieval

It is not responsible for:

- reasoning
- authorization
- tool execution
- final response generation

---

## 11.3 Retrieval Flow

```text
Knowledge
   |
   v
Chunking
   |
   v
Embedding Model
   |
   v
Vector
   |
   v
pgvector
```

For a query:

```text
User Query
   |
   v
Query Embedding
   |
   v
Similarity Search
   |
   v
Candidate Knowledge
   |
   v
Permission Filtering
   |
   v
Approved Context
```

---

## 11.4 Embeddings vs LLM

```text
Embeddings
    |
    +-- represent semantic meaning
    +-- enable similarity search
    +-- support retrieval

LLM
    |
    +-- understands language
    +-- reasons over context
    +-- generates responses
    +-- selects/requests tools
```

They work together but have different responsibilities.

---

# 12. Secure RAG

## 12.1 Purpose

Secure RAG allows Unified Intelligence to retrieve relevant company knowledge while enforcing tenant and permission boundaries.

---

## 12.2 Retrieval Flow

```text
User Query
     |
     v
Tenant Context
     |
     v
Permission Context
     |
     v
Query Embedding
     |
     v
Vector Retrieval
     |
     v
Candidate Documents
     |
     v
Permission / Tenant Filtering
     |
     v
Approved Context
     |
     v
LLM
```

---

## 12.3 Security Rules

The retrieval system must:

- enforce tenant context
- filter unauthorized information
- prevent cross-tenant retrieval
- avoid returning unauthorized documents
- provide only approved context to the LLM

The LLM must never be relied upon to perform authorization.

---

# 13. Skills Engine

## 13.1 Purpose

The Skills Engine converts company procedures and operational knowledge into structured, reusable workflows that Unified Intelligence can apply.

---

## 13.2 Skill Structure

A Skill should contain information such as:

- name
- purpose
- inputs
- preconditions
- steps
- constraints
- allowed tools
- approval requirements
- failure behavior
- expected output
- provenance
- version

Example:

```yaml
name: resolve_password_reset
purpose: Resolve a standard employee password reset request

preconditions:
  - user_identity_verified
  - account_is_active

steps:
  - check_account
  - reset_password
  - notify_user

allowed_tools:
  - identity_lookup
  - password_reset
  - notification

approval_required: false
```

The exact Skill representation can evolve as implementation proceeds.

---

# 14. AI Tools

AI Tools are controlled interfaces through which Unified Intelligence can interact with Arc or approved external systems.

Examples:

- ticket lookup
- incident lookup
- knowledge search
- notification
- account lookup
- controlled ticket update
- webhook action
- health check

---

## 14.1 Tool Execution Flow

```text
Unified Intelligence
       |
       v
Tool Selection
       |
       v
Authorization Check
       |
       v
Tool Input Validation
       |
       v
Tool Execution
       |
       v
Tool Result
       |
       v
Unified Intelligence
```

---

## 14.2 Tool Security

Tools must:

- validate inputs
- enforce authorization
- enforce tenant context
- expose only approved operations
- avoid exposing secrets
- produce observable execution records

The LLM must not be allowed to execute arbitrary Python code or arbitrary system commands.

---

## 14.3 Tool Framework

Arc remains tool/framework agnostic at the product architecture level.

Suitable open-source AI libraries/frameworks may be used where they provide real value.

A framework can be replaced without changing the concept of AI Tools.

---

# 15. PII Guard

## 15.1 Technology

Arc will use **Microsoft Presidio** for the initial PII protection layer.

Presidio is an open-source framework for detecting, analyzing, and anonymizing sensitive information.

---

## 15.2 Components

The primary workflow uses:

- Presidio Analyzer
- Presidio Anonymizer

The Analyzer identifies PII entities.

The Anonymizer applies configured de-identification operations such as:

- redaction
- replacement
- masking
- hashing
- encryption

---

## 15.3 Arc PII Flow

```text
Input
  |
  v
Presidio Analyzer
  |
  v
Detected PII
  |
  v
Presidio Anonymizer
  |
  v
Sanitized Content
  |
  v
Company Brain / RAG / LLM
```

---

## 15.4 PII Boundary

PII Guard should be applied before sensitive information crosses defined AI/data boundaries.

The first implementation should focus on practical text PII protection.

Image PII redaction is not required merely because the technology can support it.

---

## 15.5 PII Limitations

Presidio uses automated detection and cannot guarantee detection of every sensitive value.

Presidio is not a complete security boundary.

Arc must continue to enforce:

- authorization
- tenant isolation
- access control
- data minimization
- secure logging

---

# 16. Webhooks

## 16.1 Purpose

Webhooks allow external or simulated systems to send events into Arc.

---

## 16.2 Initial Implementation

The first implementation should use simple HTTP webhook endpoints.

External systems may be represented by:

- controlled APIs
- local event generators
- approved free external services

No unnecessary event infrastructure should be introduced.

---

## 16.3 Webhook Flow

```text
External System
      |
      v
Webhook Endpoint
      |
      v
Validate Event
      |
      v
Resolve Tenant
      |
      v
PII Protection if required
      |
      v
Process Event
      |
      v
Unified Intelligence
      |
      +---- Skill
      +---- AI Tool
      +---- Incident
      +---- Human Escalation
```

---

## 16.4 Webhook Requirements

The system must define behavior for:

- valid events
- invalid events
- duplicate events
- processing failures
- retries
- downstream failures

Webhook payloads must not unnecessarily expose sensitive information in logs.

---

# 17. Observability

Arc requires usage-based and operational observability.

The project specifically focuses on:

- API request count
- AI request count
- token usage
- agent/Unified Intelligence execution count
- tool invocation count
- webhook event count
- successful/failed executions
- latency
- error rate
- tenant usage
- service health
- incident count
- automated action count
- human escalation count

---

## 17.1 Health Monitoring

Health monitoring should expose whether important Arc components are functioning.

Examples:

```text
Application Health
Database Health
AI Provider Health
Webhook Health
RAG Health
Tool Health
```

The implementation should use the simplest practical mechanism.

---

## 17.2 Incident Response

Important failures should be observable and capable of creating or contributing to an incident.

Example:

```text
AI Provider Failure
      |
      v
Error Detected
      |
      v
Health Degraded
      |
      v
Incident
      |
      v
Investigation
      |
      v
Resolution / Human Action
```

---

## 17.3 Agent-Driven Actions

Unified Intelligence may initiate approved automated actions when:

- the Skill allows the action
- the Tool is authorized
- required conditions are satisfied
- the action does not require human approval

For higher-risk actions:

```text
Unified Intelligence
       |
       v
Human Approval Required
       |
       v
Human Decision
       |
       +---- Approve → Tool
       |
       +---- Reject → Stop / Escalate
```

---

# 18. Authentication

Enterprise SSO is **out of scope**.

The project will use a simple user identity model suitable for approximately:

- 3 simulated tenants
- 3–5 users per tenant
- synthetic data

The exact authentication implementation must remain consistent with the approved PRD and engineering decision.

Authentication establishes identity.

Authorization determines what the identity can access.

---

# 19. Authorization

Authorization must be enforced by the application.

The application must consider:

- authenticated user
- tenant
- role
- permissions
- resource ownership

Authorization must not be delegated to:

- the LLM
- embeddings
- the vector store
- an external AI provider

---

# 20. Data Protection

Arc must protect:

- credentials
- API keys
- PII
- customer data
- tenant-scoped information
- tool execution data

Secrets must not be committed to Git.

Development should use `.env.example` for variable documentation and local environment configuration.

---

# 21. Environment Variables

Current expected configuration includes:

```text
APP_ENV
DATABASE_URL
OPENROUTER_API_KEY
OMNIROUTE_BASE_URL
```

### APP_ENV

Used to distinguish the development/runtime environment.

### DATABASE_URL

Used to configure database connectivity.

### OPENROUTER_API_KEY

Used for the configurable LLM provider path.

The real secret must never be committed.

### OMNIROUTE_BASE_URL

Used when the project uses OmniRoute as the configurable AI routing layer.

The exact use of OmniRoute should remain implementation-configurable.

---

# 22. Docker Development

Arc is **Local Docker-first**.

The local environment should allow a developer to start the project using documented commands.

The environment should provide:

- Python runtime
- application dependencies
- required local persistence
- AI configuration
- testing tools
- reproducible configuration

Docker Compose should be used where multiple local dependencies are actually required.

The project should not create unnecessary containers for conceptual components.

---

# 23. CI

CI should validate every relevant pull request.

Minimum CI checks:

```text
Install dependencies
      |
      v
Lint / Format Check
      |
      v
Unit Tests
      |
      v
Integration Tests where applicable
      |
      v
Docker Build
```

CI should not require expensive cloud infrastructure merely to validate the project.

---

# 24. AWS Deployment

After the local Docker workflow is stable and validated, Arc should be deployable to AWS.

The AWS deployment should reuse the containerized application rather than creating a completely different architecture.

The exact AWS service mapping remains a platform/implementation decision.

The AWS target should not block local development.

The project does not require a complex multi-region or enterprise production deployment.

---

# 25. Testing Requirements

Testing should focus on the highest-risk behavior.

## Required Testing Areas

### Tenant Isolation

Test:

- Tenant A can access Tenant A data.
- Tenant A cannot access Tenant B data.

### RBAC

Test:

- authorized operation succeeds
- unauthorized operation fails

### PII

Test:

- defined PII is detected
- configured redaction occurs
- safe content remains usable

### Secure RAG

Test:

- authorized knowledge is retrieved
- unauthorized knowledge is filtered
- cross-tenant retrieval fails

### Skills

Test:

- valid Skill executes
- invalid preconditions prevent execution
- unauthorized tools cannot be called

### AI Tools

Test:

- authorized tool execution
- invalid inputs
- unauthorized tool execution

### Webhooks

Test:

- valid event
- invalid event
- duplicate event
- processing failure

### Unified Intelligence

Test:

- retrieval
- Skill selection
- tool selection
- successful execution
- failure handling
- human escalation

---

# 26. Error Handling

The system must define safe behavior for:

- LLM provider failure
- embedding failure
- retrieval failure
- database failure
- webhook failure
- tool failure
- Skill failure
- invalid input
- unauthorized operation
- human approval timeout

The system should fail safely rather than inventing successful results.

---

# 27. Security Boundaries

The following boundaries are mandatory:

```text
User
  |
Authentication
  |
Authorization
  |
Tenant Context
  |
PII Guard
  |
Secure Retrieval
  |
LLM
  |
Tool Authorization
  |
External Action
```

The LLM must never bypass:

- authentication
- authorization
- tenant isolation
- tool authorization
- human approval requirements

---

# 28. Logging

Logs should support debugging and operational investigation.

Useful information includes:

- request identifier
- tenant context where safe
- event type
- operation
- execution status
- latency
- error category

Logs must not unnecessarily contain:

- API keys
- passwords
- access tokens
- raw PII
- confidential customer content

---

# 29. Project Constraints

The technical implementation must respect:

1. 7-day implementation window
2. placement-oriented objective
3. Python-first team
4. synthetic tenants and data
5. local Docker-first development
6. AWS deployment after local validation
7. AI-focused learning
8. simple supporting infrastructure
9. no unnecessary microservices
10. no unnecessary enterprise infrastructure
11. open-source AI tooling where useful
12. configurable AI model/provider

---

# 30. Deployment Strategy

## 30.1 Local Docker-First

The first target is:

```text
Developer
   |
   v
Docker Compose
   |
   +-- Arc Application
   +-- PostgreSQL / pgvector
   +-- Required local dependencies
   |
   v
Working Local System
```

The local environment must be reproducible by the team.

---

## 30.2 AWS

After local validation:

```text
Dockerized Arc
     |
     v
AWS
     |
     v
Deployed Demonstration
```

The exact AWS service selection is not prescribed by this TRD.

---

# 31. Performance

Because this is a 7-day placement project, performance targets should focus on measurable behavior rather than production-scale capacity.

Measure:

- API latency
- retrieval latency
- embedding latency
- LLM latency
- tool execution latency
- webhook processing latency
- end-to-end workflow latency

Exact numerical targets may be established during implementation if useful.

---

# 32. Scalability

The project does not require production-scale horizontal scaling.

The implementation should nevertheless avoid unnecessary architectural choices that make future scaling impossible.

The design should be understandable enough that a developer can explain how:

- tenants
- users
- knowledge
- events
- AI requests

could grow later.

---

# 33. External Integrations

The project may use approximately 2–3 useful real connectors where they are:

- free
- easy to integrate
- useful for demonstrating the product

Controlled/fake APIs are acceptable where real integrations introduce unnecessary complexity or cost.

Connector selection remains an implementation planning decision and should not dictate unnecessary platform infrastructure.

---

# 34. AI Provider and Model Strategy

OpenRouter is the primary configurable AI provider.

The model must remain configurable.

The project should support changing the model without changing the product architecture.

OmniRoute may be used as an AI routing layer where appropriate.

The system should not assume that one model is permanently required.

Model selection should consider:

- tool-calling support
- reasoning quality
- latency
- availability
- cost
- context window
- reliability

---

# 35. AI Tooling Strategy

The AI Tool layer remains framework/tool agnostic.

The team may use suitable open-source libraries/frameworks where they provide clear value.

The selection should be based on:

- ease of learning
- compatibility with Python
- tool-calling support
- maintainability
- ability to replace the library later
- suitability for the 7-day project

The framework must not become more important than understanding the underlying agent/tool architecture.

---

# 36. Technical Decision Boundaries

The following should not be silently decided by implementation:

- replacing the Unified Intelligence model
- changing the Company Brain concept
- changing the Secure RAG security boundary
- changing the AI provider strategy
- introducing major infrastructure
- introducing a new service architecture
- changing tenant isolation behavior
- changing authentication scope
- changing deployment scope

Architecture-significant decisions should be recorded through ADRs when appropriate.

---

# 37. Deferred / Open Technical Decisions

The following may remain open until implementation review:

- exact backend package structure
- exact AI agent framework
- exact embedding model
- exact AI Tool framework
- exact external connectors
- exact AWS service mapping
- exact observability implementation
- exact webhook retry strategy
- exact database schema
- exact Skill serialization format
- exact human approval implementation

An open decision must not be treated as an implementation omission.

---

# 38. Recommended Initial Implementation Order

```text
1. Project / Docker environment
        |
        v
2. FastAPI application
        |
        v
3. PostgreSQL + pgvector
        |
        v
4. Simple authentication + tenant/RBAC
        |
        v
5. PII Guard
        |
        v
6. Company Brain data model
        |
        v
7. Embedding + Secure RAG
        |
        v
8. Skills
        |
        v
9. Unified Intelligence
        |
        v
10. AI Tools
        |
        v
11. Webhooks
        |
        v
12. Observability
        |
        v
13. Automated actions + human escalation
        |
        v
14. Tests
        |
        v
15. CI
        |
        v
16. Local Docker demonstration
        |
        v
17. AWS deployment
```

This ordering is intended to support the 7-day implementation and learning objective.

---

# 39. Minimum End-to-End Demonstration

The final demonstration should show a connected workflow similar to:

```text
Employee raises a request
        |
        v
Authentication
        |
        v
Tenant / Permission Context
        |
        v
PII Guard
        |
        v
Unified Intelligence
        |
        +---- Company Brain
        |        |
        |        v
        |    Secure RAG
        |
        +---- Skill Selection
        |
        +---- Reasoning
        |
        v
Approved AI Tool
        |
        v
External / Internal Action
        |
        v
Result
        |
        +---- Success
        |
        +---- Incident
        |
        +---- Human Escalation
        |
        v
Observability
```

This is the primary end-to-end technical proof of the project.

---

# 40. Technical Quality Bar

The implementation should demonstrate:

### Correctness

Requirements work as documented.

### Security

Tenant boundaries, authorization, PII controls, and tool permissions are enforced.

### AI Safety

The LLM cannot bypass authorization or tenant boundaries.

### Reliability

Failures are handled and observable.

### Observability

AI and operational behavior can be measured.

### Reproducibility

Another developer can run the system locally using the documented Docker workflow.

### Maintainability

Another developer can understand the major components and workflows.

### Explainability

Each team member should be able to explain:

- why the component exists
- how it works
- what data it receives
- what it produces
- how it fails
- how security is enforced

---

# 41. Final Technical Requirements

The completed system should demonstrate the following connected architecture:

```text
                 ARC ENTERPRISE AI PLATFORM
                            |
       +--------------------+--------------------+
       |                    |                    |
   Tenant/RBAC          PII Guard            Webhooks
       |                    |                    |
       +--------------------+--------------------+
                            |
                            v
                 +----------------------+
                 | UNIFIED INTELLIGENCE |
                 |                      |
                 | Company Brain        |
                 | Secure RAG           |
                 | Skills               |
                 | Reasoning / Agent    |
                 +----------+-----------+
                            |
                            v
                       AI Tools
                            |
                            v
                    Controlled Actions
                            |
                 +----------+----------+
                 |                     |
            Automated Action       Human Escalation
                 |                     |
                 +----------+----------+
                            |
                            v
                      Observability
                            |
                       Docker / AWS
```

The project should remain a single understandable system rather than becoming an unnecessarily distributed enterprise architecture.

---

# 42. TRD Acceptance Criteria

The TRD is ready for implementation when:

- Python 3.12 is defined.
- Proposed technologies have reasons.
- Local Docker-first deployment is defined.
- AWS deployment follows local validation.
- Company Brain and Agent are represented as Unified Intelligence.
- LLM responsibilities are defined.
- Embedding responsibilities are defined.
- LLM and embeddings interaction is defined.
- Secure RAG authorization boundaries are defined.
- Skills responsibilities are defined.
- AI Tools are controlled and tool/framework agnostic.
- Microsoft Presidio is identified for the initial PII layer.
- Webhooks are defined.
- Observability requirements are defined.
- Health monitoring is defined.
- Incident response is defined.
- Automated actions and human escalation are defined.
- Tenant/RBAC boundaries are defined.
- Testing requirements are defined.
- CI requirements are defined.
- AWS deployment does not block local development.
- Unresolved architecture decisions are explicitly identified.
- The technical architecture remains proportional to the 7-day project.

---

# 43. Relationship to PRD

The PRD remains the product source of truth.

The TRD translates the approved product requirements into a practical technical direction.

```text
PRD
 |
 | What / Why
 v
TRD
 |
 | How / Technical Direction
 v
ADR
 |
 | Architecture Decision
 v
Implementation
 |
 v
Tests / CI
```

If a technical implementation requires changing a product requirement, the PRD must be reviewed rather than silently changed through implementation.

---

# 44. Document Status

**Status:** Revised — PR Review Changes Incorporated

**Primary Development Language:** Python 3.12

**Deployment:** Local Docker-first → AWS

**AI Provider:** OpenRouter

**Model:** Configurable

**PII Technology:** Microsoft Presidio

**Core Intelligence Model:** Unified Intelligence

**Primary AI Focus:**

- Company Brain
- Secure RAG
- Skills
- AI Agent capabilities
- AI Tools
- PII protection
- Webhooks
- Observability
- Automated actions
- Human intervention

**Next Step:**

Bala and the engineering team review the technical direction and identify any architecture decisions that require ADRs before implementation.
