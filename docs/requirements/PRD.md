# ARC --- Product Requirements Document

**Product:** Arc **Domain:** Enterprise AI / IT Services **Project
Type:** Placement-oriented engineering project **Duration:** 7-day
implementation **Status:** Revised --- Final Consistency Review Draft
**Primary Focus:** AI, Company Brain, Unified Intelligence, Secure RAG,
Skills, Tools, Webhooks, Observability

------------------------------------------------------------------------

# 1. Document Purpose

This PRD defines what Arc is, why it exists, who uses it, the major
product capabilities, their relationships, and the expected end-to-end
behavior.

Arc is being built as a practical engineering project to demonstrate an
end-to-end enterprise AI system.

The project prioritizes understanding and demonstrating AI-driven
workflows rather than implementing production-scale infrastructure for
every enterprise concern.

The PRD defines **what Arc should do and why**.

It does not prescribe unnecessary implementation details such as a
specific microservice topology, cloud architecture, or infrastructure
stack unless explicitly required by the product.

------------------------------------------------------------------------

# 2. Product Objective

Arc demonstrates how an organization can turn scattered company
knowledge and operational information into a controlled AI system
capable of:

-   understanding company knowledge
-   retrieving relevant information securely
-   understanding company procedures
-   selecting appropriate skills
-   using approved tools
-   responding to events
-   performing controlled actions
-   monitoring outcomes
-   escalating serious situations to humans

The central product concept is **Unified Intelligence**.

------------------------------------------------------------------------

# 3. Problem Statement

Companies accumulate critical operational knowledge across:

-   documents
-   procedures
-   policies
-   previous incidents
-   incident resolutions
-   operational records
-   employee knowledge
-   connected systems
-   other internal information sources

Traditional AI applications often treat this information as a collection
of documents to search.

That is insufficient for reliable company automation.

Arc aims to create a **living Company Brain** that understands:

-   what the company knows
-   how the company operates
-   what procedures should be followed
-   what happened previously
-   which actions are allowed
-   when a human must intervene

The Company Brain and AI Agent therefore operate as one **Unified
Intelligence**, with different responsibilities within the same
intelligence system.

------------------------------------------------------------------------

# 4. Product Vision

Arc provides a company-specific intelligence layer that connects company
knowledge, secure retrieval, Skills, Unified Intelligence, controlled
tools, events, actions, and observability.

### Arc Architecture

``` mermaid
flowchart TD
    U[Users / Employees]
    C[Connectors / Company Sources]
    W[Webhooks / Operational Events]

    U --> A[Authentication & RBAC]
    A --> T[Tenant Context]
    C --> P[PII Guard]
    W --> P
    T --> P
    P --> UI[Unified Intelligence]

    CB[Company Brain]
    R[Secure RAG]
    S[Skills Engine]
    L[LLM / Reasoning]
    UI --> CB
    UI --> R
    R --> CB
    UI --> S
    UI --> L

    UI --> Tools[Approved AI Tools]
    Tools --> X[Controlled Actions]
    W --> UI

    X --> O[Observability]
    UI --> O
    Tools --> O
    O --> H[Human Intervention / Incident Response]

    CB --> O
```

The diagram is the **product-level architecture**. It describes logical
responsibilities, not a mandatory microservice or container topology.

The objective is not to build a generic chatbot.

The objective is to demonstrate how AI can understand company context
and safely participate in company workflows.

------------------------------------------------------------------------

# 5. Project Scope

## In Scope

The 7-day project focuses on:

1.  Simple multi-tenancy
2.  Authentication and RBAC
3.  PII protection
4.  Company Brain
5.  Secure RAG
6.  Skills Engine
7.  Unified Intelligence / AI Agent
8.  AI Tools
9.  Webhooks
10. Usage-based observability
11. Incident and health monitoring
12. Automated actions
13. Human intervention
14. Docker-based local execution
15. CI validation
16. AWS deployment direction after local Docker validation

AWS is a follow-on deployment target. It is not allowed to delay or
expand the 7-day local implementation.

## Out of Scope

-   Enterprise SSO
-   AWS deployment as a prerequisite for the 7-day core deliverable
-   production-scale cloud infrastructure
-   Kubernetes
-   complex microservice architecture
-   commercial billing platform
-   real customer data
-   training a foundation model
-   unnecessary enterprise infrastructure

------------------------------------------------------------------------

# 6. Target Environment

Arc uses simulated organizations rather than real companies.

The demonstration environment contains approximately:

-   3 tenants
-   3--5 users per tenant
-   synthetic company information
-   synthetic procedures
-   synthetic incidents
-   synthetic knowledge
-   controlled integrations/events

The purpose is to demonstrate the architecture without exposing real
company data.

------------------------------------------------------------------------

# 7. Users

## 7.1 Platform Administrator

### Responsibility

Manages Arc-level configuration and tenant administration.

### Permissions

May:

-   create tenants
-   configure tenants
-   manage tenant membership
-   assign roles
-   view platform-level operational information where permitted

### Access Boundary

The Platform Administrator may access administrative information
required to manage tenants, but normal tenant data access remains
subject to authorization and audit requirements.

------------------------------------------------------------------------

## 7.2 Company Administrator

### Responsibility

Manages one customer organization's users, knowledge, procedures, and
configuration.

### Permissions

May:

-   manage users within the tenant
-   assign permitted tenant roles
-   manage company knowledge
-   manage procedures and skills where authorized
-   review incidents
-   review company health
-   review tenant usage

### Access Boundary

Restricted to the administrator's tenant.

A Company Administrator must not access another tenant's protected data.

------------------------------------------------------------------------

## 7.3 Operations User

### Responsibility

Monitors company/service operations and handles incidents.

### Permissions

May:

-   view permitted operational information
-   search authorized company knowledge
-   review incidents
-   execute permitted operational tools
-   trigger approved workflows
-   respond to alerts
-   escalate incidents

### Access Boundary

Restricted to assigned tenant data and explicitly permitted operational
actions.

------------------------------------------------------------------------

## 7.4 Employee / End User

### Responsibility

Uses Arc to obtain approved company information and assistance.

### Permissions

May:

-   search permitted company knowledge
-   ask questions through Unified Intelligence
-   access procedures they are authorized to access
-   initiate permitted low-risk workflows

### Access Boundary

Cannot access restricted company information, administrative functions,
or high-risk tools unless explicitly authorized.

------------------------------------------------------------------------

# 8. Authentication & RBAC

## Authentication

Arc requires authentication before protected functionality is accessed.

### Enterprise SSO

**Enterprise SSO is Out of Scope.**

The project uses a simple authentication approach suitable for the
simulated environment.

The exact authentication implementation is a technical decision.

## RBAC

RBAC determines what an authenticated user is allowed to access or
perform.

Authorization must consider:

``` text
User
 ↓
Tenant
 ↓
Role
 ↓
Permission
 ↓
Resource / Action
```

Authentication alone does not grant permission.

## Access Boundary

Every tenant-scoped request must be evaluated against the authenticated
user's tenant and permissions.

Cross-tenant access must be denied.

------------------------------------------------------------------------

# 9. Multi-Tenancy

Arc simulates multiple customer environments.

Example:

``` text
Tenant A
 ├── Users
 ├── Knowledge
 ├── Skills
 ├── Incidents
 └── Usage

Tenant B
 ├── Users
 ├── Knowledge
 ├── Skills
 ├── Incidents
 └── Usage

Tenant C
 ├── Users
 ├── Knowledge
 ├── Skills
 ├── Incidents
 └── Usage
```

Tenant boundaries apply to:

-   users
-   knowledge
-   retrieval
-   skills
-   tools
-   incidents
-   events
-   observability
-   usage

Cross-tenant data leakage is a critical negative test.

------------------------------------------------------------------------

# 10. PII Guard

## Purpose

PII Guard protects sensitive information before it reaches downstream AI
processing or other defined boundaries.

## Workflow

``` text
Input
 ↓
PII Detection
 ↓
Redaction / Masking
 ↓
Sanitized Content
 ↓
Company Brain / RAG / AI
```

## Requirements

PII Guard should:

-   identify supported PII categories
-   redact or mask configured PII
-   preserve useful non-sensitive information
-   avoid unnecessary sensitive-data logging
-   provide predictable failure behavior

The exact detection library is an implementation decision.

------------------------------------------------------------------------

# 11. Company Brain

## Purpose

The Company Brain is Arc's central company-specific knowledge and
operational intelligence layer.

It is not simply a document search system.

It maintains structured and searchable representations of:

-   knowledge
-   procedures
-   policies
-   skills
-   decisions
-   incidents
-   previous solutions
-   relationships
-   provenance
-   permissions
-   tenant context

## Company Brain as Living Intelligence

The Company Brain is continuously informed by company information and
operational history.

Conceptually:

``` text
Company Information
       ↓
Knowledge
       ↓
Procedures
       ↓
Incidents
       ↓
Solutions
       ↓
Decisions
       ↓
Relationships
       ↓
Provenance
       ↓
Unified Intelligence
```

## Relationship With AI Agent

The Company Brain and AI Agent are **not separate intelligence
systems**.

They form one **Unified Intelligence**.

The distinction is functional:

### Company Brain capabilities

-   remember
-   retrieve
-   relate
-   understand company context
-   maintain knowledge
-   provide procedures and history

### Agent capabilities

-   reason over available context
-   select skills
-   decide which approved tools are appropriate
-   execute workflows
-   evaluate tool results
-   determine whether to continue, finish, or escalate

Therefore, Company Brain capabilities provide company memory, context,
retrieval, and operational knowledge, while Agent capabilities provide
reasoning, Skill selection, and controlled action. They remain one
Unified Intelligence.

The Agent should not operate independently of the Company Brain for
company-specific workflows.

------------------------------------------------------------------------

# 12. Secure RAG

## Purpose

Secure RAG allows Unified Intelligence to retrieve relevant company
knowledge while enforcing tenant and permission boundaries.

## Workflow

``` text
User / Event
     ↓
Authentication
     ↓
Tenant Context
     ↓
Authorization
     ↓
Query
     ↓
Retrieval
     ↓
Tenant + Permission Filtering
     ↓
Approved Context
     ↓
Unified Intelligence
     ↓
Response / Action
```

## Requirements

Secure RAG must:

-   preserve tenant context
-   retrieve relevant knowledge
-   enforce access permissions
-   prevent cross-tenant retrieval
-   prevent unauthorized knowledge from entering AI context
-   provide source/provenance information where appropriate

Authentication is not sufficient.

The retrieval layer must also enforce authorization.

------------------------------------------------------------------------

# 13. Skills Engine

## Purpose

The Skills Engine converts company procedures and operational knowledge
into structured, reusable workflows that Unified Intelligence can apply.

A Skill describes **how the company performs a task**.

## Example

``` text
Skill: Service Recovery

Purpose:
Recover a degraded service.

Preconditions:
- service health is degraded

Steps:
1. Check service health
2. Retrieve recent incidents
3. Determine approved recovery action
4. Execute permitted recovery tool
5. Verify service health

Constraints:
- do not restart protected production services automatically

Approval:
- human approval required for high-risk recovery

Failure:
- create/escalate incident
```

## Skill Responsibilities

A Skill may define:

-   purpose
-   inputs
-   preconditions
-   steps
-   constraints
-   allowed tools
-   risk level
-   approval requirements
-   expected output
-   failure behavior
-   provenance/version

Skills are part of Unified Intelligence's operational capability.

------------------------------------------------------------------------

# 14. Unified Intelligence / AI Agent

## Purpose

Unified Intelligence is the combined Company Brain + Agent system.

It provides both:

-   company memory/context
-   reasoning and action

The system is designed to move from:

``` text
Know
 ↓
Understand
 ↓
Decide
 ↓
Act
 ↓
Observe
 ↓
Learn / Update Context
```

## Core Capabilities

Unified Intelligence can:

1.  understand a user/event request
2.  retrieve company knowledge
3.  identify relevant procedures
4.  select an appropriate Skill
5.  determine required tools
6.  execute permitted actions
7.  inspect results
8.  continue or stop
9.  escalate to a human when required
10. record execution context

## Example

``` text
Webhook:
"Payment service is unhealthy."

        ↓

Unified Intelligence
        ↓
Company Brain:
Find previous payment incidents
        ↓
Skill:
Payment Service Recovery
        ↓
Reasoning
        ↓
Tool:
Check Service Health
        ↓
Tool:
Restart Service
        ↓
Verify Health
        ↓
Success?
   /       \
 Yes       No
 |          |
Close      Human
           Escalation
```

## Safety Boundary

Unified Intelligence cannot arbitrarily execute actions.

Actions must pass through approved AI Tools and authorization controls.

------------------------------------------------------------------------

# 15. AI Tools

## Purpose

AI Tools are controlled capabilities that Unified Intelligence can
invoke to interact with Arc or approved external systems.

Tools are the **action interface** between AI reasoning and the real
system.

Examples:

-   search_company_knowledge
-   get_incident_history
-   check_service_health
-   create_incident
-   update_ticket
-   send_notification
-   restart_service
-   escalate_to_human

## Tool Requirements

Each tool should have:

-   defined purpose
-   input schema
-   output schema
-   authorization requirements
-   risk level
-   validation
-   failure behavior
-   audit/observability behavior

## Open-Source Tools and Frameworks

Arc should use suitable open-source AI tools and frameworks where they
provide clear value.

The architecture remains tool-agnostic and extensible.

A selected tool/framework may be:

-   integrated
-   replaced
-   removed
-   evaluated against another option

without changing the product-level concept of AI Tools.

The project should avoid choosing a framework solely because it is
popular.

------------------------------------------------------------------------

# 16. Webhooks

## Purpose

Webhooks allow external or simulated systems to notify Arc about events.

## Example

``` text
Monitoring System
       ↓
Webhook
       ↓
Event Validation
       ↓
Tenant Resolution
       ↓
Unified Intelligence
       ↓
Skill
       ↓
AI Tool
       ↓
Action
```

## Requirements

The webhook system should support:

-   event validation
-   tenant association
-   event identification
-   processing status
-   failure handling
-   duplicate handling where applicable
-   observability

Controlled/fake APIs are acceptable for demonstration.

------------------------------------------------------------------------

# 17. Observability

Arc uses usage-based and operational observability.

The project should monitor:

-   API request count
-   AI request count
-   token usage
-   Agent execution count
-   tool invocation count
-   webhook events
-   successful Agent runs
-   failed Agent runs
-   latency
-   error rate
-   tenant usage
-   service health
-   incident count
-   automated action count
-   human escalation count

## Agent Observability

A completed Agent execution should allow the team to understand:

``` text
What triggered it?
 ↓
Which tenant?
 ↓
What knowledge was retrieved?
 ↓
Which Skill?
 ↓
Which Tools?
 ↓
Which actions?
 ↓
Result?
 ↓
Human intervention?
```

------------------------------------------------------------------------

# 18. Health Monitoring

Health monitoring provides visibility into simulated services and Arc
components.

Example:

``` text
Service
 ↓
Health Signal
 ↓
Healthy / Degraded / Unhealthy
 ↓
Unified Intelligence
 ↓
Skill
 ↓
Action or Escalation
```

Health information should be tenant-scoped where applicable.

------------------------------------------------------------------------

# 19. Incident Response

Incidents represent operational problems requiring investigation or
action.

An incident may originate from:

-   webhook event
-   health degradation
-   failed AI action
-   failed tool
-   external integration
-   human report

Example:

``` text
Health Failure
      ↓
Incident
      ↓
Unified Intelligence
      ↓
Retrieve Previous Solutions
      ↓
Select Skill
      ↓
Attempt Approved Action
      ↓
Verify
      ↓
Resolve / Escalate
```

Serious or high-risk situations should require human intervention.

------------------------------------------------------------------------

# 20. Automated Actions

Arc demonstrates controlled AI-driven actions.

Examples:

-   restart a simulated service
-   create an incident
-   update a ticket
-   send a notification
-   trigger a controlled webhook
-   escalate to a human

Automated actions must be:

-   authorized
-   validated
-   observable
-   auditable

High-risk actions should require human approval.

------------------------------------------------------------------------

# 21. Human Intervention

AI should not be treated as autonomous in every situation.

Human intervention is required when:

-   the action is high risk
-   confidence is insufficient
-   required information is missing
-   an action fails repeatedly
-   policy requires approval
-   the Agent cannot safely determine the next step

Example:

``` text
Agent
 ↓
High-risk action detected
 ↓
Human Approval
 ↓
Approved → Tool → Action
Rejected → Stop / Escalate
```

------------------------------------------------------------------------

# 22. Connectors

Arc may integrate with 2--3 practical external systems where
free/open-source or controlled APIs are available.

Connector selection is based on:

-   ease of integration
-   cost
-   usefulness to the demonstration
-   ability to support company knowledge or operational workflows

Connector-specific technical decisions are implementation decisions and
should not unnecessarily expand infrastructure.

------------------------------------------------------------------------

# 23. Data Model --- Product-Level

The exact technical schema is defined separately, but Arc requires
conceptual entities including:

### Tenant

Represents a simulated customer/company environment.

### User

Represents a person accessing Arc.

### Role

Represents a collection of permissions.

### Knowledge

Represents company-specific information.

### Procedure / Skill

Represents how a company performs an operation.

### Policy

Represents rules or constraints.

### Incident

Represents an operational problem.

### Decision

Represents an important company decision.

### Provenance

Describes where knowledge or procedures originated.

### Agent Execution

Represents a Unified Intelligence execution.

### Tool Execution

Represents an AI Tool invocation.

### Event

Represents a webhook or internal operational event.

### Usage Record

Represents measurable activity.

------------------------------------------------------------------------

# 24. Core End-to-End Workflow

The primary demonstration should connect the major AI components.

``` text
Company Data
      ↓
PII Guard
      ↓
Company Brain
      ↓
Secure RAG
      ↓
Unified Intelligence
      ↓
Skill Selection
      ↓
AI Tool
      ↓
Action
      ↓
Health Verification
      ↓
Observability
      ↓
Human Intervention if Required
```

------------------------------------------------------------------------

# 25. Example End-to-End Scenario

## Scenario: Service Failure

A simulated service becomes unhealthy.

``` text
1. Service health changes
2. Event is generated
3. Webhook receives event
4. Tenant context is established
5. Unified Intelligence is triggered
6. Company Brain retrieves previous incidents
7. Secure RAG retrieves authorized knowledge
8. Unified Intelligence identifies the relevant Skill
9. Skill determines permitted action
10. AI Tool checks service health
11. AI Tool performs approved recovery action
12. Service health is checked again
13. Action result is recorded
14. Observability records the execution
15. If recovery fails, human intervention is requested
```

This scenario demonstrates the core value of Arc.

------------------------------------------------------------------------

# 26. First Demonstration Slice

The first working AI slice should demonstrate:

``` text
Tenant
 ↓
Authenticated User
 ↓
Company Knowledge
 ↓
Secure Retrieval
 ↓
Unified Intelligence
 ↓
Skill
 ↓
AI Tool
 ↓
Controlled Action
 ↓
Observability
```

A webhook-triggered version should be demonstrated after the basic flow
works.

------------------------------------------------------------------------

# 27. Non-Functional Requirements

## Security

-   authentication required for protected functionality
-   server-side authorization
-   tenant isolation
-   permission-aware retrieval
-   protected secrets
-   controlled tool access
-   PII protection
-   auditability

## Reliability

The system should handle:

-   invalid requests
-   retrieval failure
-   AI provider failure
-   tool failure
-   webhook failure
-   action failure
-   human escalation

## Performance

The project should measure:

-   API latency
-   retrieval latency
-   AI latency
-   Agent execution latency
-   tool latency

Exact production-scale targets are not required for the placement
project.

## Reproducibility

The system must run locally using Docker-based tooling. AWS deployment
is a follow-on target after local validation and is not required to
complete the 7-day core implementation.

## Testability

Tests should cover:

-   successful workflows
-   invalid requests
-   RBAC failures
-   cross-tenant access
-   retrieval permissions
-   Agent behavior
-   tool authorization
-   webhook processing
-   PII behavior

------------------------------------------------------------------------

# 28. Product Boundaries

Arc is intentionally a project-sized implementation.

The project does not attempt to solve every enterprise platform problem.

The emphasis is:

``` text
Simple Platform Foundation
          +
Strong AI Demonstration
```

The team should spend more engineering time understanding and
implementing:

-   Company Brain
-   Secure RAG
-   Skills
-   Unified Intelligence
-   AI Tools
-   PII
-   Webhooks
-   Observability
-   Automated actions

than implementing deep enterprise infrastructure.

------------------------------------------------------------------------

# 29. Success Criteria

Arc is successful when the team can independently explain and
demonstrate:

### Company Brain

What information it stores and why.

### Secure RAG

How relevant knowledge is retrieved without violating tenant or
permission boundaries.

### Skills Engine

How company procedures become structured workflows.

### Unified Intelligence

How Company Brain and Agent capabilities work together.

### AI Tools

How the intelligence interacts with controlled systems.

### PII Guard

How sensitive information is protected.

### Webhooks

How external events enter Arc.

### Observability

How an Agent action can be investigated.

### Human Intervention

When and why the system stops autonomous execution.

Most importantly, each team member should understand the end-to-end flow
rather than only their assigned code.

------------------------------------------------------------------------

# 30. Product Review Acceptance Criteria

The revised PRD is ready for implementation planning when:

-   authentication terminology is consistent
-   Enterprise SSO is explicitly Out of Scope
-   RBAC responsibilities and access boundaries are defined
-   Company Brain and AI Agent are consistently described as Unified
    Intelligence
-   Skills are clearly distinguished from knowledge and tools
-   AI Tools are described as controlled action interfaces
-   open-source AI tools/frameworks can be evaluated without locking the
    product to one framework
-   Secure RAG is permission-aware
-   tenant isolation is explicit
-   webhooks are connected to AI workflows
-   observability covers AI and operational actions
-   human intervention is explicitly defined
-   product scope remains limited to the 7-day placement project

------------------------------------------------------------------------

# 31. Ownership

### Joe --- Product + Roadmap

Owns:

-   product scope
-   problem definition
-   user roles
-   product behavior
-   acceptance criteria
-   roadmap
-   product decisions

### Bala --- Engineering + AI

Reviews:

-   AI architecture
-   technical feasibility
-   RAG implementation
-   Agent implementation
-   Skills implementation
-   security implications
-   architecture decisions

### Bharath --- Platform + DevOps

Reviews:

-   Docker
-   local environment
-   CI
-   reproducibility
-   platform implications
-   deployment workflow

------------------------------------------------------------------------

# 32. Source of Truth

The canonical product document is:

``` text
docs/requirements/PRD.md
```

Technical requirements are maintained in:

``` text
docs/requirements/TRD.md
```

Architecture decisions are maintained in:

``` text
docs/architecture/decisions/
```

The PRD defines product behavior.

The TRD defines technical requirements.

ADRs record important architectural decisions.

------------------------------------------------------------------------

# 33. Current Status

**Status:** Revised --- Final Consistency Review Draft

**Next Step:**

1.  Bala reviews revised PRD.
2.  Bala reviews TRD.
3.  Team resolves blocking architecture questions.
4.  Required ADRs are created and reviewed.
5.  Implementation begins.
