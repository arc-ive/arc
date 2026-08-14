# Arc --- Technical Requirements Document (TRD)

**Project:** Arc\
**Purpose:** Placement-focused enterprise AI engineering project\
**Domain:** IT Services\
**Implementation:** Python-first\
**Deployment:** Local Docker\
**Team:** Python developers\
**Status:** Draft --- Technical Stack Proposal

------------------------------------------------------------------------

# 1. Purpose

This document translates the Arc PRD into a practical technical stack
and implementation boundary.

The TRD defines:

-   technology choices
-   application layers
-   AI stack
-   data stack
-   authentication
-   connectors
-   webhooks
-   observability
-   Docker environment
-   testing
-   development tooling
-   technical boundaries

The TRD does **not** redefine the product requirements.

The PRD remains the source of truth for what Arc should do.

------------------------------------------------------------------------

# 2. Technical Goals

The technical implementation must:

1.  Be understandable by Python developers.
2.  Be achievable within the 7-day project window.
3.  Run locally through Docker.
4.  Keep the AI components as the primary technical focus.
5.  Avoid unnecessary enterprise infrastructure.
6.  Keep components modular enough to demonstrate production-style
    engineering.
7.  Make tenant isolation and AI authorization testable.
8.  Make Agent behavior observable.
9.  Allow the team to explain every major technology used.

------------------------------------------------------------------------

# 3. Proposed Technology Stack

  -----------------------------------------------------------------------
  Area                                Technology
  ----------------------------------- -----------------------------------
  Backend API                         Python + FastAPI

  Frontend                            Next.js / React

  Primary Database                    PostgreSQL

  Vector Search                       pgvector

  ORM                                 SQLAlchemy

  Database Migrations                 Alembic

  Authentication                      Google OAuth

  Authorization                       Application-level RBAC

  AI Provider Interface               OpenRouter-compatible API

  LLM                                 Provider/model selected during
                                      implementation

  Embeddings                          Sentence Transformers or provider
                                      embeddings

  RAG                                 Custom Python retrieval pipeline

  Agent                               LangGraph or lightweight custom
                                      agent orchestration

  Skills                              Python-based Skill definitions

  PII                                 Microsoft Presidio

  Webhooks                            FastAPI

  Connectors                          Python API clients / official SDKs

  Background Tasks                    FastAPI background tasks initially;
                                      worker/queue only if required

  Cache                               Deferred

  Message Broker                      Deferred

  Object Storage                      Deferred

  Observability                       Application logs + metrics + Agent
                                      execution records

  Metrics                             Prometheus-compatible metrics where
                                      useful

  Dashboard                           Simple application dashboard
                                      initially

  Testing                             pytest

  API Testing                         httpx / FastAPI TestClient

  Frontend Testing                    Playwright if required

  Containers                          Docker

  Local Orchestration                 Docker Compose

  CI                                  GitHub Actions

  Dependency Management               `uv` or pip/requirements

  Code Quality                        Ruff

  Type Checking                       mypy

  Formatting                          Ruff formatter

  Environment Variables               `.env` / `.env.example`
  -----------------------------------------------------------------------

These choices are implementation defaults and may be adjusted if the
team identifies a simpler or better option during implementation.

------------------------------------------------------------------------

# 4. Python-First Architecture

Arc should use Python for the majority of backend and AI implementation.

Recommended structure:

``` text
Frontend
   ↓
FastAPI
   ↓
Application Services
   ├── Auth / RBAC
   ├── Tenant Context
   ├── Company Brain
   ├── Secure RAG
   ├── Skills Engine
   ├── AI Agent
   ├── AI Tools
   ├── PII Guard
   ├── Connectors
   ├── Webhooks
   └── Observability
   ↓
PostgreSQL + pgvector
```

The system does not require a separate microservice for every component.

------------------------------------------------------------------------

# 5. Backend

## 5.1 FastAPI

FastAPI will provide:

-   REST APIs
-   authentication endpoints/callbacks
-   tenant-scoped APIs
-   Company Brain APIs
-   RAG APIs
-   Skill APIs
-   Agent APIs
-   Tool APIs
-   webhook endpoints
-   health endpoints
-   observability endpoints

Example structure:

``` text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── brain/
│   ├── rag/
│   ├── skills/
│   ├── agent/
│   ├── tools/
│   ├── pii/
│   ├── connectors/
│   ├── webhooks/
│   └── observability/
└── tests/
```

------------------------------------------------------------------------

# 6. Database

## PostgreSQL

PostgreSQL is the proposed primary database.

It should store structured Arc information such as:

-   tenants
-   users
-   roles
-   permissions
-   documents
-   knowledge records
-   procedures
-   policies
-   incidents
-   solutions
-   decisions
-   Skills
-   Skill executions
-   Agent runs
-   Tool executions
-   webhook events
-   connector records
-   usage records
-   audit records

------------------------------------------------------------------------

# 7. Vector Search

## pgvector

The first vector-search implementation should use PostgreSQL + pgvector
rather than introducing a separate vector database.

Reason:

``` text
Structured Data
      +
Vector Data
      ↓
One PostgreSQL system
```

This reduces infrastructure and makes the 7-day project easier to
understand.

The team can store:

-   document chunks
-   embeddings
-   metadata
-   tenant ID
-   permission metadata
-   source information

The vector store must not be treated as the authorization system.

Authorization must be checked using application/domain rules.

------------------------------------------------------------------------

# 8. Company Brain Technical Model

The Company Brain should not simply be:

``` text
Documents → Embeddings → Chatbot
```

It should combine structured records and searchable knowledge.

Conceptual model:

``` text
Company Brain
│
├── Knowledge
├── Procedures
├── Policies
├── Incidents
├── Solutions
├── Decisions
├── Relationships
└── Provenance
```

Each knowledge object should have appropriate metadata such as:

``` text
id
tenant_id
type
title
content
source
created_at
updated_at
access metadata
```

Searchable content may additionally contain:

``` text
embedding
chunk metadata
```

------------------------------------------------------------------------

# 9. Secure RAG Architecture

RAG flow:

``` text
User / Agent
      ↓
Authenticate
      ↓
Resolve Tenant
      ↓
Resolve User Permissions
      ↓
Create Query
      ↓
Vector / Keyword Retrieval
      ↓
Metadata Filtering
      ↓
Authorization Filtering
      ↓
Approved Context
      ↓
LLM
      ↓
Response
```

Critical rule:

> Retrieval must never bypass authorization.

The vector database should not be trusted to determine the final
authorization decision by itself.

------------------------------------------------------------------------

# 10. Embeddings

The embedding layer should be abstracted behind an interface.

Example:

``` python
class EmbeddingProvider:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

This allows the team to change embedding providers without rewriting
RAG.

Preferred implementation:

-   free/local embedding model where practical
-   provider embeddings if simpler and affordable

The exact model is an implementation decision.

------------------------------------------------------------------------

# 11. LLM Layer

The application should avoid directly coupling business logic to a
specific model.

Conceptual interface:

``` python
class LLMProvider:
    def generate(self, messages):
        ...

    def generate_with_tools(self, messages, tools):
        ...
```

Possible provider route:

``` text
Arc
 ↓
LLM Interface
 ↓
OpenRouter
 ↓
Selected Model
```

OpenRouter may be used because the project already anticipates an
`OPENROUTER_API_KEY` and it allows model/provider flexibility.

The actual model should be selected based on:

-   availability
-   cost
-   tool-calling support
-   response quality
-   latency

------------------------------------------------------------------------

# 12. AI Agent

The Agent is the orchestration layer.

Technical responsibilities:

-   understand incoming task
-   retrieve context
-   select Skill
-   plan execution
-   select Tools
-   call Tools
-   inspect Tool results
-   continue or stop
-   request human approval
-   record execution

Conceptual flow:

``` text
Trigger
  ↓
Agent
  ↓
Company Brain / RAG
  ↓
Skill Selection
  ↓
Plan
  ↓
Tool Call
  ↓
Tool Result
  ↓
Reason
  ↓
Next Tool / Finish / Escalate
```

------------------------------------------------------------------------

# 13. Agent Framework

A framework may be used for orchestration if it reduces implementation
complexity.

Candidate:

**LangGraph**

Alternative:

**Custom Python Agent Loop**

The team should choose one.

The project should not introduce multiple agent frameworks.

### Selection Rule

Use LangGraph if:

-   stateful workflows are useful
-   graph execution is easy to explain
-   it accelerates the implementation

Use a custom Python loop if:

-   the workflow is simple
-   the team understands it better
-   framework overhead is unnecessary

The choice should be recorded as an implementation decision.

------------------------------------------------------------------------

# 14. Skills Engine

Skills are structured executable procedures.

Example:

``` text
Skill:
Payment API Recovery

Allowed Tools:
- get_service_health
- get_service_logs
- get_recent_incidents
- restart_service

Steps:
1. Check health.
2. Inspect logs.
3. Check recent incidents.
4. Restart if policy allows.
5. Verify health.
6. Update incident.
```

Technical representation may contain:

``` text
id
tenant_id
name
description
steps
allowed_tools
risk_level
requires_approval
status
version
created_by
```

Possible states:

``` text
DRAFT
PENDING_REVIEW
APPROVED
DISABLED
```

Only approved Skills should be executable by the Agent.

------------------------------------------------------------------------

# 15. AI Tools

Tools are controlled Python functions exposed to the Agent.

Example:

``` python
@tool
def get_service_health(service_name: str):
    ...
```

Tool metadata should define:

``` text
name
description
input schema
output schema
permission
risk level
requires approval
```

Example:

``` text
get_service_health
Risk: LOW
Approval: NO
```

``` text
restart_service
Risk: MEDIUM
Approval: POLICY
```

The Agent must not receive arbitrary Python execution.

------------------------------------------------------------------------

# 16. Human Approval

Sensitive Agent actions should support approval.

Flow:

``` text
Agent
 ↓
Tool requested
 ↓
Risk evaluation
 ↓
Approval required?
 ├── No → Execute
 └── Yes
       ↓
 Human approval
       ↓
 Approve / Reject
       ↓
 Execute / Stop
```

The first implementation can use a simple database-backed approval
record and UI/API action.

------------------------------------------------------------------------

# 17. PII Guard

Recommended tool:

**Microsoft Presidio**

Potential flow:

``` text
Incoming Data
     ↓
Presidio Analyzer
     ↓
Detected Entities
     ↓
Anonymizer / Redactor
     ↓
Safe Data
```

Initial entities can include:

-   email
-   phone number
-   person names where practical

The PII layer should be implemented as a reusable Python service/module
rather than scattered across every feature.

------------------------------------------------------------------------

# 18. Connectors

Connectors should be Python modules with a common interface.

Example:

``` python
class Connector:
    def authenticate(self):
        ...

    def fetch(self):
        ...

    def normalize(self, data):
        ...

    def health(self):
        ...
```

Potential real connectors:

-   GitHub
-   Google Drive
-   another free/easy source selected during implementation

Connector selection remains implementation-driven.

A controlled fake API is acceptable when a real connector would consume
too much of the 7-day schedule.

------------------------------------------------------------------------

# 19. Webhooks

FastAPI will provide webhook endpoints.

Example:

``` text
POST /api/v1/webhooks/events
```

Flow:

``` text
External System
      ↓
FastAPI Webhook
      ↓
Validate
      ↓
Resolve Tenant
      ↓
PII Guard
      ↓
Store Event
      ↓
Trigger Workflow
```

Webhook records should include:

``` text
event_id
tenant_id
source
event_type
payload/reference
received_at
status
processing_attempts
correlation_id
```

The first implementation does not require Kafka or another message
broker unless the actual workflow demonstrates a need for it.

------------------------------------------------------------------------

# 20. Background Processing

Start simple.

Possible first implementation:

``` text
FastAPI
  ↓
Background Task
```

If an actual workload requires durable asynchronous processing,
evaluate:

-   Celery
-   Dramatiq
-   RQ
-   a lightweight queue

Do not introduce a queue merely because an enterprise architecture
diagram contains asynchronous processing.

------------------------------------------------------------------------

# 21. Observability

The first implementation should record structured application events.

Important events:

``` text
AgentStarted
AgentFinished
SkillSelected
SkillExecutionStarted
ToolCalled
ToolFinished
WebhookReceived
RAGQuery
RAGRetrieved
PIIRedacted
IncidentCreated
IncidentResolved
HumanApprovalRequested
HumanApprovalCompleted
```

Agent execution should be traceable through:

``` text
agent_run_id
tenant_id
user_id
trigger
skill_id
tool_calls
result
status
duration
```

------------------------------------------------------------------------

# 22. Usage Monitoring

Usage records should be stored in PostgreSQL.

Example:

``` text
tenant_id
event_type
quantity
timestamp
metadata
```

Track:

-   RAG requests
-   Agent runs
-   Tool executions
-   webhook events
-   connector operations
-   AI requests

A simple dashboard is sufficient.

No billing system is required.

------------------------------------------------------------------------

# 23. Health Monitoring

Health endpoints should exist for important components.

Example:

``` text
GET /health
GET /health/ready
```

Potential checks:

-   API
-   PostgreSQL
-   vector search
-   AI provider
-   connector status
-   webhook processing

The UI can expose a simple health dashboard.

------------------------------------------------------------------------

# 24. Incident Response

Incidents should be stored as structured records.

Example:

``` text
id
tenant_id
title
severity
status
source
assigned_to
created_at
resolved_at
```

Basic states:

``` text
OPEN
INVESTIGATING
RESOLVED
CLOSED
```

Agent workflows may:

-   investigate
-   gather health
-   gather logs
-   retrieve previous solutions
-   execute approved recovery Skills
-   resolve
-   escalate

------------------------------------------------------------------------

# 25. Authentication

Use Google OAuth.

The system should establish:

``` text
Google Identity
      ↓
Arc User
      ↓
Tenant Membership
      ↓
Role
      ↓
Permissions
```

No enterprise SSO/SAML/SCIM is required.

------------------------------------------------------------------------

# 26. Authorization

Authorization should be enforced in the backend.

A request should effectively be evaluated against:

``` text
User
+
Tenant
+
Role
+
Permission
+
Resource
```

Example:

``` python
authorize(
    user=user,
    tenant=tenant,
    permission="incident.update",
    resource=incident,
)
```

Authorization must not depend only on frontend checks.

------------------------------------------------------------------------

# 27. Frontend

The frontend exists primarily to demonstrate the system.

Recommended:

**Next.js + React**

Main screens:

``` text
Login
Dashboard
Company Brain
Knowledge Search
Skills
Agent Runs
Incidents
Health
Usage
Connectors
Tenant / Users
```

The frontend should remain simple.

The AI/backend behavior is the priority.

------------------------------------------------------------------------

# 28. API Structure

Recommended API grouping:

``` text
/api/v1/auth
/api/v1/tenants
/api/v1/users
/api/v1/brain
/api/v1/rag
/api/v1/skills
/api/v1/agent
/api/v1/tools
/api/v1/connectors
/api/v1/webhooks
/api/v1/incidents
/api/v1/health
/api/v1/usage
```

Exact endpoints can be finalized during implementation.

------------------------------------------------------------------------

# 29. Docker

The project should run locally using Docker Compose.

Conceptual environment:

``` text
Docker Compose
│
├── backend
├── frontend
└── postgres
```

Additional containers should be added only when required.

Possible future additions:

``` text
redis
prometheus
grafana
```

These are not mandatory at the beginning.

------------------------------------------------------------------------

# 30. Environment Variables

Example:

``` env
APP_ENV=development

DATABASE_URL=postgresql://...

OPENROUTER_API_KEY=

OMNIROUTE_BASE_URL=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=

SECRET_KEY=
```

Rules:

-   `.env` is local only.
-   `.env` must not be committed.
-   `.env.example` contains placeholders only.
-   Secrets must not appear in source code.
-   Production secrets are outside the scope of this local project.

`OPENROUTER_API_KEY` is relevant once the LLM workflow is implemented.

`DATABASE_URL` becomes relevant once PostgreSQL is introduced.

`OMNIROUTE_BASE_URL` should remain only if the project actually uses
OmniRoute.

------------------------------------------------------------------------

# 31. Testing

## Framework

Use:

``` text
pytest
```

Important test categories:

### Unit Tests

-   PII detection
-   Skill parsing
-   permission checks
-   Tool validation
-   data transformations

### Integration Tests

-   database
-   RAG
-   connectors
-   webhook processing
-   Agent + Tools

### Security Tests

-   cross-tenant access
-   unauthorized role
-   unauthorized knowledge retrieval
-   unauthorized Tool execution

### End-to-End Test

``` text
Webhook
 ↓
PII
 ↓
Company Brain
 ↓
RAG
 ↓
Skill
 ↓
Agent
 ↓
Tool
 ↓
Incident
 ↓
Observability
```

------------------------------------------------------------------------

# 32. Code Quality

Recommended tooling:

``` text
Ruff
mypy
pytest
pre-commit
```

Ruff should handle:

-   linting
-   formatting

The project should avoid excessive tooling.

------------------------------------------------------------------------

# 33. Repository Structure

Recommended:

``` text
arc/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── brain/
│   │   ├── rag/
│   │   ├── skills/
│   │   ├── agent/
│   │   ├── tools/
│   │   ├── pii/
│   │   ├── connectors/
│   │   ├── webhooks/
│   │   └── observability/
│   └── tests/
│
├── frontend/
│
├── docs/
│   ├── requirements/
│   │   ├── PRD.md
│   │   └── TRD.md
│   ├── architecture/
│   └── learning/
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

------------------------------------------------------------------------

# 34. Technical Dependency Strategy

## Required Now

For the first meaningful implementation:

-   Python
-   FastAPI
-   PostgreSQL
-   pgvector
-   Google authentication
-   Docker
-   pytest

AI implementation additionally requires:

-   LLM provider
-   embedding provider
-   PII implementation
-   Agent orchestration
-   RAG implementation

## Potentially Later

-   Redis
-   background worker
-   Prometheus
-   Grafana
-   object storage
-   message broker

## Not Justified Initially

-   Kafka
-   Kubernetes
-   multiple databases
-   multiple vector databases
-   service mesh
-   cloud infrastructure
-   complex event buses

------------------------------------------------------------------------

# 35. Technical Decisions That Must Not Be Prematurely Locked

The following should remain flexible until implementation requires them:

-   exact LLM
-   exact embedding model
-   LangGraph vs custom Agent loop
-   exact connector list
-   background worker
-   Redis
-   Prometheus/Grafana
-   object storage
-   message broker

The team should prefer simple choices that can be explained clearly.

------------------------------------------------------------------------

# 36. Seven-Day Technical Execution

## Day 1

``` text
FastAPI
PostgreSQL
Docker
Google Auth
Tenant/RBAC
```

## Day 2

``` text
Company Brain
PII Guard
Knowledge ingestion
```

## Day 3

``` text
pgvector
Embeddings
Secure RAG
```

## Day 4

``` text
Skills
Agent
Tools
Approval
```

## Day 5

``` text
Webhooks
Incidents
Health
Agent actions
```

## Day 6

``` text
Connectors
Usage
Observability
```

## Day 7

``` text
Integration
Testing
Security tests
Docker validation
Documentation
Demo
```

------------------------------------------------------------------------

# 37. Golden Technical Flow

The implementation should prove this flow:

``` text
External Monitoring Event
          ↓
      Webhook API
          ↓
      Tenant Resolve
          ↓
       PII Guard
          ↓
     Company Brain
          ↓
      Secure RAG
          ↓
     Skill Selection
          ↓
       AI Agent
          ↓
       AI Tool
          ↓
     Service Action
          ↓
     Health Check
          ↓
      Incident
          ↓
   Agent Resolution
          ↓
     Observability
          ↓
    Company Brain
```

------------------------------------------------------------------------

# 38. Technical Acceptance Criteria

The technical implementation is acceptable when:

-   the system starts through Docker
-   backend starts successfully
-   frontend starts successfully
-   PostgreSQL starts successfully
-   migrations can run
-   Google authentication works
-   tenant context works
-   RBAC works
-   Company Brain stores knowledge
-   PII Guard processes data
-   pgvector retrieval works
-   RAG respects tenant/permission boundaries
-   Skills can be represented and approved
-   Agent can execute approved Skills
-   Agent can call Tools
-   Tool permissions work
-   webhook events are accepted
-   webhook events can trigger Agent workflows
-   incidents can be created
-   health can be monitored
-   usage is recorded
-   Agent runs are observable
-   at least two useful connectors work where feasible
-   critical tests pass
-   no secrets are committed

------------------------------------------------------------------------

# 39. Technical Definition of Done

A technical component is complete when:

1.  Its product requirement is known.
2.  Its technical responsibility is documented.
3.  Implementation exists.
4.  Tests exist where applicable.
5.  Security behavior is tested where applicable.
6.  Tenant behavior is tested where applicable.
7.  Failure behavior is addressed.
8.  Observability exists where required.
9.  Documentation is updated.
10. Docker environment remains reproducible.
11. CI passes.
12. The implementing developer can explain the component.

------------------------------------------------------------------------

# 40. Learning Requirement

Technology must not be selected solely because it is popular.

For every major component, the team should be able to answer:

-   What problem does it solve?
-   Why do we need it?
-   Why did we choose it?
-   What alternatives exist?
-   What data enters it?
-   What comes out?
-   What can fail?
-   How is it secured?
-   How does it connect to the next component?

Major components:

``` text
FastAPI
PostgreSQL
pgvector
RAG
PII
Company Brain
Skills
Agent
Tools
Webhooks
Observability
Docker
```

------------------------------------------------------------------------

# 41. Final Technical Boundary

Arc is not intended to demonstrate every enterprise technology.

The technical target is:

``` text
Simple Platform
      +
Strong AI Workflow
      +
Good Security Boundaries
      +
Useful Observability
      +
Reproducible Docker Environment
```

The team should spend most engineering effort on:

``` text
Company Brain
Secure RAG
Skills Engine
AI Agent
AI Tools
PII Guard
```

rather than spending the seven-day window building elaborate
infrastructure.

------------------------------------------------------------------------

# 42. Status

**Document:** Technical Requirements Document\
**File:** `docs/requirements/TRD.md`\
**Project:** Arc\
**Primary Language:** Python\
**Frontend:** React/Next.js\
**Backend:** FastAPI\
**Database:** PostgreSQL + pgvector\
**Deployment:** Docker / Docker Compose\
**Authentication:** Google OAuth\
**AI:** Provider-agnostic interface, initial OpenRouter-compatible path\
**Status:** Draft --- Team Technical Review Required
