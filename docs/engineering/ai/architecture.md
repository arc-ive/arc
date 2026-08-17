# Arc AI Development Architecture



## Status



Foundation Phase / Sprint 0



This document defines the standardized AI-assisted development architecture for Arc.



It establishes the development-time relationship between the developer, coding-agent interface, AI routing layer, model gateway, configurable model roles, and Arc repository context.



This document does not define Arc's production application architecture.



---



## 1. Purpose



The purpose of the Arc AI development architecture is to provide a consistent, secure, reproducible, and model-independent workflow for AI-assisted software development.



The standardized development flow is:



Developer

↓

OpenCode

↓

OmniRoute

↓

OpenRouter

↓

Configurable AI model



The workflow must allow models to be changed without requiring codebase-wide changes to the Arc project.



Human engineers remain responsible for:



- Product decisions

- Requirements interpretation

- Architecture decisions

- Security decisions

- Code review

- Validation

- Final approval

- Production-impacting actions



AI tools are development aids and are not authoritative sources of project knowledge.



---



## 2. Scope



This architecture covers:



- OpenCode as the coding-agent interface

- OmniRoute as the local routing and policy layer

- OpenRouter as the initial model gateway

- Configurable model roles

- Repository-based AI context

- AI permission boundaries

- AI-assisted development traceability

- Model fallback principles

- Development-time security boundaries



This architecture does not establish:



- Arc's production application architecture

- Backend framework

- Frontend framework

- Production database

- Cache

- Message broker

- Vector database

- Object storage

- Kubernetes

- Microservices

- Cloud architecture

- Production AI infrastructure

- Product-specific AI agents

- Product-specific RAG architecture



Those decisions require separate requirements and architecture work when justified.



---



## 3. High-Level Architecture



The standardized AI development path is:



```text

Developer

&#x20;   |

&#x20;   v

OpenCode

&#x20;   |

&#x20;   | OpenAI-compatible interface

&#x20;   v

OmniRoute

&#x20;   |

&#x20;   | Routing / policy / model selection

&#x20;   v

OpenRouter

&#x20;   |

&#x20;   +------------------+------------------+

&#x20;   |                  |                  |

&#x20;   v                  v                  v

Primary Model      Review Model       Fast Model

&#x20;   |                  |                  |

&#x20;   +------------------+------------------+

&#x20;                      |

&#x20;                      v

&#x20;                Model Provider(s)

```



The exact model names are intentionally not fixed by this architecture.



Models may be replaced as evaluation results, availability, reliability, cost, or project requirements change.



---



## 4. Layer Responsibilities



### 4.1 Developer



The developer is the final authority for AI-assisted development activity.



The developer is responsible for:



- Defining the task

- Providing appropriate context

- Reviewing AI output

- Validating generated changes

- Running relevant tests

- Reviewing security implications

- Reviewing architecture implications

- Approving changes before commit

- Controlling production-impacting actions



AI output must not be accepted solely because it appears plausible or passes a superficial check.



---



### 4.2 OpenCode



OpenCode is the standardized coding-agent interface used by the Arc engineering team.



Its responsibilities include:



- Interacting with the developer

- Inspecting the repository

- Reading approved project context

- Searching project files

- Inspecting relevant Git history

- Running permitted local development commands

- Producing or modifying local working-tree changes

- Supporting AI-assisted development tasks



OpenCode is not the authoritative source of Arc project knowledge.



The repository remains the durable source of project context.



---



### 4.3 OmniRoute



OmniRoute is the routing and policy layer between OpenCode and downstream model providers.



Its responsibilities include:



- Providing a stable local AI endpoint

- Routing requests to configured models

- Supporting configurable model selection

- Supporting model-role separation

- Supporting fallback behavior where configured

- Preventing OpenCode from being tightly coupled to a specific downstream model

- Providing a controlled boundary between the coding agent and external model services



The exact routing configuration is documented separately in the AI setup documentation.



---



### 4.4 OpenRouter



OpenRouter is the initial model gateway used by the Arc AI development environment.



Its responsibilities include:



- Providing access to supported downstream models

- Acting as the external model gateway

- Providing model availability through its gateway

- Supporting model substitution without changing the coding-agent interface



OpenRouter is not considered the project's permanent or exclusive AI provider.



The architecture must allow the downstream provider to be changed in the future if a justified decision requires it.



---



## 5. Model Abstraction



The AI development system must not permanently couple Arc to a single model.



The stable abstraction is the model role:



```text

Primary

Review

Fast

```



The model assigned to each role is configurable.



For example:



```text

Primary Role

&#x20;   ↓

Configured Model A



Review Role

&#x20;   ↓

Configured Model B



Fast Role

&#x20;   ↓

Configured Model C

```



The actual models may change independently of the rest of the development system.



This allows model selection to consider:



- Correctness

- Reliability

- Context handling

- Security

- Latency

- Cost

- Availability

- Benchmark performance



Model selection must be based on documented evaluation rather than popularity or leaderboard reputation alone.



---



## 6. Model Roles



### 6.1 Primary Model



The Primary model is intended for:



- Normal feature implementation

- Complex debugging

- Difficult reasoning

- Larger development tasks

- Repository-level engineering tasks



Selection criteria include:



- Quality

- Reliability

- Context handling

- Cost

- Performance on Arc-relevant benchmark tasks



---



### 6.2 Review Model



The Review model is intended for independent critique.



Typical uses include:



- Code review

- Security critique

- Architecture critique

- Identifying implementation flaws

- Identifying missing edge cases

- Challenging assumptions



Selection criteria include:



- Critical reasoning

- Defect detection

- Security reasoning

- Ability to independently challenge proposed solutions



The Review model does not replace human review.



---



### 6.3 Fast Model



The Fast model is intended for lightweight development tasks.



Typical uses include:



- Documentation

- Small edits

- Simple tests

- Formatting

- Routine transformations

- Low-complexity repository tasks



Selection criteria include:



- Latency

- Cost

- Reliability

- Acceptable correctness



---



## 7. Model Fallback



The AI development system should support fallback between configured models where technically supported.



A request may fail because of:



- Rate limiting

- Temporary provider failure

- Timeout

- Model availability

- Gateway failure



Fallback behavior must be:



1\. Deterministic.

2\. Configurable.

3\. Documented.

4\. Observable to the developer.

5\. Free from hard-coded model dependencies.



Fallback must not silently change the task's security or permission boundaries.



A fallback model must remain subject to the same repository and security restrictions as the originally selected model.



---



## 8. Repository AI Context Architecture



AI agents obtain durable Arc project context from the repository.



The context hierarchy is:



```text

AGENTS.md

&#x20;   |

&#x20;   v

PROJECT_CONTEXT.md

&#x20;   |

&#x20;   v

CURRENT_STATE.md

&#x20;   |

&#x20;   v

Product / Requirements Documentation

&#x20;   |

&#x20;   v

Architecture Documentation

&#x20;   |

&#x20;   v

Architecture Decision Records

&#x20;   |

&#x20;   v

Relevant Source Code

&#x20;   |

&#x20;   v

Relevant Git History

```



These sources have different responsibilities.



### AGENTS.md



Defines instructions governing AI-assisted work.



It establishes:



- Repository rules

- Source-of-truth precedence

- Development boundaries

- Required engineering behavior

- AI-specific operating rules



---



### PROJECT_CONTEXT.md



Provides durable project context.



It should contain relatively stable information about:



- Project identity

- Domain

- Current engineering direction

- Team responsibilities

- Important constraints

- Foundation state



It must not become a replacement for the complete product requirements document.



---



### CURRENT_STATE.md



Provides short-term repository and Foundation status.



It records:



- Completed Foundation work

- Current work

- Known blockers

- Current risks

- Immediate next steps



It should be updated when meaningful project state changes.



---



### Product and Requirements Documentation



Product requirements define what Arc is expected to do.



When product requirements change, AI agents must use the latest approved repository documentation rather than relying on historical conversations.



During periods where the PRD is still under construction, AI agents must not treat unfinished requirements as finalized product architecture.



---



### Architecture Documentation



Architecture documentation describes approved technical decisions.



AI agents must not treat suggestions or generated designs as approved architecture.



Major architectural decisions must follow the project's ADR process.



---



### ADRs



Architecture Decision Records provide durable records of accepted architectural decisions.



AI agents must use accepted ADRs when proposing or implementing changes affected by those decisions.



If an AI-generated proposal conflicts with an accepted ADR, the ADR takes precedence until the team explicitly changes the decision.



---



### Source Code



Source code is authoritative for the current implementation.



AI agents must inspect relevant existing code before proposing modifications where implementation already exists.



---



### Git History



Git history provides implementation history and context.



It may be used to understand:



- Why a change was introduced

- Previous implementation decisions

- Related changes

- Historical constraints



Git history does not override current approved requirements or architecture decisions.



---



## 9. Source-of-Truth Principle



AI conversations are not a permanent source of project knowledge.



Important decisions discovered during AI-assisted development must be transferred into the appropriate repository artifact.



Examples:



```text

Product decision

&#x20;   → Product / requirements documentation



Architecture decision

&#x20;   → ADR



Engineering convention

&#x20;   → CONTRIBUTING.md or relevant engineering documentation



Security rule

&#x20;   → SECURITY.md or relevant security documentation



Current project state

&#x20;   → CURRENT_STATE.md



AI workflow decision

&#x20;   → docs/engineering/ai/

```



This prevents important project knowledge from being trapped inside individual AI conversations.



---



## 10. Security Boundary



The AI development environment is a development-time system.



It must not receive unrestricted production access.



Initially permitted activities include:



- Reading the repository

- Searching repository files

- Inspecting Git history

- Running local tests

- Running approved local tooling

- Modifying the local working tree



Initially restricted activities include:



- Production database writes

- Accessing production credentials

- Accessing customer data

- Production deployments

- Billing or financial operations

- Destructive cloud operations

- Unrestricted cloud administration



Additional permissions require explicit engineering consideration.



---



## 11. Secrets Boundary



AI tools must never receive:



- Production API keys

- Production passwords

- Production tokens

- Private certificates

- Customer credentials

- Customer secrets

- Sensitive production configuration

- Unnecessary personal or confidential information



Development credentials must be handled through approved local secret/configuration mechanisms.



Secrets must never be committed to Git.



The repository's `.env.example` file may contain variable names and safe placeholders but must never contain real credentials.



---



## 12. External Content Boundary



External content must be treated as untrusted input.



This includes:



- Web pages

- Retrieved documents

- External repositories

- User-provided documents

- Tool responses

- Third-party API responses

- Generated content from external systems



External content must not override:



- Repository instructions

- Security policies

- Approved architecture

- Product requirements

- Human engineering decisions



The AI agent must distinguish between information it is allowed to consume and instructions it is authorized to follow.



---



## 13. MCP and Tool Permissions



MCP servers and other external tools must be introduced incrementally.



Before enabling a tool, the team should determine:



- Why the tool is required

- What data it can access

- What actions it can perform

- Whether it can modify data

- Whether it can access external systems

- Whether credentials are required

- Whether the permissions are broader than necessary



The principle is:



```text

Required capability

&#x20;       ↓

Minimum necessary permission

&#x20;       ↓

Explicit documentation

&#x20;       ↓

Human review

```



Unused tools should not remain enabled merely because they are available.



Every enabled MCP server must have its purpose and relevant permissions documented.



---



## 14. Human Approval Boundary



AI may assist with engineering work, but human engineers retain responsibility for:



- Architecture approval

- Security approval

- Product decisions

- Production-impacting changes

- Merging changes

- Deployment approval

- Changes involving sensitive data

- Changes involving privileged infrastructure



AI output must be reviewed before becoming an accepted project change.



---



## 15. Development Traceability



Meaningful AI-assisted work must remain traceable through normal engineering processes.



The expected chain is:



```text

Linear Issue

&#x20;   ↓

Git Branch

&#x20;   ↓

AI-assisted development

&#x20;   ↓

Developer verification

&#x20;   ↓

Commit

&#x20;   ↓

Pull Request

&#x20;   ↓

Human Review

&#x20;   ↓

Merge

```



AI assistance does not bypass the GitHub and Linear workflow.



The developer remains responsible for ensuring that the final change satisfies the linked work item.



---



## 16. Product-Agnostic Boundary



The AI development architecture must remain usable while Arc's product requirements are evolving.



The following must not be hard-coded into the X-9 AI foundation:



- Product modules

- Product workflows

- Final backend architecture

- Final frontend architecture

- Database architecture

- Production infrastructure

- Product-specific AI agents

- Product-specific RAG pipelines

- Product-specific model requirements



When the approved PRD and architecture become stable, relevant product-specific context may be added to the repository and consequently become available to AI agents through the established context workflow.



---



## 17. Architecture Decision Policy



X-9 establishes the AI development workflow but does not silently approve unrelated application architecture.



A separate ADR is required when a decision:



- Creates a significant architectural dependency

- Establishes a production technology choice

- Introduces a new infrastructure system

- Creates a persistent integration dependency

- Changes security boundaries

- Changes the project's long-term development architecture



Routine configuration of the approved X-9 tooling does not automatically require a new ADR when it implements an already approved Foundation direction.



If implementation reveals a new architectural decision that is not already covered by the Foundation direction or existing ADRs, implementation must pause until the decision is reviewed.



---



## 18. Reproducibility Principle



Another Arc developer must be able to reproduce the approved AI development workflow from repository documentation without relying on private conversations.



The reproducibility path is:



```text

Clone repository

&#x20;     ↓

Read repository instructions

&#x20;     ↓

Configure local development environment

&#x20;     ↓

Install approved AI tooling

&#x20;     ↓

Configure local credentials

&#x20;     ↓

Start routing layer

&#x20;     ↓

Configure coding agent

&#x20;     ↓

Verify model connectivity

&#x20;     ↓

Run repository-context test

&#x20;     ↓

Perform controlled AI-assisted change

```



The exact installation and configuration procedure is maintained separately in:



`docs/engineering/ai/setup.md`



---



## 19. Verification Boundary



The AI architecture is considered operational only after the documented verification process succeeds.



Verification must demonstrate:



- OpenCode is installed and operational

- OmniRoute is reachable

- OpenRouter connectivity works

- An approved model can respond

- OpenCode can operate against the Arc repository

- Repository context can be understood

- A small non-production change can be completed safely

- No secrets were committed

- AI permissions remain within the approved boundary



Verification evidence should be attached to the relevant Linear issue and Pull Request.



---



## 20. Relationship to Existing Arc Documentation



This document does not replace existing Foundation documentation.



The responsibilities are:



```text

AGENTS.md

&#x20;   → AI operating instructions



PROJECT_CONTEXT.md

&#x20;   → Durable project context



CURRENT_STATE.md

&#x20;   → Current project state



CONTRIBUTING.md

&#x20;   → Engineering contribution workflow



SECURITY.md

&#x20;   → Security requirements



docs/architecture/decisions/

&#x20;   → Accepted architecture decisions



docs/engineering/ai/

&#x20;   → AI development system and operating procedures

```



If two documents appear to conflict, the repository's established source-of-truth precedence and the latest approved decision must be followed.



---



## 21. Current Status



This architecture describes the intended X-9 Foundation direction.



At the beginning of X-9, the following may not yet be verified:



- OpenCode installation

- OmniRoute installation

- OpenRouter connectivity

- Model availability

- OpenCode-to-OmniRoute connectivity

- Model benchmark results

- Second-developer reproduction



These items are implementation and verification tasks for X-9 and must not be represented as completed until evidence exists.



---



## 22. Non-Goals



This architecture does not attempt to:



- Build Arc product functionality

- Replace human engineering judgment

- Finalize the application architecture

- Select the production database

- Build production AI infrastructure

- Grant AI production access

- Permanently select a single AI model

- Treat AI conversations as project documentation

- Treat generated architecture as automatically approved architecture



---



## 23. Summary



The Arc AI development foundation establishes a controlled abstraction between engineers and AI models:



```text

Developer

&#x20;   ↓

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configurable Model Role

```



The repository remains the durable source of project context:



```text

Repository

&#x20;   ↓

Instructions

&#x20;   ↓

Project Context

&#x20;   ↓

Current State

&#x20;   ↓

Requirements

&#x20;   ↓

Architecture

&#x20;   ↓

ADRs

&#x20;   ↓

Source Code

&#x20;   ↓

Git History

```



Human engineers remain responsible for architecture, security, validation, review, and final approval.



The AI development foundation must remain independent of unsettled product and application architecture decisions so that Arc can evolve without requiring the AI development system to be redesigned.
