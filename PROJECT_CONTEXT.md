\# Arc — Project Context



\## 1. Project Identity



Product:



Arc



Domain:



IT Services



Product Category:



Enterprise Multi-Tenant AI Platform



Current Phase:



Foundation Phase — X-10 (tenant membership boundary) and X-11 (application RBAC) complete; ADR-001 through ADR-014 accepted and implemented (ADR-014 merged after this baseline); QA Phases 0–4 merged (PR #320, `41f32fd`)



Team:



\- Bala — Engineering + AI Lead

\- Joe — Product + Roadmap Lead

\- Bharath — Platform + DevOps Lead



\## 2. Product Purpose



Arc is being developed as an integrated enterprise platform for IT Services organizations.



The intended product combines multiple interconnected enterprise capabilities rather than operating as a collection of unrelated standalone projects.



The detailed product definition, target personas, business requirements, module boundaries, and roadmap are being established during the Foundation Phase.



\## 3. Product Scope



The project is expected to combine capabilities covering areas such as:



\- Multi-tenant SaaS

\- Enterprise identity and access

\- Customer integrations

\- Secure AI/RAG capabilities

\- Customer health and operational monitoring

\- Webhook/event reliability

\- Customer deployment

\- PII protection

\- Incident response

\- Usage metering and billing

\- Customer onboarding

\- Deployment and technical case-study documentation



The final module definitions, dependencies, priorities, and implementation boundaries are controlled by the approved product roadmap and requirements.



Do not treat this list as a finalized technical architecture.



\## 4. Domain



Primary domain:



IT Services



The system is being designed around enterprise customers that may have:



\- Multiple users

\- Multiple organizations or tenants

\- Existing enterprise identity systems

\- External SaaS systems

\- Customer-specific integrations

\- Sensitive business information

\- Operational and service-level requirements



\## 5. Key Engineering Themes



The engineering design is expected to emphasize:



\- Tenant isolation

\- Authentication

\- Authorization

\- Enterprise integrations

\- Secure AI usage

\- Permission-aware data access

\- Observability

\- Reliability

\- Usage tracking

\- Deployment automation

\- Security

\- Auditability



These themes should be refined into explicit requirements before implementation.



\## 6. Technology Vocabulary



The project is expected to use technologies from areas including:



\### Application Development



\- Frontend

\- Backend APIs

\- Databases

\- Background workers

\- Automated testing



\### AI



\- Large Language Models

\- Retrieval-Augmented Generation

\- Embeddings

\- Vector search

\- AI agents

\- Model routing

\- AI gateways



\### Infrastructure



\- Containers

\- Docker

\- Dev Containers

\- CI/CD

\- Cloud infrastructure



\### Integrations



\- OAuth

\- SAML

\- SCIM

\- Webhooks

\- External SaaS APIs



The exact technology selections are established through the Foundation architecture and environment work.



\## 7. AI Development Architecture



The planned AI-assisted development workflow is:



Developer

&#x20;   ↓

AI Coding Agent

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Selected AI Model



The exact coding agent and model configuration will be finalized during the AI Development Setup.



AI tools are development aids and do not replace the repository's source of truth.



\## 8. Repository Context



Persistent project context is maintained through:



```text

AGENTS.md

PROJECT\_CONTEXT.md

CURRENT\_STATE.md

docs/

```



These files are intended to make project context available consistently across developers and AI development tools.



\## 9. Security Assumptions



The initial security principles include:



\- Tenant boundaries are security boundaries.

\- Authorization must be enforced server-side.

\- Authentication alone is insufficient for tenant isolation.

\- Secrets must not be committed to Git.

\- Production/customer data must not be used for normal development.

\- Sensitive customer data must not be provided to AI development tools.

\- Logs must not expose secrets or unnecessary sensitive information.

\- Significant security decisions must be documented.



See:



`SECURITY.md`



for the current security baseline.



\## 10. Architecture Decision Process



Significant architecture decisions are documented through ADRs.



Location:



```text

docs/architecture/decisions/

```



Examples include decisions involving:



\- Service boundaries

\- Database architecture

\- Tenant isolation

\- Authentication

\- Authorization

\- AI architecture

\- Model routing

\- Infrastructure

\- Deployment

\- Security

\- External integrations



\## 11. Development Workflow



The expected engineering workflow is:



Linear Issue

&#x20;   ↓

GitHub Branch

&#x20;   ↓

Commit(s)

&#x20;   ↓

Pull Request

&#x20;   ↓

CI

&#x20;   ↓

Code Review

&#x20;   ↓

Merge



See:



`CONTRIBUTING.md`



\## 12. Source of Truth



The canonical sources are:



\### GitHub



Source code, engineering documentation, ADRs, AI context, security rules, and development conventions.



\### Linear



Work tracking, priorities, cycles, and roadmap execution.



\### Product Documentation



Approved product requirements and roadmap documents.



\### ADRs



Approved architecture decisions.



AI conversations are not considered permanent project memory unless important information from them is transferred into the appropriate repository documentation.



\## 13. Current Constraints



Current Foundation constraints include:



\- Team of three developers

\- Development across Windows and macOS

\- Need for reproducible environments

\- Need for consistent AI development context

\- Need for controlled GitHub collaboration

\- Need for CI-based quality gates

\- Need for secure handling of credentials and customer data

\- Product roadmap still being finalized



\## 14. Important Project Links



GitHub Organization:



https://github.com/arc-ive



Repository:



https://github.com/arc-ive/arc



Linear:



To be added by the team.



Architecture documentation:



`docs/architecture/`



\## 15. Important Rule



This document is a context summary, not the complete product specification.



When detailed requirements or architecture decisions exist, follow the authoritative requirement or ADR rather than expanding this file with duplicated information.



\## 16. Maintenance



Update this document when stable project context changes.



Do not update it for every commit.



Use:



`CURRENT\_STATE.md`



for short-term project status.



Use:



`docs/`



for detailed requirements and technical documentation.



Use:



`docs/architecture/decisions/`



for significant architecture decisions.

