# Arc --- Product Requirements Document

**Project:** Arc\
**Type:** Enterprise AI Engineering / Placement Project\
**Domain:** IT Services\
**Purpose:** Placement and end-to-end engineering learning\
**Implementation Window:** 7 days\
**Status:** Active Implementation PRD

------------------------------------------------------------------------

## 1. Purpose

This PRD defines the actual Arc project to be built during the 7-day
implementation sprint.

Arc is **not a startup, commercial SaaS product, or production
enterprise platform**. It is a serious engineering project intended to
demonstrate and teach how an enterprise AI system works end to end.

The project prioritizes the AI domain while keeping generic platform
capabilities intentionally simple.

The core objective is to build one connected system around:

-   Company Brain
-   Secure RAG
-   Skills Engine
-   AI Agent
-   AI Tools
-   PII protection
-   Webhooks
-   Observability

Supporting capabilities provide the minimum platform foundation required
for these AI workflows:

-   Multi-tenancy
-   Authentication / RBAC
-   Connectors
-   Docker-based local deployment

------------------------------------------------------------------------

# 2. Project Objective

Arc should demonstrate how an IT Services organization can collect
scattered organizational knowledge, protect it, retrieve it according to
user permissions, turn procedures into executable Skills, and allow an
AI Agent to use those Skills and controlled Tools to perform operational
work.

The central loop is:

``` text
Information / Event
        ↓
Connectors / Webhooks
        ↓
PII Guard
        ↓
Company Brain
        ↓
Secure RAG / Skills
        ↓
AI Agent
        ↓
AI Tools
        ↓
Action
        ↓
Observability / Incident
        ↓
Outcome becomes organizational knowledge
```

The final system should be understandable by the team without depending
on an AI assistant to explain its own implementation.

------------------------------------------------------------------------

# 3. Product Vision

The problem Arc demonstrates is that important company knowledge is
scattered across documents, procedures, previous incidents, solutions,
communications, and external systems.

The Company Brain acts as the organization's living memory.

It contains and connects:

-   Knowledge
-   Procedures
-   Policies
-   Incidents
-   Solutions
-   Decisions
-   Relationships
-   Provenance
-   Operational experience

The AI Agent uses this organizational context to perform useful work.

Arc is therefore **not simply a chatbot over documents**.

The intended concept is:

``` text
Company data
      ↓
Company Brain
      ↓
Secure knowledge
      ↓
Skills
      ↓
AI Agent
      ↓
Controlled actions
      ↓
New operational experience
      ↓
Company Brain
```

------------------------------------------------------------------------

# 4. Scope

## 4.1 In Scope

### Platform

1.  Multi-Tenant Platform
2.  Google/Gmail Authentication
3.  Basic RBAC
4.  Docker local environment

### AI / Data

5.  PII Guard
6.  Company Brain
7.  Secure RAG
8.  Skills Engine
9.  AI Agent
10. AI Tools

### Integration / Operations

11. Connectors
12. Webhook Integration Engine
13. Usage Monitoring
14. Health Monitoring
15. Incident Response
16. Agent-driven automatic actions
17. Human approval for sensitive actions

The numbers above are implementation areas, not the old 12-module PRD.

## 4.2 Out of Scope

-   Startup/business model
-   Sales
-   Fundraising
-   Customer acquisition
-   Commercial launch
-   AWS deployment
-   Kubernetes
-   Production multi-region architecture
-   Enterprise SSO
-   Customer-hosted deployment
-   Advanced IAM
-   Advanced multi-tenancy
-   Custom foundation-model training
-   Real customer data
-   Full commercial billing
-   Unnecessary microservices
-   Infrastructure added only to appear enterprise

------------------------------------------------------------------------

# 5. Target Environment

There are no real customers.

Arc will use synthetic data and three simulated tenants.

``` text
Tenant A
 ├── 3–5 users
 └── tenant-specific data

Tenant B
 ├── 3–5 users
 └── tenant-specific data

Tenant C
 ├── 3–5 users
 └── tenant-specific data
```

Each tenant should have its own:

-   users
-   knowledge
-   procedures
-   incidents
-   solutions
-   Skills
-   operational information
-   AI context

The exact number of users can be adjusted for implementation
convenience.

------------------------------------------------------------------------

# 6. Architecture

``` text
                         ARC ENTERPRISE AI PLATFORM
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
        Multi-Tenant              Auth/RBAC               Connectors
             │                        │                        │
             └────────────────────────┼────────────────────────┘
                                      │
                                  PII GUARD
                                      │
                                      ▼
                              ┌───────────────┐
                              │ COMPANY BRAIN │
                              │               │
                              │ Knowledge     │
                              │ Procedures    │
                              │ Policies      │
                              │ Incidents     │
                              │ Solutions     │
                              │ Decisions     │
                              │ Provenance    │
                              └───────┬───────┘
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                         ▼                         ▼
                    SECURE RAG                SKILLS ENGINE
                         │                         │
                         └────────────┬────────────┘
                                      ▼
                                  AI AGENT
                                      │
                         ┌────────────┴────────────┐
                         │                         │
                         ▼                         ▼
                     AI TOOLS                  WEBHOOKS
                         │                         │
                         └────────────┬────────────┘
                                      ▼
                               OBSERVABILITY
                                      │
                               HUMAN APPROVAL
                                      │
                                    DOCKER
```

This is the product-level architecture. It is not a requirement to
create a separate service for every box.

------------------------------------------------------------------------

# 7. Multi-Tenant Platform

## Purpose

Provide basic separation between simulated customer organizations.

## Required Behavior

Arc must support:

-   multiple tenants
-   users associated with tenants
-   tenant-scoped data
-   tenant-aware requests
-   basic tenant isolation

## Example

``` text
Tenant A user
     ↓
Tenant A data       ALLOWED

Tenant A user
     ↓
Tenant B data       DENIED
```

## Acceptance Criteria

-   Three simulated tenants exist.
-   Each tenant has multiple users.
-   Tenant-scoped records can be created.
-   Tenant-scoped records can be retrieved.
-   Cross-tenant access is rejected.
-   Cross-tenant behavior is tested.

Advanced enterprise tenancy is not required.

------------------------------------------------------------------------

# 8. Authentication and RBAC

## Authentication

Use Google/Gmail-based authentication.

Enterprise SSO is not required.

## RBAC

Use a small practical role model, for example:

``` text
Admin
Operator
Employee
```

### Admin

Can manage:

-   users
-   roles
-   tenant configuration
-   operational information

### Operator

Can:

-   investigate incidents
-   use Company Brain
-   use AI workflows
-   execute approved operational tasks

### Employee

Can:

-   access permitted company knowledge
-   use approved knowledge workflows

The exact permissions should remain simple.

## Acceptance Criteria

-   Users can authenticate.
-   Users belong to a tenant.
-   Roles can be assigned.
-   Protected functionality requires authentication.
-   Role permissions are enforced.
-   Tenant isolation remains enforced after authentication.

------------------------------------------------------------------------

# 9. Connectors

## Purpose

Bring external organizational information into the Company Brain.

The project should implement **2--3 real connectors where feasible**.

Selection criteria:

1.  Free or low cost
2.  Easy to authenticate
3.  Useful for Company Brain
4.  Useful for demonstrating external data ingestion
5.  Achievable within seven days

Likely candidates include:

-   GitHub
-   Google Drive
-   another simple useful source if feasible

If a real connector becomes too expensive or technically distracting, a
controlled/fake API may be used.

## Flow

``` text
External System
      ↓
Connector
      ↓
Fetch Data
      ↓
Tenant Association
      ↓
PII Guard
      ↓
Company Brain
```

## Acceptance Criteria

-   At least two useful sources can be connected where feasible.
-   Imported data has tenant context.
-   Connector failures are handled.
-   Secrets are protected.
-   Imported information can enter the Company Brain.

------------------------------------------------------------------------

# 10. PII Guard

## Purpose

Detect and protect personally identifiable information before it reaches
sensitive downstream workflows.

## Flow

``` text
Input
  ↓
PII Detection
  ↓
Redaction / Masking
  ↓
Safe Data
  ↓
Company Brain / RAG / AI
```

## Example

Input:

``` text
Contact John at john@example.com about the outage.
```

Output:

``` text
Contact John at [EMAIL_REDACTED] about the outage.
```

The first implementation can focus on common categories such as email
addresses and phone numbers.

Perfect PII detection is not required.

## Acceptance Criteria

-   Defined PII examples are detected.
-   Defined PII is redacted or masked.
-   Useful non-sensitive information remains.
-   Sensitive values are not unnecessarily logged.
-   PII processing is integrated into relevant data flows.

------------------------------------------------------------------------

# 11. Company Brain

## Purpose

The Company Brain is the central organizational memory of Arc.

It stores and connects information that humans and AI systems need to
understand how the simulated company operates.

## Brain Contents

### Knowledge

General company and technical knowledge.

### Procedures

Step-by-step ways of performing work.

Example:

``` text
Payment API Incident Procedure

1. Check service health.
2. Check recent logs.
3. Check recent deployments.
4. Restart service if permitted.
5. Verify health.
6. Escalate if recovery fails.
```

### Policies

Rules controlling employee and Agent behavior.

### Incidents

Previous operational problems.

### Solutions

How previous incidents were solved.

### Decisions

Important organizational or operational decisions.

### Relationships

Example:

``` text
Incident
   ↓
Service
   ↓
Procedure
   ↓
Skill
   ↓
Solution
```

### Provenance

The Brain should record where information originated:

-   document
-   connector
-   incident
-   procedure
-   user-created entry

## Living Knowledge

Operational outcomes can become future knowledge.

``` text
Incident
   ↓
Investigation
   ↓
Solution
   ↓
Outcome
   ↓
Company Brain
```

## Important Boundary

The Company Brain is not just a vector database.

Structured organizational information and its relationships should be
retained separately from retrieval representations.

## Acceptance Criteria

-   Knowledge can be stored.
-   Procedures can be stored.
-   Incidents can be stored.
-   Solutions can be stored.
-   Provenance can be recorded.
-   Information is tenant-scoped.
-   Brain information can be retrieved through Secure RAG.
-   Operational outcomes can become stored experience/history.

------------------------------------------------------------------------

# 12. Secure RAG

## Purpose

Allow users and Agents to retrieve relevant Company Brain information
while respecting authorization and tenant boundaries.

## Flow

``` text
User / Agent
     ↓
Tenant
     ↓
Permissions
     ↓
Query
     ↓
Retrieval
     ↓
Permission Filtering
     ↓
Allowed Context
     ↓
LLM
     ↓
Response
```

## Critical Requirement

RAG must never become an authorization bypass.

Retrieval must consider:

-   tenant
-   user
-   role
-   permission
-   knowledge access

## Acceptance Criteria

-   Authorized knowledge can be retrieved.
-   Unauthorized knowledge is excluded.
-   Cross-tenant retrieval is prevented.
-   Permission filtering is tested.
-   The LLM receives only permitted context.
-   Retrieval failures are handled safely.

------------------------------------------------------------------------

# 13. Skills Engine

## Purpose

Turn organizational procedures into controlled, executable Skills for
the AI Agent.

A Skill represents a repeatable way of performing a task.

## Example

``` text
Skill: Payment API Recovery

1. Get service health.
2. Get service logs.
3. Check recent deployment.
4. Restart service if allowed.
5. Verify service health.
6. Update incident.
```

## Skill Lifecycle

``` text
Company Brain
      ↓
Procedure / Knowledge
      ↓
AI proposes Skill
      ↓
Human reviews
      ↓
Approved Skill
      ↓
Available to Agent
```

The Agent must not invent unrestricted executable behavior.

Skills should operate within defined boundaries.

## Acceptance Criteria

-   Procedures can be represented as Skills.
-   Skills have defined steps.
-   Skills identify permitted Tools.
-   Skill proposals can be reviewed.
-   Human approval can be required before activation.
-   Approved Skills can be invoked by the Agent.
-   Skill execution is observable.

------------------------------------------------------------------------

# 14. AI Agent

## Purpose

The AI Agent is the reasoning and orchestration layer.

It uses:

-   Company Brain
-   Secure RAG
-   Skills
-   AI Tools
-   operational events

to perform tasks.

## Company Brain vs AI Agent

They are both part of the same living system, but they have different
responsibilities.

### Company Brain

``` text
Memory
Knowledge
Experience
Procedures
Policies
History
```

### AI Agent

``` text
Understand
Reason
Plan
Select Skill
Select Tools
Execute
Observe
Adapt
Escalate
```

The Brain tells the Agent what the organization knows and how it works.

The Agent determines what to do in the current situation within its
permissions and approved Skills.

## Agent Flow

``` text
Trigger
  ↓
Understand task
  ↓
Search Company Brain
  ↓
Secure RAG
  ↓
Identify Skill
  ↓
Plan
  ↓
Select Tools
  ↓
Execute
  ↓
Observe result
  ↓
Continue / Resolve / Escalate
```

## Acceptance Criteria

-   Agent can receive a task/event.
-   Agent can retrieve authorized knowledge.
-   Agent can identify an appropriate Skill.
-   Agent can invoke allowed Tools.
-   Agent can observe Tool results.
-   Agent can perform a multi-step workflow.
-   Agent can stop or request human intervention.
-   Agent execution is observable.

------------------------------------------------------------------------

# 15. AI Tools

## Purpose

Provide controlled capabilities that the AI Agent can invoke.

AI Tools are the Agent's controlled interface to the rest of Arc.

## Initial Examples

``` text
search_company_knowledge()
get_service_health()
get_service_logs()
get_recent_incidents()

create_incident()
update_incident()

send_notification()

restart_service()
```

The initial Tool set should remain small.

## Tool Definition

Each Tool should have:

-   name
-   purpose
-   input
-   output
-   permission
-   risk level
-   execution behavior

## Example

``` text
Tool: get_service_health
Risk: Low
Agent: Allowed
Approval: No
```

``` text
Tool: restart_service
Risk: Medium
Agent: Conditional
Approval: Policy-dependent
```

The Agent should never receive unrestricted arbitrary code execution.

## Acceptance Criteria

-   Agent can use approved Tools.
-   Tool inputs are validated.
-   Tool permissions are enforced.
-   Tool results return to the Agent.
-   Tool failures are handled.
-   Tool executions are observable.

------------------------------------------------------------------------

# 16. Webhook Integration Engine

## Purpose

Allow external operational events to enter Arc and trigger workflows.

## Example

``` text
Monitoring System
       ↓
POST /webhooks/events
       ↓
Validate
       ↓
Resolve Tenant
       ↓
PII Guard
       ↓
AI Agent
```

Example event:

``` json
{
  "event": "service_unhealthy",
  "service": "payment-api",
  "tenant_id": "tenant-a"
}
```

## Required Behavior

1.  Receive event.
2.  Validate event.
3.  Resolve tenant.
4.  Protect sensitive data.
5.  Process event.
6.  Trigger relevant workflow.
7.  Record result.

## Acceptance Criteria

-   Valid events are accepted.
-   Invalid events are rejected safely.
-   Tenant context is preserved.
-   Duplicate behavior is defined sufficiently.
-   Failures are observable.
-   Webhooks can trigger Agent workflows.

------------------------------------------------------------------------

# 17. Observability

Observability is intentionally focused on the project needs.

## 17.1 Usage Monitoring

Track:

-   AI requests
-   RAG requests
-   Agent executions
-   Tool calls
-   webhook events
-   connector activity

Example:

``` text
Tenant A

RAG requests:      42
Agent runs:        15
Tool executions:   31
Webhook events:    18
```

## 17.2 Health Monitoring

Track relevant health such as:

-   API
-   Company Brain
-   RAG
-   Agent
-   connectors
-   webhook processing

## 17.3 Incident Response

Operational failures should become incidents.

``` text
Failure
  ↓
Health Signal
  ↓
Incident
  ↓
Agent Investigation
  ↓
Resolution / Human Escalation
```

## 17.4 Agent-Driven Actions

Observability should expose:

-   Agent run
-   trigger
-   selected Skill
-   Tools used
-   actions performed
-   result
-   failure
-   human approval
-   final outcome

Example:

``` text
Agent Run #102

Trigger:
payment-api unhealthy

Knowledge:
Payment API Incident Procedure

Skill:
payment_api_recovery

Tools:
get_service_health()
get_service_logs()
restart_service()

Result:
Service recovered

Human approval:
Not required
```

## Acceptance Criteria

-   Usage can be viewed.
-   Health can be viewed.
-   Incidents can be tracked.
-   Agent executions can be inspected.
-   Tool executions can be inspected.
-   Important failures are visible.
-   Sensitive information is not unnecessarily logged.

------------------------------------------------------------------------

# 18. Human Intervention

AI autonomy must have boundaries.

``` text
AI Agent
    │
    ├── Low-risk action
    │       ↓
    │    Execute
    │
    └── Sensitive action
            ↓
       Human Approval
            │
       ┌────┴────┐
       │         │
    Approve    Reject
       │
    Execute
```

Examples of potentially low-risk actions:

-   search knowledge
-   inspect health
-   inspect logs
-   create incident

Potentially higher-risk actions:

-   restart service
-   change configuration
-   destructive operations

The project only needs a simple approval workflow.

------------------------------------------------------------------------

# 19. Docker Local Deployment

Arc will run locally using Docker.

## Required

-   reproducible local setup
-   documented environment configuration
-   no committed secrets
-   consistent startup process
-   all required application infrastructure containerized where
    practical

## Not Required

-   AWS
-   Kubernetes
-   production cloud deployment
-   customer-hosted deployment

The exact container topology is an engineering decision.

------------------------------------------------------------------------

# 20. AI Provider Strategy

The application should avoid being tightly coupled to one AI provider.

Conceptually:

``` text
Application
     ↓
LLM Interface
     ↓
Provider Adapter
     ↓
Model
```

This allows a free/local/provider-based model to be substituted without
rewriting the Agent.

Prefer free or low-cost options where practical.

The exact model and provider are technical decisions.

------------------------------------------------------------------------

# 21. Data Strategy

Use synthetic data only.

Example data:

-   company policies
-   technical procedures
-   incidents
-   solutions
-   service information
-   documents
-   employee information
-   operational events

No real customer/company data is required.

------------------------------------------------------------------------

# 22. Security Requirements

The project requires the following minimum controls:

-   authentication for protected functionality
-   role-based authorization
-   tenant isolation
-   server-side authorization
-   protected credentials
-   no committed secrets
-   PII protection
-   permission-aware RAG
-   controlled Agent Tools
-   human approval for sensitive actions
-   safe logging

The project does not require a full enterprise security program.

------------------------------------------------------------------------

# 23. AI Safety Requirements

The Agent must not:

-   bypass tenant authorization
-   retrieve unauthorized knowledge
-   execute arbitrary code
-   access arbitrary systems
-   invent permissions
-   execute restricted actions without required approval
-   unnecessarily expose PII

The Agent operates through controlled Tools and approved Skills.

------------------------------------------------------------------------

# 24. Testing Strategy

Testing should concentrate on critical behavior.

## Tenant Tests

-   Tenant A can access Tenant A data.
-   Tenant A cannot access Tenant B data.

## Authentication Tests

-   authenticated user succeeds
-   unauthenticated user is rejected

## Authorization Tests

-   allowed role succeeds
-   disallowed role fails

## PII Tests

-   known PII is detected
-   known PII is redacted

## RAG Tests

-   authorized knowledge retrieved
-   unauthorized knowledge excluded
-   cross-tenant retrieval blocked

## Skill Tests

-   approved Skill executes
-   restricted Skill requires approval

## Agent Tests

-   Agent selects appropriate Tool
-   Agent receives Tool result
-   Agent handles Tool failure
-   Agent escalates when required

## Webhook Tests

-   valid event accepted
-   invalid event rejected
-   tenant context preserved

## End-to-End Test

The golden workflow must work:

``` text
Webhook
 → PII
 → Company Brain
 → Secure RAG
 → Skill
 → Agent
 → Tool
 → Health
 → Incident
 → Observability
```

------------------------------------------------------------------------

# 25. Golden End-to-End Scenario

A simulated customer service becomes unhealthy.

## Step 1 --- Event

``` text
Monitoring System
      ↓
Webhook
      ↓
service_unhealthy
```

## Step 2 --- Tenant Resolution

``` text
Webhook
   ↓
Tenant A
```

## Step 3 --- PII Protection

``` text
Event
   ↓
PII Guard
   ↓
Safe Event
```

## Step 4 --- Company Brain

The Agent searches organizational knowledge about the affected service.

## Step 5 --- Secure RAG

``` text
Query
 ↓
Tenant-scoped procedure
 ↓
Previous incidents
 ↓
Previous solutions
```

## Step 6 --- Skill

``` text
Payment API Recovery Skill
```

## Step 7 --- Agent

The Agent determines the appropriate sequence.

``` text
Get health
   ↓
Get logs
   ↓
Check recent incidents
   ↓
Determine action
```

## Step 8 --- Tool

If allowed:

``` text
restart_service()
```

## Step 9 --- Verification

``` text
get_service_health()
```

## Step 10 --- Incident

If recovered:

``` text
Incident resolved
```

If not:

``` text
Human intervention required
```

## Step 11 --- Learning

``` text
Incident
   ↓
Solution
   ↓
Outcome
   ↓
Company Brain
```

## Step 12 --- Observability

The complete Agent execution is visible.

------------------------------------------------------------------------

# 26. Implementation Priority

AI capabilities receive the highest priority.

Recommended priority:

1.  Company Brain
2.  Secure RAG
3.  Skills Engine
4.  AI Agent
5.  AI Tools
6.  PII Guard
7.  Webhook → Agent integration
8.  AI/Agent Observability
9.  Connectors
10. Multi-tenancy
11. Auth/RBAC
12. Docker/platform polish

Lower-priority platform components should remain simple so they do not
consume time needed for AI components.

------------------------------------------------------------------------

# 27. Seven-Day Roadmap

## Day 1 --- Foundation

-   Docker
-   backend/frontend skeleton
-   required data foundation
-   three simulated tenants
-   users
-   Google authentication
-   basic RBAC

**Exit:** A user can authenticate and access tenant-scoped
functionality.

## Day 2 --- Company Brain + PII

-   knowledge
-   documents
-   procedures
-   policies
-   incidents
-   solutions
-   provenance
-   PII detection/redaction

**Exit:** Synthetic company information can enter and be safely stored
in the Brain.

## Day 3 --- Secure RAG

-   chunking
-   embeddings
-   retrieval
-   tenant filtering
-   permission filtering
-   context construction
-   response generation

**Exit:** Authorized users/Agents can retrieve permitted knowledge
without cross-tenant leakage.

## Day 4 --- Skills + Agent + Tools

-   Skill representation
-   Skill proposal
-   approval
-   Agent
-   planning
-   Tool definitions
-   Tool calling
-   Tool permissions
-   execution tracking

**Exit:** Agent can use an approved Skill and controlled Tools for a
multi-step task.

## Day 5 --- Webhooks + Operations

-   webhook endpoint
-   validation
-   tenant resolution
-   event processing
-   incident workflow
-   health checks
-   Agent-driven actions
-   human approval

**Exit:** A webhook can trigger an Agent workflow that investigates a
simulated operational problem.

## Day 6 --- Connectors + Observability

-   2--3 connectors where feasible
-   connector ingestion
-   usage monitoring
-   health monitoring
-   Agent run visibility
-   Tool execution visibility
-   incident visibility

**Exit:** External information can enter the Brain and important
workflows can be inspected.

## Day 7 --- Integration + Testing + Documentation

-   golden workflow
-   tenant isolation tests
-   security tests
-   RAG tests
-   Agent tests
-   failure tests
-   Docker validation
-   documentation
-   architecture diagram
-   final demonstration

**Exit:** Team can explain and demonstrate the complete Arc workflow
independently.

------------------------------------------------------------------------

# 28. Definition of Done

Arc is complete for this project when:

-   application runs locally
-   Docker setup works
-   three simulated tenants exist
-   Google authentication works
-   basic RBAC works
-   tenant isolation works
-   PII protection works
-   Company Brain works
-   Secure RAG works
-   Skills can be created/approved
-   AI Agent can execute an approved workflow
-   AI Tools work through controlled interfaces
-   Webhooks can trigger workflows
-   incidents can be created/handled
-   usage monitoring exists
-   health monitoring exists
-   Agent activity is observable
-   at least two useful connectors work where feasible
-   golden end-to-end workflow works
-   critical security cases are tested
-   documentation explains the implementation

------------------------------------------------------------------------

# 29. Learning Requirement

The project is not successful merely because the code works.

Each team member should understand the component they implement.

Learning process:

``` text
1. Concept explained
        ↓
2. Architecture understood
        ↓
3. Questions asked
        ↓
4. Team member explains it back
        ↓
5. Implementation designed
        ↓
6. Team member implements
        ↓
7. Implementation reviewed/debugged
        ↓
8. Team member documents what was learned
```

The final goal is that the team can explain the complete system without
relying on an AI assistant to explain their own implementation.

------------------------------------------------------------------------

# 30. Placement Demonstration Requirements

A developer working on Arc should be able to explain:

## Product

What problem Arc demonstrates.

## Company Brain

How organizational knowledge is collected, structured, stored,
connected, and reused.

## Secure RAG

How AI retrieves only authorized information.

## Skills Engine

How procedures become controlled executable Skills.

## AI Agent

How the Agent reasons, plans, selects Skills, and orchestrates actions.

## AI Tools

How the Agent interacts with controlled capabilities.

## PII Guard

How sensitive information is detected and protected.

## Webhooks

How external events enter Arc and trigger workflows.

## Observability

How Agent and system behavior is monitored.

## Security

How tenant isolation and authorization prevent data leakage.

## Docker

How the entire project runs locally.

------------------------------------------------------------------------

# 31. Deferred Technical Decisions

The PRD does not finalize:

-   backend language/framework
-   frontend framework
-   database
-   vector database
-   cache
-   message broker
-   object storage
-   AI provider
-   AI model
-   Agent framework
-   orchestration framework
-   exact connector list
-   container/service topology

These should be selected only when required by implementation.

No technology should be added merely because the architecture diagram
contains a conceptual component.

------------------------------------------------------------------------

# 32. Decision Rule

Before adding infrastructure or a framework, ask:

1.  Does the current Arc workflow require it?
2.  Does it provide useful learning value?
3.  Can the team understand it within seven days?
4.  Is there a simpler alternative?
5.  Does it improve the final demonstration?

If not, defer it.

------------------------------------------------------------------------

# 33. Final Product Flow

``` text
                   EXTERNAL INFORMATION
                           │
                           ▼
                     CONNECTORS
                           │
                           ▼
                      PII GUARD
                           │
                           ▼
                    COMPANY BRAIN
                     │         │
                     │         │
                     ▼         ▼
                SECURE RAG   SKILLS
                     │         │
                     └────┬────┘
                          ▼
                       AI AGENT
                          │
                    ┌─────┴─────┐
                    │           │
                    ▼           ▼
                 AI TOOLS    WEBHOOKS
                    │           │
                    └─────┬─────┘
                          ▼
                    OBSERVABILITY
                          │
                    ┌─────┴─────┐
                    │           │
                 Resolved    Escalated
                    │           │
                    │      Human Approval
                    │           │
                    └─────┬─────┘
                          ▼
                    COMPANY BRAIN
                 learns from outcome
```

------------------------------------------------------------------------

# 34. Final Scope Statement

Arc is a **simplified enterprise AI engineering project for placement**.

Its main demonstration is:

> How a Company Brain, Secure RAG, Skills Engine, AI Agent, AI Tools,
> PII protection, Webhooks, and Observability can work together to turn
> organizational knowledge and operational events into controlled
> AI-assisted actions.

The supporting platform capabilities exist only to make this AI workflow
realistic:

``` text
Multi-Tenant
Auth/RBAC
Connectors
PII
Company Brain
Secure RAG
Skills Engine
AI Agent
AI Tools
Webhooks
Observability
Docker
```

The project should remain simple enough to complete and understand
within seven days.

The goal is not to build everything an enterprise would ever need.

The goal is to build **one coherent enterprise AI system that the team
can explain, implement, demonstrate, and defend technically.**

------------------------------------------------------------------------

# 35. Document Status

**Status:** Active Implementation PRD\
**Purpose:** 7-Day Placement Project\
**Primary Focus:** Company Brain / Secure RAG / Skills / AI Agent\
**Deployment:** Local Docker\
**Authentication:** Google/Gmail\
**Tenants:** Three simulated tenants\
**Real Customer Data:** Not used\
**AWS:** Out of scope\
**Enterprise SSO:** Out of scope\
**Commercial Product:** Out of scope

**Next Step:** Finalize the implementation stack and repository
architecture, then begin Day 1.
