# ADR-001: Arc Unified Intelligence Application Architecture

## Status

Proposed

## Date

2026-08-14

## Decision Owners

- Joe — Product scope and product requirements
- Bala — Engineering and AI architecture review
- Bharath — Platform, Docker, CI, and deployment review

## Context

Arc is a 7-day placement-oriented enterprise AI engineering project.

The approved product and technical direction requires one connected system
that demonstrates:

- authenticated multi-tenant access
- tenant-aware RBAC
- PII protection
- Company Brain
- permission-aware Secure RAG
- Skills
- Unified Intelligence
- controlled AI Tools
- webhook-driven workflows
- observability
- automated actions
- human intervention
- reproducible local execution
- CI validation
- AWS deployment after local validation

The product architecture establishes **Unified Intelligence as the single
intelligence layer**. Company Brain and Agent capabilities are functional
parts of that intelligence system rather than separate intelligence
systems.

The project is intentionally limited to seven days. Therefore, the
architecture must demonstrate the required enterprise-AI behavior without
turning every logical component into a separate microservice, container,
database, or repository.

The current technical direction also defines Python 3.12, FastAPI,
PostgreSQL with pgvector, Microsoft Presidio, OpenRouter with configurable
model selection, Docker/Docker Compose, Pytest, Ruff, GitHub Actions, and
AWS as the follow-on deployment target.

## Decision

Arc will use a **modular application architecture** in which the major
product capabilities are implemented as logical components of one
understandable application rather than as mandatory independent
microservices.

The architecture is:

```text
                         ARC ENTERPRISE AI PLATFORM
                                      |
                +---------------------+---------------------+
                |                     |                     |
          Multi-Tenancy         Authentication             RBAC
                |                     |                     |
                +---------------------+---------------------+
                                      |
                                  PII GUARD
                                      |
                                      v
              +----------------------------------------------+
              |              UNIFIED INTELLIGENCE             |
              |                                              |
              |  +----------------------------------------+  |
              |  |             COMPANY BRAIN              |  |
              |  |                                        |  |
              |  | Knowledge / Procedures / Policies     |  |
              |  | Decisions / Incidents / Solutions     |  |
              |  | Relationships / Provenance / Memory   |  |
              |  +--------------------+-------------------+  |
              |                       |                      |
              |                 Secure RAG                   |
              |                       |                      |
              |                 Embeddings                   |
              |                       |                      |
              |  +--------------------v-------------------+  |
              |  |             AGENT CAPABILITY           |  |
              |  |                                        |  |
              |  | Reasoning / Planning / Skill Selection|  |
              |  | Tool Selection / Execution / Escalation|
              |  +--------------------+-------------------+  |
              |                       |                      |
              |                  LLM LAYER                   |
              +-----------------------+----------------------+
                                      |
                         +------------+------------+
                         |                         |
                         v                         v
                  SKILLS ENGINE               AI TOOLS
                                                   |
                                            TOOL EXECUTION
                                                   |
                                  +----------------+----------------+
                                  |                                 |
                                  v                                 v
                           Arc/Internal Systems             External Systems

Data Ingestion / Connectors -----------------> Company Brain
Webhooks / Operational Events ---------------> Unified Intelligence

Company Brain / RAG / AI / Tools -----------> Observability
                                                   |
                                                   v
                                         Human Intervention

Deployment:
Local Docker-first  -----------------------> AWS follow-on
```

### Core architectural decisions

#### 1. Unified Intelligence is the single intelligence layer

Company Brain and Agent capabilities are not independent intelligence
systems.

The **Company Brain capability** provides:

- company knowledge
- procedures
- policies
- decisions
- incidents
- solutions
- relationships
- provenance
- operational context
- memory and retrieval

The **Agent capability** provides:

- reasoning
- planning
- Skill selection
- tool selection
- execution planning
- result interpretation
- failure handling
- escalation

They remain one Unified Intelligence system.

#### 2. Company Brain uses a hybrid data model

Company Brain will not be implemented as only a vector store.

Structured company information will use PostgreSQL. Semantic knowledge
will use embeddings stored through pgvector.

The conceptual model therefore combines:

```text
Structured Company Data
        +
Semantic Knowledge
        +
Relationships
        +
Provenance
        +
Tenant / Permission Context
        =
Company Brain
```

#### 3. Secure RAG is permission-aware

RAG retrieval must establish:

```text
Identity
  -> Tenant Context
  -> Authorization
  -> Retrieval
  -> Tenant / Permission Filtering
  -> Approved Context
  -> Unified Intelligence / LLM
```

The LLM, embeddings layer, and vector store are not authorization
systems.

Cross-tenant or unauthorized knowledge must not be placed into the LLM
context.

#### 4. The LLM is a reasoning component, not a security boundary

The LLM is used for language understanding, reasoning, planning,
generation, Skill selection, tool selection, and interpretation of tool
results.

The application remains responsible for:

- authentication
- authorization
- tenant isolation
- permission checks
- tool authorization
- human approval requirements

#### 5. AI Tools are controlled action interfaces

Unified Intelligence may interact with Arc or approved external systems
only through controlled AI Tools.

Tools must provide:

- defined inputs
- defined outputs
- authorization requirements
- validation
- risk controls
- failure handling
- observability

The LLM must not execute arbitrary Python code or arbitrary system
commands.

The product architecture remains tool/framework agnostic. Suitable
open-source AI libraries or frameworks may be evaluated and replaced
without changing the AI Tools concept.

#### 6. PII protection uses Microsoft Presidio initially

Microsoft Presidio is the initial PII protection technology.

The primary flow is:

```text
Input
  -> Presidio Analyzer
  -> PII Detection
  -> Presidio Anonymizer
  -> Sanitized Content
  -> Company Brain / RAG / AI
```

Presidio is a protection layer, not the complete security boundary.
Authorization, tenant isolation, access control, data minimization, and
secure logging remain application responsibilities.

The initial implementation focuses on practical text PII protection.

#### 7. Logical components are not automatically separate services

The following remain logical components:

- PII Guard
- Company Brain
- Secure RAG
- Skills Engine
- Unified Intelligence
- AI Tools
- Webhooks
- Observability

They do not automatically require separate:

- microservices
- containers
- databases
- repositories

The implementation should use the smallest practical number of
deployable components that can demonstrate the required behavior.

#### 8. Local Docker-first deployment precedes AWS

Local Docker execution is the first deployment target.

Docker Compose should be used for the application and only the local
dependencies actually required.

After local validation, the containerized application should be
deployable to AWS.

The exact AWS service mapping remains an implementation/platform
decision and must not block local development.

## Technology Decisions

| Area | Decision |
|---|---|
| Primary language | Python 3.12 |
| Backend API | FastAPI |
| Structured persistence | PostgreSQL |
| Vector search | pgvector |
| PII protection | Microsoft Presidio |
| LLM provider | OpenRouter |
| LLM model | Configurable |
| AI routing | OmniRoute/configurable routing where used |
| Embeddings | Configurable embedding model |
| AI tools | Tool/framework agnostic |
| Webhooks | FastAPI HTTP endpoints |
| Containers | Docker |
| Local orchestration | Docker Compose |
| Testing | Pytest |
| Linting/formatting | Ruff |
| CI | GitHub Actions |
| Cloud target | AWS after local Docker validation |

These technologies are implementation decisions for the current project
direction. Any significant change should be reviewed rather than silently
introduced during implementation.

## Options Considered

### Option 1 — Modular application architecture

**Description:**

Implement the major capabilities as logical modules/components within a
small application, using shared application boundaries and only the
required supporting infrastructure.

**Advantages:**

- Appropriate for the 7-day implementation window.
- Easier for the team to understand and demonstrate end to end.
- Reduces operational and deployment complexity.
- Keeps the focus on AI, Secure RAG, Skills, Tools, PII, and
  observability.
- Still allows logical boundaries to be maintained in code.

**Disadvantages:**

- Less independent scaling than a fully distributed architecture.
- Some component boundaries are enforced at application/module level
  rather than network/service level.

### Option 2 — Microservice-per-component architecture

**Description:**

Create separate services for PII Guard, Company Brain, RAG, Skills,
Agent, Tools, Webhooks, Observability, and other logical components.

**Advantages:**

- Strong service boundaries.
- Independent deployment and scaling.
- Resembles a larger enterprise distributed architecture.

**Disadvantages:**

- Excessive complexity for a 7-day project.
- Requires additional networking, service discovery, deployment,
  observability, and failure-handling work.
- Risks spending the project on infrastructure instead of AI behavior.
- The PRD/TRD explicitly state that conceptual components do not
  automatically become separate services.

### Option 3 — Monolithic implementation with no logical boundaries

**Description:**

Implement all functionality as one undifferentiated application.

**Advantages:**

- Fastest initial implementation.

**Disadvantages:**

- Makes responsibilities difficult to understand.
- Weakens security and testing boundaries.
- Makes the Unified Intelligence, RAG, Skills, and Tool architecture
  harder to explain and maintain.
- Does not provide the modularity required by the project design.

## Rationale

Option 1 is selected because it provides the correct balance between
architectural clarity and implementation speed.

Arc is intended to demonstrate an end-to-end enterprise AI system, not
to demonstrate distributed-systems infrastructure for its own sake.

The architecture therefore preserves clear logical boundaries while
avoiding unnecessary service decomposition.

The Unified Intelligence model is especially important because the PRD
defines Company Brain and Agent capabilities as one intelligence system.
Separating them into independent intelligence services would introduce a
different architectural interpretation.

The hybrid PostgreSQL + pgvector approach also avoids introducing a
separate vector database while still supporting both structured company
data and semantic retrieval.

## Consequences

### Positive

- Clear single-intelligence architecture.
- Company Brain and Agent responsibilities remain understandable.
- Secure RAG can enforce tenant and permission boundaries at the
  application level.
- Structured and semantic knowledge can coexist.
- AI actions remain controlled through Tools.
- The system is practical to run locally.
- Docker-first development is reproducible.
- The architecture can later evolve toward independently deployed
  services if required.

### Negative

- The initial implementation will not provide independent scaling of
  every logical component.
- Some enterprise-grade infrastructure concerns remain simplified.
- The application may eventually need decomposition if the system grows
  beyond the project scope.

### Risks

- Team members may incorrectly interpret logical components as separate
  services.
- An AI framework may accidentally become tightly coupled to the product
  architecture.
- The LLM may be incorrectly trusted for authorization if application
  checks are not enforced.
- RAG implementation may leak cross-tenant or unauthorized information
  if filtering is performed too late.
- PII detection may miss sensitive information because automated
  detection is not perfect.
- External AI provider availability may affect demonstrations.

## Security Considerations

### Authentication

Protected functionality requires an authenticated identity.

Enterprise SSO is out of scope for this project.

### Authorization

Authorization is enforced by the application using:

```text
Authenticated User
      +
Tenant
      +
Role
      +
Permission
      +
Resource / Action
```

### Tenant Isolation

Tenant context must be established before tenant-scoped data is accessed.

Cross-tenant access must be denied.

### Secure RAG

Permission and tenant filtering must occur before retrieved content is
passed to the LLM.

### PII

PII Guard should sanitize content before it crosses defined AI/data
boundaries.

Presidio is not treated as the complete security boundary.

### AI Security

The LLM cannot:

- bypass authorization
- bypass tenant isolation
- execute arbitrary Python
- execute arbitrary system commands
- bypass required human approval

### Secrets

API keys and credentials must remain outside Git. `.env.example` may
document required variables without containing real secrets.

## Operational Considerations

### Local Development

The project is Local Docker-first.

A new developer should be able to reproduce the environment using the
documented Docker workflow.

### CI

GitHub Actions should validate relevant pull requests through:

- dependency installation
- linting/formatting checks
- unit tests
- applicable integration tests
- Docker image build

### Observability

The system should record sufficient information to understand:

```text
Trigger
  -> Tenant
  -> Retrieved Knowledge
  -> Skill
  -> Tools
  -> Actions
  -> Result
  -> Human Intervention
```

Sensitive values must not be unnecessarily written to logs.

### AWS

AWS is a follow-on deployment target after local Docker validation.

The exact AWS service selection is intentionally not fixed by this ADR.

## Testing / Validation

The architecture will be validated through the following minimum
scenarios.

### Tenant isolation

- Tenant A can retrieve Tenant A knowledge.
- Tenant A cannot retrieve Tenant B knowledge.

### RBAC

- An authorized operation succeeds.
- An unauthorized operation is rejected.

### PII

- Supported PII is detected.
- Configured anonymization/redaction occurs.
- Useful non-sensitive content remains usable.

### Secure RAG

- Authorized knowledge is retrieved.
- Unauthorized knowledge is filtered.
- Cross-tenant retrieval fails.

### Unified Intelligence

- A request can retrieve relevant company context.
- A Skill can be selected.
- An approved Tool can be selected.
- The Tool can execute a controlled action.
- The result can be interpreted.
- Failure can trigger human escalation.

### Tool security

- Authorized tool execution succeeds.
- Invalid inputs are rejected.
- Unauthorized tool execution is blocked.
- Arbitrary code execution is unavailable.

### Webhooks

- Valid events are processed.
- Invalid events are rejected.
- Duplicate events are handled according to the implementation.
- Processing failures are observable.

### Reproducibility

- The application starts through the documented Docker workflow.
- CI can build the application image.
- Tests execute successfully in the supported development environment.

## Related Documents

- `docs/requirements/PRD.md`
- `docs/requirements/TRD.md`
- `docs/architecture/decisions/ADR_TEMPLATE.md`

The PRD defines product behavior and contains the canonical product-level
architecture diagram.

The TRD defines the technical requirements and implementation direction.

ADRs record significant architecture decisions.

## Related Work

- Linear: Arc implementation and architecture work items
- GitHub: Arc repository and pull requests

## Supersedes

None.

## Superseded By

None.

## Review Notes

This ADR is **Proposed** because the PRD/TRD are currently at the final
consistency-review stage and the project documentation states that
required ADRs should be reviewed before implementation.

Once the engineering review is complete, this ADR should be changed to
**Accepted** if the decision is approved.

If a later architecture decision materially changes this architecture,
create a new ADR and mark this ADR as **Superseded** rather than silently
rewriting the historical decision.
