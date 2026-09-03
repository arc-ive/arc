# Arc Final Product and Architecture Specification

**Product:** Arc Enterprise AI Platform
**Domain:** IT Services / Enterprise AI
**Status:** Rebuilt from authoritative sources — Architecture Conditionally Frozen
**Generated:** 2026-09-03
**Commit:** 89c80ece59c4f1c38f3222b5be079f53d541244d
**Authority:** Backend code is authoritative for current implementation behavior; PRD is authoritative for product requirements; TRD is authoritative for technical requirements; ADRs are authoritative for architecture decisions; frontend is presentation only

---

## Table of Contents

1. [Document Purpose](#1-document-purpose)
2. [Product Identity](#2-product-identity)
3. [Source of Truth Hierarchy](#3-source-of-truth-hierarchy)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Multi-Tenancy](#5-multi-tenancy)
6. [Authentication](#6-authentication)
7. [Authorization and RBAC](#7-authorization-and-rbac)
8. [PII Guard](#8-pii-guard)
9. [Company Brain](#9-company-brain)
10. [Secure RAG and Retrieval](#10-secure-rag-and-retrieval)
11. [Skills Engine](#11-skills-engine)
12. [AI Tools](#12-ai-tools)
13. [Unified Intelligence](#13-unified-intelligence)
14. [AI Agent](#14-ai-agent)
15. [Human Intervention](#15-human-intervention)
16. [Webhooks](#16-webhooks)
17. [Connectors](#17-connectors)
18. [Observability](#18-observability)
19. [LLM Layer](#19-llm-layer)
20. [Embeddings Layer](#20-embeddings-layer)
21. [Database Schema](#21-database-schema)
22. [Domain Model](#22-domain-model)
23. [API Surface](#23-api-surface)
24. [Frontend](#24-frontend)
25. [Deployment](#25-deployment)
26. [Security Boundaries](#26-security-boundaries)
27. [Error Handling](#27-error-handling)
28. [Testing](#28-testing)
29. [Current Project State](#29-current-project-state)
30. [Source Conflicts and Open Decisions](#30-source-conflicts-and-open-decisions)
31. [End-to-End Flow Descriptions (A-R)](#31-end-to-end-flow-descriptions-a-r)
32. [Non-Functional Requirements](#32-non-functional-requirements)
33. [Traceability Matrix](#33-traceability-matrix)
34. [Appendix A: Permission Matrix](#appendix-a-permission-matrix)
35. [Appendix B: Database Tables](#appendix-b-database-tables)
36. [Appendix C: API Endpoints](#appendix-c-api-endpoints)

---

## 1. Document Purpose

This document is the single authoritative product and architecture specification for Arc. It replaces all previous specification drafts. Every factual claim is traceable to a specific source file and line number in the repository at commit `89c80ece59c4f1c38f3222b5be079f53d541244d`.

This document defines **what Arc is, how it is built, and what it does**. It does not invent requirements. Where a source is ambiguous or conflicts with another source, the conflict is explicitly identified as an open decision.

---

## 2. Product Identity

| Field | Value |
|---|---|
| Project | Arc |
| Domain | IT Services / Enterprise AI |
| Product Category | Enterprise multi-tenant AI platform |
| Phase | Foundation Phase / Sprint 0 |
| Language | Python `>=3.12,<3.13` |
| Framework | FastAPI |
| Database | PostgreSQL 17 with pgvector |
| PII | Microsoft Presidio (presidio-analyzer, presidio-anonymizer) |
| LLM | Configurable via `LLM_PROVIDER` env var; only `deterministic` supported |
| Embeddings | Configurable via `EMBEDDING_PROVIDER` env var; `deterministic` (zlib.crc32) and `openai` (text-embedding-3-small, 1536-dim) |
| AI Routing | OmniRoute / OpenRouter (configurable, deferred for production) |
| Deployment | Local Docker-first (`docker-compose.yml`), AWS follow-on |
| Testing | pytest |
| Linting | Ruff |
| CI | GitHub Actions |

---

## 3. Source of Truth Hierarchy

### When Sources Conflict

When sources conflict, follow this order:

1. This document (the current task requirements)
2. Backend source code (authoritative for **current implementation** — what exists today)
3. ADRs in `docs/architecture/decisions/` (authoritative for **architecture decisions**)
4. PRD in `docs/requirements/PRD.md` (authoritative for **product requirements** — what the final product should do)
5. TRD in `docs/requirements/TRD.md` (authoritative for **technical requirements** — how the final product should be built)
6. `CURRENT_STATE.md`
7. `PROJECT_CONTEXT.md`

### Distinguishing Current Implementation from Final Product

This document describes **both** the current implementation (what exists in the code at commit `89c80ece`) **and** the final intended product (what the PRD/TRD/ADRs require). Where the current implementation diverges from the final requirement, this document explicitly labels the gap as **DEFERRED**, **NOT YET IMPLEMENTED**, or **OPEN DECISION**.

Backend code is authoritative for auth, RBAC, tenancy, validation, security, execution semantics, and domain logic **as currently implemented**. PRD and TRD are authoritative for what the final product should achieve. Frontend is presentation only.

### Current-vs-Final Gap Summary

| Domain | Current Implementation | Final Intended Product | Gap | Status |
|---|---|---|---|---|
| **Multi-Tenancy** | TenantContext from JWT, cross-tenant denied, path consistency check | Same (complete for V1) | None | **Frozen** |
| **Authentication** | HS256 JWT, sessionStorage, test users | Same + Enterprise SSO (out of scope) | SSO deferred | **Conditionally Frozen** |
| **RBAC** | 22 permissions, 4 roles, Employee has zero permissions | Employee should "initiate permitted low-risk workflows" per PRD §7.4 | Employee role conflict | **Open Decision (C-1)** |
| **PII Guard** | Microsoft Presidio, 6 default categories, applied at ingestion + skill creation + connector sync | Same + webhooks + tool results + observability | Boundary incomplete | **Conditionally Frozen** |
| **Company Brain** | Knowledge CRUD, PII-sanitized ingestion, ADR-003 identity, atomic chunk+document persistence | Same (complete for V1) | None | **Frozen** |
| **Secure RAG** | pgvector HNSW, cosine similarity, ApprovedContext contract, dense semantic only | Same + lexical + hybrid + reranking | Advanced retrieval deferred | **Conditionally Frozen** |
| **Skills Engine** | CRUD + SkillExecutionService, MAX_TOOL_CALLS=10, fail-closed approval, in-memory results | Same + risk field + persisted execution results | Risk field missing, persistence missing | **Conditionally Frozen** |
| **AI Tools** | Platform-owned whitelist (1 tool), ToolExecutionPolicy, tool:execute + per-tool permissions | Same + additional tools (create_incident, send_notification, etc.) | Tool catalog expansion deferred | **Conditionally Frozen** |
| **Unified Intelligence** | Deterministic only, single tool proposal (ADR-004), ApprovedContext contract | Same + production LLM via OmniRoute/OpenRouter | Production LLM deferred | **Conditionally Frozen** |
| **AI Agent** | Bounded orchestration (MAX_STEPS=3), SkillExecutionService boundary, no tool access | Same + memory, multi-step reasoning, approval integration | Memory and approval integration deferred | **Conditionally Frozen** |
| **Human Intervention** | FAIL-CLOSED denial, approval creation + decision API exists, no Agent integration, no expiry sweep | Full approval lifecycle: creation → decision → consumption → Agent re-execution | Consumption path not wired | **NOT YET IMPLEMENTED** |
| **Webhooks** | Inbound-only, HMAC-SHA-256, replay resistance, metadata-only recording, no downstream triggers | Same + trigger Unified Intelligence → Skill → Tool execution | Downstream processing missing | **NOT YET IMPLEMENTED** |
| **Connectors** | GitHub/Slack/Linear adapters, env-based credentials, simulated mode, sync to Company Brain | Same + Google Drive + secure secret management + rotation | Google Drive deferred, secret management missing | **Conditionally Frozen** |
| **Observability** | Aggregation layer, usage summary, component health, best-effort telemetry | Same + agent execution trace + incident count + automated action count + human escalation count | Agent trace deferred | **Conditionally Frozen** |
| **LLM Layer** | Deterministic only, fail-closed on non-deterministic | OmniRoute → OpenRouter → configurable model | Production LLM deferred | **Deferred** |
| **Embeddings** | Deterministic (zlib.crc32) + OpenAI (text-embedding-3-small, 1536-dim), HNSW index | Same (complete for V1) | None | **Frozen** |
| **Database** | 12 tables, no agent_runs or skill_executions | Same + agent_runs + skill_executions (if C-4 decided) | Persistence decision pending | **Open Decision (C-4)** |
| **Frontend** | 33 pages, sessionStorage, capability-based routing | Same (presentation only) | None | **Frozen** |
| **Deployment** | Docker Compose local, GitHub Actions CI | Same + AWS deployment | AWS deferred | **Deferred** |

### Final Freeze Status

**Architecture: Conditionally Frozen**

The foundational architecture (tenancy, auth, RBAC, PII, knowledge, retrieval, skills, tools, agent, webhooks, connectors, observability) is frozen for the current codebase at commit `89c80ece`. The following remain **unresolved or deferred** and may change:

- Employee role permissions (C-1)
- Agent/skill execution result persistence (C-4)
- Production LLM provider selection (OpenRouter decision)
- Webhook → Agent downstream processing
- Human Intervention consumption path
- Connector credential management (secret rotation, encryption)
- AWS deployment architecture

---

## 4. High-Level Architecture

Arc is a single application (not microservices) containing logical components:

```
ARC ENTERPRISE AI PLATFORM
    |
    +-- Multi-Tenancy (TenantContext from JWT, X-10)
    +-- Authentication (JWT, sessionStorage)
    +-- RBAC (22 permissions, 4 roles)
    |
    v
PII GUARD (Microsoft Presidio — ingestion boundary only)
    |  Applied at: knowledge ingestion, skill creation, connector sync
    |  NOT applied universally on every request
    v
UNIFIED INTELLIGENCE
    |
    +-- COMPANY BRAIN
    |   Knowledge • Procedures • Policies
    |   Decisions • Incidents • Solutions
    |
    +-- SECURE RAG
    |   Embeddings • Semantic Retrieval • Approved Context Contract
    |
    +-- AGENT CAPABILITY
    |   Reasoning • Planning • Skill Selection
    |   (No direct tool access — only SkillExecutionService)
    |
    +-- LLM LAYER (deterministic only; OmniRoute/OpenRouter deferred)
    |
    v
SKILLS ENGINE                  AI TOOLS
    |                           |
    v                           v
SkillExecutionService    ToolExecutionService
    |  (single execution boundary)  (RBAC + policy + schema + audit)
    |                           |
    v                           v
Human Intervention        Internal Arc Systems / External Systems
(Approval Gate — currently fail-closed)
    |
DATA INGESTION
    +-- Company Brain ingestion (PII Guard applied)
    +-- Webhooks (inbound HMAC-SHA-256, metadata-only)
    +-- Connectors (GitHub, Slack, Linear)
    |
    v
OBSERVABILITY (aggregation layer — not a second source of truth)
    |
    v
POSTGRESQL + PGVECTOR (12 tables)
```

### Architecture Notes

- **PII Guard** is an ingestion boundary, not universal middleware. It runs at knowledge ingestion, skill creation, and connector sync points — NOT on every API request.
- **Agent** has NO direct tool access. It orchestrates Skills via `SkillExecutionService`, which is the single execution boundary.
- **ToolExecutionService** is the single choke point for ALL tool execution. It enforces RBAC, policy, schema validation, and audit.
- **Human Intervention** is wired for approval creation and decision, but the consumption path (re-executing after approval) is NOT YET IMPLEMENTED. `REQUIRE_HUMAN_APPROVAL` tools currently fail closed.
- The LLM is NOT the authorization system. All security decisions are application-enforced before information reaches the LLM.

---

## 5. Multi-Tenancy

**Source:** `src/arc/db/schema.sql:12-36` (tenants table), `src/arc/security/dependencies.py` (TenantContextService)

### Tenant Model

- Tenants are isolated customer environments
- Every tenant-scoped request requires a trusted `TenantContext`
- The `TenantContext` is established by the X-10 `TenantContextService` from the JWT `sub` claim and the authenticated user's membership
- Cross-tenant access is denied: a member of tenant A can never access tenant B's data

### Tenant Boundaries Apply To

- Users and memberships
- Knowledge documents and chunks
- Skills
- Connectors
- Webhook events
- Tool execution records
- Approval requests
- Observability data

### TenantContext Invariants

- The `TenantContext` is frozen (immutable) once established
- `is_valid` returns `True` only when `tenant_id`, `user_id`, and `roles` are all non-empty
- Services derive the tenant boundary exclusively from `TenantContext.tenant_id`
- Caller-supplied tenant identifiers are never trusted

---

## 6. Authentication

**Source:** `src/arc/security/jwt.py`, `src/arc/security/dependencies.py`, `src/arc/security/models.py`

### JWT Configuration

| Setting | Value |
|---|---|
| Algorithm | HS256 |
| Audience | `arc-api` |
| Issuer | `arc` |
| Secret | `arc-dev-jwt-secret-change-me` (dev only) |
| Storage | **`sessionStorage`** (NOT localStorage) |

### AuthenticatedPrincipal

```python
@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str        # JWT "sub" claim
    tenant_id: str      # JWT "tenant_id" claim
    roles: List[str]    # JWT "roles" claim
```

### Test Users

| User | Role |
|---|---|
| `demo-user` | platform_administrator |
| `admin-a` | company_administrator |
| `employee-a` | employee |

### Enterprise SSO

**Out of scope.** Simple JWT-based authentication suitable for the simulated environment.

---

## 7. Authorization and RBAC

**Source:** `src/arc/security/authorization.py:1-200`

### Roles

| Role | Description |
|---|---|
| `platform_administrator` | Manages Arc-level configuration and tenant administration |
| `company_administrator` | Manages one customer organization's users, knowledge, and configuration |
| `operations_user` | Monitors company/service operations and handles incidents |
| `employee` | Uses Arc to obtain approved company information and assistance |

### Permissions (22 total, colon-based format)

```
tenant:create, tenant:read, user:create, membership:create,
knowledge:create, knowledge:read,
skill:create, skill:read, skill:update, skill:delete, skill:execute,
tool:read, tool:execute,
connector:create, connector:read, connector:sync,
webhook:read,
agent:execute,
approval:read, approval:decide,
observability:read, observability:platform_read
```

### ROLE_PERMISSIONS Matrix

**Source:** `src/arc/security/authorization.py:120-187`

| Permission | platform_admin | company_admin | operations_user | employee |
|---|---|---|---|---|
| `tenant:create` | YES | NO | NO | NO |
| `tenant:read` | YES | YES | YES | NO |
| `user:create` | YES | NO | NO | NO |
| `membership:create` | YES | NO | NO | NO |
| `knowledge:create` | YES | YES | NO | NO |
| `knowledge:read` | YES | YES | YES | NO |
| `skill:create` | YES | YES | NO | NO |
| `skill:read` | YES | YES | YES | NO |
| `skill:update` | YES | YES | NO | NO |
| `skill:delete` | YES | YES | NO | NO |
| `skill:execute` | YES | YES | YES | NO |
| `tool:read` | YES | YES | YES | NO |
| `tool:execute` | YES | YES | YES | NO |
| `connector:create` | YES | YES | NO | NO |
| `connector:read` | YES | YES | YES | NO |
| `connector:sync` | YES | YES | YES | NO |
| `webhook:read` | YES | YES | YES | NO |
| `agent:execute` | YES | YES | YES | NO |
| `approval:read` | YES | YES | NO | NO |
| `approval:decide` | YES | YES | NO | NO |
| `observability:read` | YES | YES | YES | NO |
| `observability:platform_read` | YES | NO | NO | NO |

### Employee Has Zero Permissions by Design

The `employee` role has NO `skill:execute`, `tool:execute`, `agent:execute`, or `approval:decide` permissions. This conflicts with PRD §7.4 which suggests employees may "initiate permitted low-risk workflows" and "search permitted company knowledge."

**Open Decision:** Is the zero-permission Employee role intentional or an oversight?

### skill:update Permission — No Corresponding Endpoint

The `skill:update` permission exists in the authorization matrix and is granted to `platform_administrator` and `company_administrator`. However, no `PUT /skills/{skill_id}` endpoint currently exists in `controllers.py`. The `SkillService` in `skills.py` also lacks an `update_skill()` method. The permission is defined but unimplemented as an API surface.

### Authorization Enforcement

- RBAC is enforced by FastAPI dependencies (`require_permission`, `require_tenant_permission`)
- The `AuthorizationService.has_permission()` method checks the role's permission set
- Per-tool authorization requires `tool:execute` AND every permission declared by the tool
- Authorization is never delegated to the LLM

---

## 8. PII Guard

**Source:** `src/arc/services/pii.py`, `src/arc/security/authorization.py` (shared via dependency injection)

### Technology

**Microsoft Presidio** (presidio-analyzer + presidio-anonymizer), NOT pattern-based detection.

### Configuration

```python
PiiGuardConfig:
    enabled_categories: Optional[Set[str]]
    operators: Optional[Dict[str, str]]
    mask_char: str = "*"
    analyzer_language: str = "en"
```

### Default Enabled Categories

```python
DEFAULT_ENABLED_CATEGORIES = frozenset({
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS",
})
```

### Anonymization Operators

- `replace` — replaces with entity label (e.g., `<PERSON>`)
- `mask` — replaces with mask character (`*`)
- `redact` — removes the entity

### PII Flow

```
RAW INPUT
    |
    v
PiiGuardService.sanitize(text)
    |
    v
Presidio Analyzer (detect PII entities)
    |
    v
Presidio Anonymize (apply operators)
    |
    v
SANITIZED OUTPUT
```

### Failure Behavior

- Analysis or anonymization failure raises `PiiGuardError` (fail closed)
- No unsanitized text is ever returned
- Error messages never contain the input text or detected values
- The service is stateless: no persistence, no caches, no logs of input

### Where PII Guard Is Applied (Current)

- **Knowledge ingestion** (`KnowledgeService.ingest_document`): all textual content
- **Skill creation** (`SkillService.create_skill`): name, purpose, inputs, steps, expected_output, failure_behavior
- **Connector sync** (`ConnectorSyncService.sync`): through `KnowledgeService.ingest_document`

### PII Boundaries (Current vs Final)

| Boundary | Current | Final Required | Status |
|---|---|---|---|
| Knowledge ingestion | ✅ Applied | ✅ Applied | **Frozen** |
| Skill creation | ✅ Applied | ✅ Applied | **Frozen** |
| Connector sync | ✅ Applied (via KnowledgeService) | ✅ Applied | **Frozen** |
| Webhook ingestion | ❌ Not applied (metadata-only, no content stored) | ⚠️ Required if webhook content contains PII | **NOT YET IMPLEMENTED** |
| Tool results | ❌ Not applied (check_service_health returns simulated data) | ⚠️ Required when tools return external data | **NOT YET IMPLEMENTED** |
| Observability data | ❌ Not applied (raw prompts/answers NOT stored) | ✅ Correct by design — no PII stored | **Frozen** |
| LLM input | ⚠️ Partially — Approved Context is sanitized at ingestion | ✅ Required — sanitize before prompt construction | **Conditionally Frozen** |

---

## 9. Company Brain

**Source:** `src/arc/services/knowledge.py`, `src/arc/domain/models.py` (KnowledgeDocument, KnowledgeStatus, KnowledgeSource)

### Purpose

The Company Brain is Arc's central company-specific knowledge and operational intelligence layer. It is not a document search system.

### Knowledge Document Model

```python
class KnowledgeDocument:
    id: str
    tenant_id: str
    source: KnowledgeSource
    provenance: str
    version: int
    status: KnowledgeStatus
    content: str          # Sanitized content (PII Guard applied)
    external_id: Optional[str]
    created_at: datetime
    updated_at: datetime
```

### Knowledge Sources

```python
class KnowledgeSource(str, Enum):
    POLICY = "policy"
    PROCEDURE = "procedure"
    INCIDENT_REPORT = "incident_report"
    TROUBLESHOOTING = "troubleshooting"
    INTERNAL_KNOWLEDGE = "internal_knowledge"
    SOLUTION = "solution"
```

### Knowledge Status

```python
class KnowledgeStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
```

### Document Identity (ADR-003)

When `external_id` is provided, the logical document identity is `(tenant_id, source, external_id)`:

- No existing document → create (version 1)
- Existing document with identical sanitized content → returned unchanged (idempotent)
- Existing document with different sanitized content → new chunks prepared in memory first, then document updated in place with `version = version + 1` and chunk set replaced atomically

### Ingestion Pipeline

```
RAW CONTENT
    |
    v
PiiGuardService.sanitize(content)
    |
    v
RetrievalService.prepare_index(document)
    |   chunk text → embed → validate dimensions
    v
KnowledgeRepository.create_document_with_chunks(document, chunks, embeddings)
    |   ONE database transaction
    v
PERSISTED: document + chunks + embeddings (atomic)
```

### Fail-Closed Ordering

Chunk texts and embeddings are computed BEFORE the owning document is persisted. Embedding failure prevents any persistence — there is never a document without a complete index, nor a partial chunk set.

---

## 10. Secure RAG and Retrieval

**Source:** `src/arc/services/retrieval.py`, `src/arc/services/embeddings.py`, `src/arc/domain/models.py`

### Retrieval Architecture

- **Vector storage:** pgvector extension on PostgreSQL
- **Chunking:** `KnowledgeChunker` (sentence-boundary splitting)
- **Embedding:** Configurable provider (deterministic or openai)
- **Search:** Cosine similarity via pgvector `<=>` operator
- **Index type:** HNSW (cosine distance)

### RetrievalService Methods

| Method | Purpose |
|---|---|
| `prepare_index()` | Chunk + embed a document WITHOUT persisting |
| `persist_index()` | Persist prepared chunks atomically with embeddings |
| `search()` | Embed query and return top tenant-scoped matches |
| `approved_search()` | Return results as `ApprovedContext` (the ONLY representation the LLM may consume) |

### Approved Context Contract

**Source:** `src/arc/domain/models.py` (ApprovedContext, ApprovedContextItem)

```python
class ApprovedContext:
    request_id: str
    tenant_id: str
    principal_id: str
    query: str
    retrieval_method: RetrievalMethod
    items: List[ApprovedContextItem]
    security_metadata: ApprovedContextSecurityMetadata
```

The `ApprovedContext` carries sanitized content with provenance/citation metadata. The LLM never receives raw documents, vectors, or authorization state.

### Retrieval Methods

```python
class RetrievalMethod(str, Enum):
    DENSE_SEMANTIC = "dense_semantic"
```

V1 implements **dense semantic retrieval only**. Lexical, fusion, reranking, and modular routing are later maturity layers.

### RAG Properties

| Property | Status | Source |
|---|---|---|
| Permission-aware retrieval | ✅ `approved_search` returns only tenant-scoped matches | §7, RetrievalService |
| Sanitized content only | ✅ LLM never receives raw documents or vectors | Approved Context Contract |
| No fabrication | ✅ Model cannot invent context — only ApprovedContext items provided | ADR-001, §13 |
| Empty retrieval → answer `None` | ✅ When no matches, no context is provided and answer is `None` | §27 fail-closed principles |
| Archived knowledge excluded | ⚠️ KnowledgeStatus.ARCHIVED exists but filtering at search time not explicitly verified | Open — needs verification |
| Security revalidation | ✅ Matches are tenant-scoped at retrieval; cross-tenant access denied | TenantContext boundary |
| Ingestion/query consistency | ✅ Same embedding provider used for both ingestion and query (single EMBEDDING_PROVIDER config) | EmbeddingSettings |
| Dimension validation | ✅ Dimension mismatch fails closed at configuration time | §20 |

---

## 11. Skills Engine

**Source:** `src/arc/services/skills.py`, `src/arc/services/skill_execution.py`, `src/arc/domain/models.py`

### Skill Model

**Source:** `src/arc/domain/models.py` (Skill dataclass)

```python
@dataclass
class Skill:
    id: str
    tenant_id: str
    name: str
    purpose: str
    version: str
    inputs: List[str]
    preconditions: List[str]
    steps: List[str]
    constraints: List[str]
    allowed_tools: List[str]
    approval_required: bool
    expected_output: Optional[str]
    failure_behavior: Optional[str]
    provenance: Optional[str]
    status: SkillStatus
    created_at: datetime
    updated_at: datetime
```

### Skill Model Gaps

| Field | Current | PRD Requirement | Status |
|---|---|---|---|
| `risk` | **MISSING** — not in Skill dataclass | PRD §13 lists "risk level" as a Skill property | **NOT YET IMPLEMENTED** |
| `status` | ✅ SkillStatus enum (ACTIVE, INACTIVE, ARCHIVED) | Implied by "procedures and skills" management | **Frozen** |
| `approval_required` | ✅ Boolean field | PRD §13: "approval requirements" | **Frozen** |

### Skill Status

```python
class SkillStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
```

### SkillService

CRUD operations for skills within a tenant. Textual fields are sanitized through PII Guard before persistence.

| Method | Purpose |
|---|---|
| `create_skill()` | Create with PII-sanitized fields |
| `get_skill()` | Tenant-scoped lookup |
| `list_skills()` | List all skills for a tenant |
| `delete_skill()` | Tenant-scoped delete |
| `preconditions_met()` | Check if preconditions are satisfied |
| `is_tool_allowed()` | Check if a tool is in the skill's allowed tools |

### Skill Execution

**Source:** `src/arc/services/skill_execution.py`

`SkillExecutionService` is the single execution boundary. It holds NO tool registry and NO handlers. Every action flows through `ToolExecutionService`.

**Execution Flow:**

```
Trusted TenantContext (X-10) + skill:execute permission
    |
    v
resolve Skill (tenant-scoped)
    |
    v
Skill ACTIVE?                        no → FAILED/inactive_skill
    |
    v
preconditions satisfied?             no → PRECONDITION_FAILED
    |
    v
approval_required?                   yes → APPROVAL_REQUIRED (fail closed)
    |
    v
for each proposed tool call (in order):
    |
    v
    allowed by Skill.allowed_tools?  no  → DENIED/disallowed_tool
    |
    v
    ToolExecutionService.execute_tool
    (registry + RBAC + policy + schema + audit)
    |
    success → record step, continue
    failure → record error_kind, STOP (no later step runs)
    |
    v
SUCCEEDED (SkillExecutionResult)
```

### Execution Limits

- `MAX_TOOL_CALLS = 10` — upper bound on proposed tool calls per execution
- `MAX_AGENT_STEPS = 3` — upper bound on Skill executions per Agent run

### Execution Results

**Not persisted.** Agent run and skill execution results are returned as in-memory dataclasses only. There is no `agent_runs` or `skill_executions` table in the schema.

---

## 12. AI Tools

**Source:** `src/arc/services/tools.py`

### Tool Registry

The tool catalog is a **platform-owned, code-defined whitelist**. Tenants cannot register, upload, or modify tools. The registry is closed by construction.

### Platform-Approved Tools

```python
PLATFORM_TOOLS: Tuple[ToolDefinition, ...] = (SERVICE_HEALTH_TOOL,)
```

**Only 1 tool exists:** `check_service_health`

### Tool Definition

```python
class ToolDefinition:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_permissions: FrozenSet[Permission]
    risk_level: ToolRiskLevel
    execution_policy: ToolExecutionPolicy
    audit_policy: ToolAuditPolicy
    handler: Callable[[Dict[str, Any], str], Dict[str, Any]]
```

### Tool Risk Levels

```python
class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

### Tool Risk Policy (Current vs Final)

| Risk Level | Current Behavior | Final Required Behavior | Status |
|---|---|---|---|
| LOW | `ALLOW` — auto-executed after authorization | Read-only tools auto-allowed after authorization | **Frozen** |
| MEDIUM | `ALLOW` or `REQUIRE_HUMAN_APPROVAL` (per tool definition) | State-changing tools require approval by default | **Conditionally Frozen** |
| HIGH | `REQUIRE_HUMAN_APPROVAL` or `DENY` | High-risk/external tools require mandatory approval + safeguards | **Conditionally Frozen** |
| Unknown/Unclassified | Not defined in enum | **Fail closed** (deny execution) | **NOT YET IMPLEMENTED** |

### Tool Risk Policy Rules

1. **LOW-risk tools** (read-only): Auto-allowed after authorization check passes
2. **MEDIUM-risk tools** (state-changing): Require human approval unless explicitly waived
3. **HIGH-risk tools** (destructive/irreversible/external): Mandatory approval + additional safeguards
4. **Unknown risk**: Fail closed — deny execution
5. **HIGH-risk tools MUST declare `REQUIRE_HUMAN_APPROVAL` or `DENY`** (never `ALLOW`)
6. `REQUIRE_HUMAN_APPROVAL` **fails closed** until the approval gate is fully integrated (current: fail-closed denial; final: full approval lifecycle)

### Execution Flow (TRD 14.1)

```
selection → authorization (tool:execute AND all declared permissions)
    → tool policy check → input validation → execution → result handling
    → execution/audit record
```

Every controlled attempt produces an observable `tool_execution_records` row.

### Audit Policy

```python
class ToolAuditPolicy:
    record_summary_only: bool = True
```

Only safe, sanitized summaries are persisted. Sensitive keys are redacted at any nesting depth. Free-form strings are scanned for sensitive patterns (API keys, JWTs, Bearer tokens).

---

## 13. Unified Intelligence

**Source:** `src/arc/services/intelligence.py`

### Definition

Unified Intelligence is the single intelligence layer (ADR-001). It provides secure knowledge reasoning plus the V1 bounded tool-calling contract of ADR-004.

### Flow

```
Authenticated request
    |
    v
Trusted TenantContext (X-10) + permission (knowledge:read)
    |
    v
Approved Context Contract (RetrievalService.approved_search)
    |
    v
OPTIONAL single tool proposal (ADR-004, untrusted)
    |
    v
ToolExecutionService: resolve → validate → authorize → policy → execute
    |
    v
bounded observation folded into ONE reasoning completion
    |
    v
IntelligenceAnswer (answer + citations + execution reference)
```

### Security Invariants

1. The ONLY retrieval path is `RetrievalService.approved_search`
2. The LLM receives ONLY sanitized content and citation references from the approved context
3. Single execution choke point: proposals execute ONLY through `ToolExecutionService`
4. Fail closed on every path: malformed/unknown/unauthorized/policy-blocked proposals degrade to a controlled observation
5. **One iteration only:** at most ONE proposal and ONE execution per query

### ADR-004 V1 Tool Calling

When the configured LLM provider implements `ToolProposingLlm` AND the tool execution service is wired AND the trusted principal/authorization are supplied, the provider may emit ONE raw proposal.

Every failure mode — malformed proposal, unknown tool, invalid arguments, denied authorization, DENY/REQUIRE_HUMAN_APPROVAL policy, execution failure — degrades to a controlled observation. The model can never cause an unauthorized execution.

### IntelligenceAnswer

```python
class IntelligenceAnswer:
    request_id: str
    tenant_id: str
    principal_id: str
    query: str
    answer: Optional[str]
    citations: List[str]
    retrieval_method: RetrievalMethod
    context_used: bool
    tool_executions: List[dict] = field(default_factory=list)
```

---

## 14. AI Agent

**Source:** `src/arc/services/agent.py`

### Definition

The Agent is the Unified Intelligence capability that decides WHICH tenant Skill to run next (PRD 14, TRD 8.3). It sits strictly ABOVE `SkillExecutionService` and adds ONLY orchestration.

### Architecture

```
LLM decision (untrusted)
    | strict AgentDecision.parse (fail closed)
    v tenant-scoped Skill catalog containment
    v SkillExecutionService.execute   <- the single action boundary
    v observe structured SkillExecutionResult
    v stop / chain within MAX_AGENT_STEPS
```

### Security Invariants

1. **No direct tool access of any kind.** The Agent holds no `ToolRegistry`, no handlers, and no `ToolExecutionService` reference. The Agent causes tool execution **indirectly** through `SkillExecutionService`, which is the single execution boundary. This indirection is the security boundary — the Agent cannot bypass Skill constraints, tool authorization, or policy checks.
2. **Untrusted decisions fail closed.** Model output is data, never a grant
3. **Tenant boundary comes only from the trusted X-10 context.** The model never sees or sets tenant identifiers
4. **Strictly bounded.** At most `MAX_AGENT_STEPS=3` Skill executions per run
5. **Human Intervention is not implemented.** An approval-gated Skill stops the run with the propagated `APPROVAL_REQUIRED` outcome

### AgentDecision (Untrusted Model Output)

```python
class AgentDecision:
    skill_id: str
    tool_calls: List[Dict[str, Any]]
    satisfied_preconditions: List[str]
```

Parsed via `AgentDecision.parse()` — returns `None` on any deviation (fail closed, no coercion, no exception escapes).

### Agent Run Status

```python
class AgentRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"
    MAX_STEPS_REACHED = "max_steps_reached"
```

### Agent Decision Enabled

A decision capability must be configured. The default `DeterministicLlmProvider` without a `skill_decision_script` is NOT decision-capable. The Agent fails closed (`agent_capability_unavailable`) until a decision capability is explicitly configured.

---

## 15. Human Intervention

**Source:** `src/arc/services/approvals.py`, `src/arc/services/tools.py` (approval gate)

### Current vs Final Status

| Capability | Current | Final Required | Status |
|---|---|---|---|
| Approval creation | ✅ `record_required_approval()` creates PENDING request | ✅ Same | **Frozen** |
| Approval decision | ✅ `decide_request()` approves/rejects (self-decision prevention, lazy expiry) | ✅ Same | **Frozen** |
| Approval consumption | ⚠️ `consume_approval()` exists but NOT wired into Agent re-execution | ✅ Must re-execute tool after approval | **NOT YET IMPLEMENTED** |
| Agent integration | ❌ Agent propagates `APPROVAL_REQUIRED` but does NOT create approval requests | ✅ Agent must create approval request and re-execute after approval | **NOT YET IMPLEMENTED** |
| Expiry sweep | ❌ Lazy derivation only (no background sweep) | ⚠️ Background sweep recommended for production | **NOT YET IMPLEMENTED** |
| Rejection handling | ⚠️ `APPROVAL_REQUIRED` returned to caller but no stop/escalate behavior | ✅ Rejection stops workflow or escalates | **NOT YET IMPLEMENTED** |

### Current Behavior

`REQUIRE_HUMAN_APPROVAL` tools currently **fail closed** (deny execution). The approval creation path and decision API exist, but the consumption path — re-executing the tool after approval is granted — is NOT wired end-to-end. An Agent encountering an approval-gated Skill stops with `APPROVAL_REQUIRED` outcome.

### Final Behavior (PRD §21, TRD §17.3)

```
Agent detects high-risk action
    → Human Approval required
    → Approval request created (approval_requests table)
    → Human approves via POST /approvals/{id}/decisions
    → consume_approval() atomically marks CONSUMED
    → Tool re-executes with approved approval_id
    → Agent continues or stops based on result
```

### Approval Lifecycle

1. **Creation:** `ToolExecutionService` calls `HumanApprovalService.record_required_approval()` when a `REQUIRE_HUMAN_APPROVAL` tool is executed without an `approval_id`
2. **Decision:** A separate authorized user approves or rejects via `decide_request()`
3. **Consumption:** **NOT YET IMPLEMENTED** — the approved request should be atomically consumed via `consume_approval()` before handler execution

### Approval Model

```python
class ApprovalRequest:
    id: str                    # "appr-{hex[:16]}"
    tenant_id: str
    requested_by_user_id: str
    tool_name: str
    tool_version: str
    risk_level: str
    input_summary: str         # Redacted, max 512 chars
    arguments_digest: str      # SHA-256 of canonical serialized validated args
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime       # 24h TTL
    decided_at: Optional[datetime]
    decided_by_user_id: Optional[str]
    consumed_at: Optional[datetime]
```

### Approval Status

```python
class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"
```

### Security Properties

- **Self-decision prevention:** Requester cannot approve/reject their own request
- **Lazy expiry:** 24h TTL; reads derive expiry without mutating
- **Single-use consumption:** Atomic UPDATE with conditional WHERE; concurrent consumers serialized
- **Idempotent creation:** Duplicate (tenant, tool, version, digest) reuses existing open request
- **Best-effort creation:** Persistence failure is logged and dropped (never breaks the business response)
- **Tenant isolation:** Every repository call is tenant-scoped

### Approval API

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /tenants/{tenant_id}/approvals` | `approval:read` | List requests with lazy expiry |
| `GET /tenants/{tenant_id}/approvals/{id}` | `approval:read` | Read one request |
| `POST /tenants/{tenant_id}/approvals/{id}/decisions` | `approval:decide` | Approve or reject |

### Unresolved Issues

- The Agent does NOT integrate with the approval gate yet (`AgentExecutionService.run()` propagates `APPROVAL_REQUIRED` but does not create approval requests)
- No background expiry sweep (lazy derivation only)
- `decide_request()` uses `context.user_id` from `TenantContext` as the decider, but `decide_request()` also receives `principal_user_id` as a parameter — both are set to `context.user_id` in the controller, which is correct but redundant

---

## 16. Webhooks

**Source:** `src/arc/services/webhook_ingestion.py`

### Scope

**Inbound-only.** No outbound webhooks. No retry. No delivery guarantees beyond idempotent receiver semantics.

### Webhook Flow

```
External/simulated system
    -> POST /webhooks/{endpoint_id}/events (HMAC-signed)
    -> endpoint resolution (tenant binding from trusted config)
    -> timestamp window check (replay resistance, 300s tolerance)
    -> HMAC-SHA256 signature verification (constant-time)
    -> payload validation (size, JSON shape, required fields)
    -> tenant-scoped WebhookEvent record (metadata-only)
```

### Authentication

- HMAC-SHA-256 signature over `{timestamp}.{raw_body}`
- Constant-time comparison via `hmac.compare_digest`
- Signature scheme: `sha256`
- Unknown endpoints, missing headers, stale timestamps, and signature mismatches all return the same uniform 401

### Security Properties

- Tenant binding comes EXCLUSIVELY from environment-configured endpoint entry
- Raw payloads are never persisted, logged, returned, or included in errors
- Only safe envelope metadata survives ingestion
- Duplicate `(tenant_id, event_id)` pairs resolve to the original record (idempotent)

### Request Body Limits

- `MAX_BODY_BYTES = 65536` (64 KB)
- Bodies are read incrementally via `request.stream()` with hard cap
- Content-Length is early-rejection fast path only (client-controlled, never enforcement)

### WebhookEvent

```python
class WebhookEvent:
    id: str
    tenant_id: str
    endpoint_id: str
    event_id: str
    event_type: str
    status: WebhookEventStatus
    payload_size_bytes: int
    created_at: datetime
```

### Not Implemented

- Outbound webhooks
- Retry policy
- Per-endpoint CRUD APIs
- Secret rotation
- Downstream processing triggers

### Webhook Downstream Processing Gap

**Current:** Webhook events are recorded as metadata-only (`webhook_events` table). No downstream processing occurs — the event is stored but not forwarded to Unified Intelligence, Agent, or any Skill.

**Final Required (PRD §16):** Webhook events should trigger downstream processing:
```
External system → Webhook → Event Validation → Tenant Resolution
    → Unified Intelligence → Skill → AI Tool → Action
```

**Gap:** The wiring from webhook ingestion to Unified Intelligence is NOT YET IMPLEMENTED. The webhook system currently functions as a passive event recorder.

---

## 17. Connectors

**Source:** `src/arc/services/connectors.py`, `src/arc/services/connector_sync.py`

### Scope

Provider integrations for ingesting external data into the Company Brain. Follows ADR-001 ingestion boundary (Option A).

### Connector Providers

```python
class ConnectorProvider(str, Enum):
    GITHUB = "github"
    SLACK = "slack"
    LINEAR = "linear"
    GOOGLE_DRIVE = "google_drive"
```

GitHub, Slack, and Linear are committed in the codebase. Google Drive is enum-only (not implemented).

### Credential Management (Current)

- Environment-based: `CONNECTOR_CREDENTIALS` env var
- `ConnectorCredentialStore` reads lazily from environment
- Credentials are never returned, logged, or persisted in the API response

### Credential Management (Current vs Final)

| Property | Current | Final Required | Status |
|---|---|---|---|
| Storage | Environment variable (`CONNECTOR_CREDENTIALS`) | Secure tenant-specific secret management (e.g., AWS Secrets Manager, HashiCorp Vault) | **Deferred** |
| Encryption | ❌ Not encrypted at rest (plaintext env var) | ✅ Encrypted at rest and in transit | **NOT YET IMPLEMENTED** |
| Per-tenant isolation | ⚠️ Single env var for all tenants | ✅ Per-tenant credential isolation | **NOT YET IMPLEMENTED** |
| Least privilege | ⚠️ All-or-nothing credential access | ✅ Per-connector scoped credentials | **NOT YET IMPLEMENTED** |
| Rotation | ❌ No rotation mechanism | ✅ Credential rotation without downtime | **NOT YET IMPLEMENTED** |
| Revocation | ❌ No revocation mechanism | ✅ Immediate revocation capability | **NOT YET IMPLEMENTED** |
| Audit | ⚠️ Sync records only | ✅ Credential access audit trail | **NOT YET IMPLEMENTED** |

### Connector Sync Flow

```
Connector (GitHub/Slack/Linear)
    -> provider adapter (validated, typed records)
    -> Company Brain ingestion (KnowledgeService + PII Guard boundary)
    -> tenant-scoped sync audit record
```

### Sync Deduplication

ADR-003 logical identity: repeated syncs of one source record resolve to ONE tenant-scoped document. External ID format: `{provider}:{source_id}`.

### ConnectorSyncRecord

```python
class ConnectorSyncRecord:
    id: str
    tenant_id: str
    connector_id: str
    provider: ConnectorProvider
    status: ConnectorSyncStatus
    items_fetched: int
    error_kind: Optional[str]
    created_at: datetime
```

### Not Implemented

- Google Drive adapter
- Live mode for all providers
- Outbound webhook delivery from connectors

---

## 18. Observability

**Source:** `src/arc/services/observability.py`

### Scope

Aggregation/read layer, NOT a second source of truth. Authoritative records remain owned by their subsystems.

### ObservabilityService Methods

| Method | Purpose |
|---|---|
| `record_api_request()` | Best-effort telemetry write (never raises) |
| `get_tenant_usage_summary()` | Tenant-scoped aggregates |
| `get_platform_summary()` | Strictly tenant-agnostic platform status |
| `get_component_health()` | Real component checks (database, LLM, embeddings) |

### Failure Semantics

- **TELEMETRY WRITE:** best effort — persistence failure is logged and dropped, never fails the business request
- **READ APIs:** fail closed for authorization and tenant isolation

### Usage Summary Sources

Aggregated from existing subsystem records:
- HTTP telemetry (`api_request_records`)
- Tool execution activity (`tool_execution_records`)
- Connector sync activity (`connector_sync_records`)
- Webhook event activity (`webhook_events`)
- Approval activity (`approval_requests`)

### Component Health

```python
async def get_component_health():
    components = {}
    # database: reachability check
    # llm_provider: build_llm_provider(get_llm_settings())
    # embeddings: build_embedding_provider(get_embedding_settings())
    # webhook_config: WebhookEndpointStore existence
    overall = "healthy" if all healthy else "degraded"
```

Results expose status labels only — never settings values, error details, or configuration material.

---

## 19. LLM Layer

**Source:** `src/arc/services/llm.py`

### Provider Architecture

**Source:** `src/arc/services/llm.py:44-95`

```python
class LlmProvider(Protocol):
    def complete(self, prompt: str) -> str: ...

class ToolProposingLlm(Protocol):
    def propose_tool(self, query: str, context_references: Sequence[str]) -> Optional[Mapping[str, Any]]: ...

class SkillSelectingLlm(Protocol):
    def propose_skill(self, goal: str, catalog: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]: ...
```

### Supported Providers

| Provider | Status |
|---|---|
| `deterministic` | Supported — local, deterministic, CI-safe |
| All others | NOT supported — `LlmConfigurationError` raised at startup |

### DeterministicLlmProvider

- Returns a deterministic summary of cited context items
- Optional `tool_proposal_script` for ADR-004 V1 (off by default)
- Optional `skill_decision_script` for ADR-006 V1 (off by default)
- `skill_decision_capable` property indicates whether a decision capability is actually configured

### LLM Security Boundary (TRD 10.3, ADR-001)

The LLM is NOT the authorization system:
- Providers receive only the prompt text assembled from the Approved Context Contract
- They never receive repository access, vectors, raw documents, or authorization state
- The model cannot choose tenants/principals, grant permissions, bypass schemas/policies, or trigger arbitrary execution

### Configuration

```python
LLM_PROVIDER=deterministic   # only value supported
LLM_MODEL=                   # optional, metadata only for deterministic
```

Production LLM provider/model selection (OpenRouter primary per TRD 34) is a deferred decision.

### LLM Production Chain (Current vs Final)

| Component | Current | Final Required | Status |
|---|---|---|---|
| Provider selection | `deterministic` only (rejects all others) | Configurable via `LLM_PROVIDER` env var | **Conditionally Frozen** |
| Routing | Direct to provider | OmniRoute → OpenRouter → configurable model | **Deferred** |
| Model selection | N/A (deterministic returns static summary) | Configurable per TRD §34 (tool-calling support, reasoning quality, latency, cost) | **Deferred** |
| Fallback | N/A | Provider failover / model fallback | **Deferred** |

---

## 20. Embeddings Layer

**Source:** `src/arc/services/embeddings.py`

### Supported Providers

| Provider | Algorithm | Use Case |
|---|---|---|
| `deterministic` | `zlib.crc32` word hashing + L2 normalization | Development and tests |
| `openai` | `text-embedding-3-small` via OpenAI SDK | Production |

### Storage Dimension

**Fixed at 1536 dimensions** (`EMBEDDING_DIMENSIONS = 1536` in `embeddings.py`; `vector(1536)` in the schema). All providers must produce exactly this dimension. A dimension mismatch fails closed at configuration time.

### EmbeddingSettings

```python
class EmbeddingSettings:
    provider: str = "deterministic"
    model: Optional[str] = None
    dimensions: int = 1536
    api_key: Optional[str] = None
    base_url: Optional[str] = None
```

### Configuration

```python
EMBEDDING_PROVIDER=deterministic
EMBEDDING_MODEL=             # optional
EMBEDDING_DIMENSION=1536     # must match schema
OPENAI_API_KEY=              # required for openai provider without base_url
OMNIROUTE_BASE_URL=          # optional, routes through gateway
```

### OpenAI Provider

- Routes through the project's configured gateway (OmniRoute/OpenRouter) or directly to OpenAI
- When `base_url` is set, the gateway manages the provider credential per ADR-007
- Output dimension is validated against `EMBEDDING_DIMENSIONS`
- No automatic retry/backoff (V1)

### Deterministic Provider

- Text is lowercased, split into alphanumeric words
- Each word is hashed via `zlib.crc32` into a bucket
- Resulting histogram is L2-normalized
- Identical inputs always produce identical vectors
- NOT a semantic model, never a production provider

---

## 21. Database Schema

**Source:** `src/arc/db/schema.sql`

### Tables (12 total)

| Table | Purpose |
|---|---|
| `tenants` | Customer organizations |
| `users` | User accounts |
| `memberships` | User-tenant-role associations |
| `connector_configs` | Connector configurations per tenant |
| `knowledge_documents` | Sanitized knowledge content |
| `skills` | Tenant-scoped skill definitions |
| `tool_execution_records` | Tool execution audit trail |
| `knowledge_chunks` | Embedded text chunks for vector search |
| `connector_sync_records` | Connector synchronization audit |
| `webhook_events` | Inbound webhook event records |
| `api_request_records` | HTTP telemetry |
| `approval_requests` | Human Intervention approval lifecycle |

### Key Indexes

- `knowledge_chunks_tenant_embedding_idx` — HNSW index on `tenant_id + embedding vector` (cosine distance)
- `knowledge_documents_external_id_unique_idx` — unique index on `(tenant_id, source, external_id)` WHERE `external_id IS NOT NULL`
- `approval_requests_tenant_tool_version_digest_unique_idx` — unique index on `(tenant_id, tool_name, tool_version, arguments_digest)` WHERE `status = 'pending'`

---

## 22. Domain Model

**Source:** `src/arc/domain/models.py` (1381 lines)

### Enums (15)

| Enum | Values |
|---|---|
| `UserRole` | platform_administrator, company_administrator, operations_user, employee |
| `ConnectorProvider` | github, slack, linear, google_drive |
| `ConnectorStatus` | active, inactive, error |
| `KnowledgeStatus` | active, archived |
| `KnowledgeSource` | policy, procedure, incident_report, troubleshooting, internal_knowledge, solution |
| `RetrievalMethod` | dense_semantic |
| `SkillStatus` | active, inactive, archived |
| `ToolRiskLevel` | low, medium, high |
| `ToolExecutionStatus` | success, failed |
| `ToolAuthorizationOutcome` | granted, denied |
| `ConnectorSyncStatus` | success, failed |
| `WebhookEventStatus` | received, processed, failed |
| `ApprovalStatus` | pending, approved, rejected, expired, consumed |
| `SkillExecutionStatus` | succeeded, failed, precondition_failed, approval_required, denied |
| `AgentRunStatus` | succeeded, failed, approval_required, max_steps_reached |

### Dataclasses (29)

Key domain objects include: `Tenant`, `User`, `Membership`, `ConnectorConfig`, `KnowledgeDocument`, `KnowledgeChunk`, `KnowledgeMatch`, `Skill`, `ToolExecutionRecord`, `ConnectorSyncRecord`, `WebhookEvent`, `ApiRequestRecord`, `ApprovalRequest`, `TenantContext`, `AuthenticatedPrincipal`, `Permission`, `ApprovedContext`, `ApprovedContextItem`, `ApprovedContextSecurityMetadata`, `IntelligenceAnswer`, `ToolProposal`, `SkillExecutionResult`, `SkillExecutionStepOutcome`, `AgentStepOutcome`, `AgentExecutionResult`, `AgentDecision`.

---

## 23. API Surface

**Source:** `src/arc/api/controllers.py` (1517 lines)

### Endpoint Summary

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Liveness probe |
| `GET` | `/auth/me` | Authenticated | Authenticated profile + permissions |
| `POST` | `/tenants` | `tenant:create` | Create tenant (PLATFORM_ADMINISTRATOR) |
| `GET` | `/tenants/{tenant_id}` | `tenant:read` | Get tenant |
| `POST` | `/users` | `user:create` | Create user (PLATFORM_ADMINISTRATOR) |
| `GET` | `/tenants/{tenant_id}/users` | `tenant:read` | List users for tenant |
| `GET` | `/users/{user_id}/tenants` | Self-scoped | Tenants for user |
| `POST` | `/skills` | `skill:create` | Create skill |
| `GET` | `/skills` | `skill:read` | List skills |
| `GET` | `/skills/{skill_id}` | `skill:read` | Get skill |
| `DELETE` | `/skills/{skill_id}` | `skill:delete` | Delete skill |
| `POST` | `/skills/{skill_id}/execute` | `skill:execute` | Execute skill |
| `POST` | `/agent/runs` | `agent:execute` | Run bounded agent |
| `POST` | `/tenants/{tenant_id}/knowledge` | `knowledge:create` | Create knowledge document |
| `GET` | `/tenants/{tenant_id}/knowledge` | `knowledge:read` | List knowledge documents |
| `GET` | `/tenants/{tenant_id}/knowledge/{doc_id}` | `knowledge:read` | Get knowledge document |
| `GET` | `/tenants/{tenant_id}/knowledge/search` | `knowledge:read` | Search knowledge chunks |
| `POST` | `/tenants/{tenant_id}/intelligence/query` | `knowledge:read` | Unified Intelligence query |
| `GET` | `/tenants/{tenant_id}/tools` | `tool:read` | List platform tool catalog |
| `POST` | `/tenants/{tenant_id}/tools/{name}/execute` | `tool:execute` | Execute tool |
| `GET` | `/tenants/{tenant_id}/connectors` | `connector:read` | List connectors |
| `POST` | `/tenants/{tenant_id}/connectors` | `connector:create` | Create connector |
| `POST` | `/tenants/{tenant_id}/connectors/{id}/sync` | `connector:sync` | Sync connector |
| `POST` | `/webhooks/{endpoint_id}/events` | HMAC auth | Ingest webhook event |
| `GET` | `/tenants/{tenant_id}/webhooks/events` | `webhook:read` | List webhook events |
| `GET` | `/tenants/{tenant_id}/observability/usage-summary` | `observability:read` | Tenant usage summary (`hours` query param, default 24, range 1-168) |
| `GET` | `/platform/observability/summary` | `observability:platform_read` | Platform summary |
| `GET` | `/observability/health` | `observability:platform_read` | Component health |
| `GET` | `/tenants/{tenant_id}/approvals` | `approval:read` | List approval requests (`status` query param optional) |
| `GET` | `/tenants/{tenant_id}/approvals/{id}` | `approval:read` | Get approval request |
| `POST` | `/tenants/{tenant_id}/approvals/{id}/decisions` | `approval:decide` | Approve/reject request |

### Missing Endpoint

No `PUT /skills/{skill_id}` endpoint exists. The `skill:update` permission is defined in the authorization matrix but has no corresponding API surface. `SkillService` in `skills.py` also lacks an `update_skill()` method.

### Dev Endpoints

**Source:** `src/arc/api/dev_controllers.py`

Development-only endpoints for membership provisioning. Not part of the production API surface.

### Tenant Consistency Check

Every tenant-scoped endpoint calls `_require_path_tenant_matches_context()` to verify the path `tenant_id` matches the trusted `TenantContext.tenant_id`. Mismatch returns 403.

---

## 24. Frontend

**Source:** Frontend source fully explored via subtask (87 files)

### Authentication

- **Storage:** `sessionStorage` (key: `arc.accessToken`)
- **NOT localStorage**

### Route Guards

Capability-based routing that reads the user's role and permissions from `/auth/me`. Guards prevent unauthorized navigation.

### Page Count

**33 page files** — names differ significantly from what previous specification drafts claimed.

### Key Pages

- Login, Dashboard, Knowledge, Skills, Connectors, Webhooks, Observability, Approvals, Agent, Intelligence, Settings

### API Layer

17 API endpoint files in `frontend/src/api/`

---

## 25. Deployment

**Source:** `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `.env.example`, `pyproject.toml`

### Dockerfile

```dockerfile
FROM python:3.12-slim-bookworm
WORKDIR /app
EXPOSE 8000
```

### docker-compose.yml

- **Services:** `arc` (application) and `db` (PostgreSQL)
- **Database image:** `pgvector/pgvector:pg17`
- **Port:** 8000 (application), 5432 (database)

### CI Workflow

**Source:** `.github/workflows/ci.yml`

- Runs on pull requests and pushes to `main`
- Steps: checkout, Python 3.12 setup, dependency install, Ruff lint, pytest

### Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | Runtime environment | `development` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://arc:arc-dev-password@localhost:5432/arc` |
| `LLM_PROVIDER` | LLM provider selection | `deterministic` |
| `LLM_MODEL` | LLM model identifier | None |
| `EMBEDDING_PROVIDER` | Embedding provider | `deterministic` |
| `EMBEDDING_MODEL` | Embedding model | None |
| `EMBEDDING_DIMENSION` | Embedding dimension | `1536` |
| `OPENAI_API_KEY` | OpenAI API key (for openai embeddings) | None |
| `OMNIROUTE_BASE_URL` | OmniRoute gateway URL | None |
| `CONNECTOR_CREDENTIALS` | Connector tokens (JSON) | None |
| `WEBHOOK_INGESTION_ENDPOINTS` | Webhook endpoint configs (JSON) | None |

---

## 26. Security Boundaries

### Mandatory Boundaries

1. **Authentication:** JWT-based, `sessionStorage` only
2. **Authorization:** Application-enforced RBAC (22 permissions, 4 roles)
3. **Tenant Isolation:** `TenantContext` derived exclusively from JWT; cross-tenant access denied
4. **PII Protection:** Microsoft Presidio before all AI/data boundaries
5. **Permission-Aware Retrieval:** `approved_search` returns only tenant-scoped, sanitized context
6. **LLM Isolation:** LLM receives ONLY sanitized content + citation references; never raw documents, vectors, or auth state
7. **Tool Authorization:** `tool:execute` + per-tool permissions; platform-owned whitelist
8. **Human Approval:** HIGH-risk tools require approval gate (fail-closed until implemented)

### What the LLM Cannot Bypass

- Authentication
- Authorization
- Tenant isolation
- Tool authorization
- Human approval requirements
- PII guard

---

## 27. Error Handling

### Fail-Closed Principles

- Every security gate fails closed (deny on uncertainty)
- Embedding or LLM failure propagates with no partial answer
- When no approved context matches, nothing runs and the answer is `None`
- Malformed proposals never execute
- Cross-tenant access is indistinguishable from missing (404)

### Controlled Error Types

| Error | Source | Behavior |
|---|---|---|
| `LlmConfigurationError` | LLM provider config | Application refuses to start |
| `EmbeddingConfigurationError` | Embedding config | Application refuses to start |
| `EmbeddingError` | Embedding failure | No answer produced (fail closed) |
| `LlmError` | LLM failure | No partial answer (fail closed) |
| `PiiGuardError` | PII analysis/anonymization | No unsanitized content persisted |
| `ToolNotFoundError` | Unknown tool | 404 + audit record |
| `ToolValidationError` | Invalid input | 400 + audit record |
| `ToolDeniedError` | Authorization/policy denied | 403 + audit record |
| `ToolExecutionError` | Handler failure | 500 + audit record |
| `ApprovalNotFoundError` | Unknown approval | 404 |
| `ApprovalExpiredError` | 24h TTL elapsed | 409 |
| `ApprovalSelfDecisionError` | Self-decision attempt | 403 |
| `ApprovalStateError` | Invalid state transition | 409 |
| `ApprovalConsumedError` | Already consumed | 409 |
| `ConnectorSyncError` | Sync failure | 400 + audit record |
| `WebhookAuthenticationError` | Auth failure | Uniform 401 |
| `WebhookValidationError` | Invalid payload | 400 |

---

## 28. Testing

### Test Framework

pytest (configured in `pyproject.toml`)

### Current Test Coverage

**13 test files** in `tests/` directory. Local pytest is blocked by `.venv` truststore bug on macOS. CI runs via GitHub Actions.

| Test Area | Files | Coverage Status |
|---|---|---|
| Tenant isolation | ✅ | Covered |
| RBAC | ✅ | Covered |
| PII behavior | ✅ | Covered |
| Secure RAG | ✅ | Covered |
| Skills execution | ✅ | Covered |
| AI Tools authorization | ✅ | Covered |
| Webhook processing | ✅ | Covered |
| Unified Intelligence | ✅ | Covered |
| Human Intervention approval lifecycle | ✅ | Covered |
| Agent execution | ⚠️ | Partial — no approval integration test |
| Connector sync | ⚠️ | Partial — simulated mode only |
| Observability | ⚠️ | Partial — aggregation only |
| LLM provider | ⚠️ | Deterministic only |

### CI

GitHub Actions runs lint (Ruff) and tests on every PR and push to `main`.

---

## 29. Current Project State

**Source:** `CURRENT_STATE.md` (as of 2026-09-01)

### What Exists

- Foundation services: tenancy, auth, RBAC, PII, knowledge, retrieval, embeddings, LLM, tools, skills, skill execution, agent, connectors, webhooks, approvals, observability
- 31 API endpoints
- Frontend with 33 pages
- 12 database tables
- Docker Compose local environment
- CI pipeline
- 13 test files (local pytest blocked by `.venv` truststore bug on macOS)

### Deferred / Excluded / Not Yet Implemented

| Item | Classification | Rationale |
|---|---|---|
| `agent_runs` table | **DEFERRED** — Open Decision (C-4) | PRD §23 lists "Agent Execution" entity but schema lacks it; decision pending on whether persistence is required |
| `skill_executions` table | **DEFERRED** — Open Decision (C-4) | Same as above |
| Production LLM provider (OpenRouter) | **DEFERRED** — decision pending | TRD §34 requires OpenRouter; current `deterministic` is sufficient for V1 foundation |
| OmniRoute routing layer | **DEFERRED** — decision pending | TRD §34 mentions OmniRoute; not required for V1 |
| Enterprise SSO | **EXCLUDED** — out of scope | PRD §6: "Enterprise SSO is out of scope" |
| Outbound webhooks | **DEFERRED** — not in V1 scope | No PRD/TRD requirement for outbound webhooks in V1 |
| Google Drive connector | **DEFERRED** — enum only | PRD §22 says "2-3 practical external systems"; GitHub/Slack/Linear suffice |
| Agent-to-approval integration | **NOT YET IMPLEMENTED** | Approval creation exists; consumption path not wired |
| Human Intervention decision UI | **NOT YET IMPLEMENTED** | Backend API exists; frontend not wired |
| Background expiry sweep | **NOT YET IMPLEMENTED** | Lazy derivation only; no background sweep |
| Connector secret management | **DEFERRED** — env-based is V1 | TRD does not mandate secret rotation for V1 |
| AWS deployment | **DEFERRED** — follow-on | TRD §3: "Local Docker-first → AWS deployment" |
| Lexical/hybrid retrieval | **DEFERRED** — later maturity | §10: V1 is dense semantic only |
| Agent memory | **DEFERRED** — not decided | No persistence for agent state across runs |
| Skill risk field | **NOT YET IMPLEMENTED** | PRD §13 lists "risk level" but Skill dataclass lacks field |
| Webhook → Agent downstream | **NOT YET IMPLEMENTED** | §16: webhook events are metadata-only |

---

## 30. Source Conflicts and Open Decisions

### Confirmed Conflicts

| ID | Conflict | Sources | Status |
|---|---|---|---|
| C-1 | Employee role has zero permissions | Backend `ROLE_PERMISSIONS` vs PRD §7.4 | **Open** |
| C-2 | ADR-006 and ADR-007 are "Proposed"/"Draft" but CURRENT_STATE.md says "accepted" | ADR files vs CURRENT_STATE.md | **Open** |
| C-3 | `decide_request()` receives redundant `principal_user_id` parameter (always `context.user_id`) | controllers.py:1500 vs approvals.py:173 | **Low priority** |
| C-4 | No `agent_runs` or `skill_executions` tables despite PRD §23 listing "Agent Execution" as a data model entity | Backend schema vs PRD §23 | **Open** |
| C-5 | Webhook endpoint config is env-based only; no CRUD API | Backend vs TRD §16.4 ("processing status" implies state tracking) | **Open** |
| C-6 | Connector sync creates `KnowledgeDocument` with `source=INTERNAL_KNOWLEDGE` for all providers | connector_sync.py:142 vs KnowledgeSource enum having 4 values | **Low priority** |

### Unresolved Product Decisions

1. Is the zero-permission Employee role intentional?
2. Should agent run and skill execution results be persisted?
3. Should the approval gate be fully integrated with the Agent?
4. Should outbound webhooks be implemented?
5. Should Google Drive connector be implemented?
6. Should the webhook endpoint configuration have a CRUD API?

---

## 31. End-to-End Flow Descriptions (A-R)

Each flow describes the complete path through the system for a specific scenario. Every flow is subject to TenantContext validation (X-10), RBAC enforcement, and fail-closed error handling.

### Flow A: Normal Knowledge Question

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/intelligence/query` |
| 2 | **Auth** | JWT validated; `AuthenticatedPrincipal` extracted from `sub` claim |
| 3 | **TenantContext** | `TenantContextService` establishes trusted context from JWT; path `tenant_id` verified against `TenantContext.tenant_id` |
| 4 | **Permission** | `require_tenant_permission(knowledge:read)` checks role |
| 5 | **Retrieval** | `RetrievalService.approved_search(tenant_id, query, principal_id)` — embeds query, searches pgvector HNSW, returns top matches |
| 6 | **ApprovedContext** | Matches assembled into `ApprovedContext` (sanitized content + citation references only) |
| 7 | **LLM** | `LlmProvider.complete(prompt)` — deterministic provider returns summary of cited context items |
| 8 | **Response** | `IntelligenceAnswer(answer, citations, context_used=True)` returned |
| 9 | **Observability** | `record_api_request()` — best-effort telemetry write |

**Success:** Answer with citations. **Failure:** `LlmError` → no partial answer (fail closed).

### Flow B: Secure RAG Question (No Matches)

| Step | Component | Action |
|---|---|---|
| 1-5 | Same as Flow A | Steps 1-5 identical |
| 6 | **ApprovedContext** | No matches found; `ApprovedContext` with empty `items` list |
| 7 | **LLM** | `LlmProvider.complete(prompt)` — no context items; answer is `None` |
| 8 | **Response** | `IntelligenceAnswer(answer=None, citations=[], context_used=False)` |

**Success:** `None` answer (no fabrication). **Failure:** N/A — this IS the fail-closed behavior.

### Flow C: Operational Action (Direct Tool Execution)

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/tools/{name}/execute` |
| 2 | **Auth** | JWT validated |
| 3 | **TenantContext** | Established and path-verified |
| 4 | **Permission** | `require_tenant_permission(tool:execute)` |
| 5 | **Tool Resolution** | `ToolExecutionService.execute_tool(tool_name, args, principal, tenant_context)` |
| 6 | **Authorization** | `has_permission(tool:execute)` AND all tool-declared permissions |
| 7 | **Policy** | `ToolExecutionPolicy` checked (ALLOW / REQUIRE_HUMAN_APPROVAL / DENY) |
| 8 | **Schema** | Input validated against `input_model` |
| 9 | **Execution** | Tool handler called |
| 10 | **Record** | `ToolExecutionRecord` persisted to `tool_execution_records` |

**Success:** Tool result returned. **Failure:** `ToolDeniedError` (403), `ToolValidationError` (400), `ToolExecutionError` (500).

### Flow D: Agent Executes Skill

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /agent/runs` |
| 2 | **Auth** | JWT validated; `agent:execute` permission required |
| 3 | **TenantContext** | Established and path-verified |
| 4 | **Agent Decision** | `AgentDecision.parse(llm_output)` — fail closed on deviation |
| 5 | **Skill Resolution** | `SkillExecutionService.execute(skill_id, args, principal, tenant_context)` |
| 6 | **Preconditions** | `preconditions_met()` checked |
| 7 | **Tool Calls** | For each proposed tool call: `allowed_tools` check → `ToolExecutionService.execute_tool()` |
| 8 | **Result** | `SkillExecutionResult` returned in-memory |
| 9 | **Agent Loop** | If `MAX_AGENT_STEPS < 3` and more steps, repeat from step 4 |
| 10 | **Final** | `AgentExecutionResult` returned |

**Success:** Agent completes within step limit. **Failure:** `SkillExecutionError` → Agent stops; `MAX_STEPS_REACHED` if limit hit.

### Flow E: Skill Invokes Read-Only Tool (LOW Risk)

| Step | Component | Action |
|---|---|---|
| 1-6 | Same as Flow D | Steps 1-6 identical |
| 7 | **Tool Allowed** | `allowed_tools` contains tool name |
| 8 | **ToolExecutionService** | Authorization → policy check (ALLOW for LOW) → schema validation → execution |
| 9 | **Record** | `ToolExecutionRecord` persisted |
| 10 | **Continue** | Skill continues to next step |

**Success:** Tool executed, step recorded, Skill continues.

### Flow F: State-Changing Tool Requiring Approval (HIGH Risk)

| Step | Component | Action |
|---|---|---|
| 1-7 | Same as Flow E | Steps 1-7 identical |
| 8 | **Policy** | `REQUIRE_HUMAN_APPROVAL` — approval gate check |
| 9 | **Current: Fail Closed** | Execution denied; `APPROVAL_REQUIRED` returned |
| 10 | **Final: Approval Request** | `HumanApprovalService.record_required_approval()` creates PENDING request |
| 11 | **Response** | `SkillExecutionResult(status=APPROVAL_REQUIRED, approval_id=...)` |

**Current:** Execution fails closed. **Final:** Approval request created, execution paused pending human decision.

### Flow G: Human Approves

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/approvals/{id}/decisions` with `{decision: "approve"}` |
| 2 | **Auth** | `approval:decide` permission required |
| 3 | **Self-Check** | Requester ≠ decider (self-decision prevention) |
| 4 | **Expiry Check** | `expires_at > now` (lazy expiry) |
| 5 | **Decision** | `decide_request()` sets `status=APPROVED`, `decided_at=now`, `decided_by_user_id` |
| 6 | **Final: Consumption** | `consume_approval()` atomically sets `status=CONSUMED`, `consumed_at=now` |
| 7 | **Final: Re-execution** | Tool re-executes with approved `approval_id` |

**Current:** Steps 1-5 work. Steps 6-7 NOT YET IMPLEMENTED. **Final:** Full lifecycle.

### Flow H: Human Rejects

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/approvals/{id}/decisions` with `{decision: "reject"}` |
| 2-4 | Same as Flow G | Auth, self-check, expiry check |
| 5 | **Decision** | `decide_request()` sets `status=REJECTED` |
| 6 | **Response** | `ApprovalRequest` returned with `REJECTED` status |

**Success:** Rejection recorded. **Final:** Workflow stops or escalates per PRD §21.

### Flow I: Approval Expires

| Step | Component | Action |
|---|---|---|
| 1 | **Read** | Any read of approval request |
| 2 | **Lazy Expiry** | If `status=PENDING` and `expires_at <= now`, status derived as `EXPIRED` |
| 3 | **Response** | `ApprovalRequest` returned with `EXPIRED` status |

**No background sweep exists.** Expiry is derived at read time only.

### Flow J: Tool Execution Fails

| Step | Component | Action |
|---|---|---|
| 1-8 | Same as Flow C | Steps 1-8 identical |
| 9 | **Handler Failure** | Tool handler raises exception |
| 10 | **Error Type** | `ToolExecutionError` (500) |
| 11 | **Record** | `ToolExecutionRecord` with `status=FAILED` and `error_kind` persisted |
| 12 | **Skill Impact** | Skill execution STOPS immediately (no later steps run) |

**Success:** Error recorded, Skill halted.

### Flow K: Agent Reaches Execution Bound

| Step | Component | Action |
|---|---|---|
| 1 | **Agent Start** | `POST /agent/runs` |
| 2-N | **Skill Executions** | Agent executes Skills up to `MAX_AGENT_STEPS=3` |
| N+1 | **Bound Hit** | Agent attempts step 4 (exceeds MAX_AGENT_STEPS) |
| N+2 | **Stop** | Agent stops with `AgentRunStatus.MAX_STEPS_REACHED` |
| N+3 | **Response** | `AgentExecutionResult(status=MAX_STEPS_REACHED, steps=[...])` |

**Success:** Bounded execution respected.

### Flow L: Connector Ingestion

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/connectors/{id}/sync` |
| 2 | **Auth** | `connector:sync` permission required |
| 3 | **TenantContext** | Established and path-verified |
| 4 | **Provider Adapter** | GitHub/Slack/Linear adapter fetches records |
| 5 | **PII Guard** | `KnowledgeService.ingest_document()` applies PII sanitization |
| 6 | **Embedding** | `RetrievalService.prepare_index()` chunks + embeds |
| 7 | **Persistence** | Atomic transaction: document + chunks + embeddings |
| 8 | **Sync Record** | `ConnectorSyncRecord` persisted |

**Success:** Data ingested into Company Brain. **Failure:** `ConnectorSyncError` (400).

### Flow M: Webhook Reception

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /webhooks/{endpoint_id}/events` (HMAC-signed) |
| 2 | **Endpoint Resolution** | Tenant binding from environment-configured endpoint |
| 3 | **Timestamp Check** | 300s tolerance window (replay resistance) |
| 4 | **HMAC Verify** | `hmac.compare_digest` (constant-time) |
| 5 | **Payload Validate** | Size (64KB max), JSON shape, required fields |
| 6 | **Record** | `WebhookEvent` with metadata only (no raw payload stored) |
| 7 | **Current: Stop** | Event recorded; NO downstream processing |
| 8 | **Final: Trigger** | Forward to Unified Intelligence → Skill → Tool execution |

**Current:** Metadata-only recording. **Final:** Full downstream processing.

### Flow N: PII Encountered

| Step | Component | Action |
|---|---|---|
| 1 | **Ingestion Point** | Knowledge ingestion / Skill creation / Connector sync |
| 2 | **PII Guard** | `PiiGuardService.sanitize(text)` |
| 3 | **Analysis** | Presidio Analyzer detects PII entities |
| 4 | **Anonymization** | Presidio Anonymize applies operators (replace/mask/redact) |
| 5 | **Output** | Sanitized text returned; no unsanitized content persists |
| 6 | **Failure** | `PiiGuardError` raised; no partial content persisted (fail closed) |

### Flow O: Unauthorized Tenant Access

| Step | Component | Action |
|---|---|---|
| 1 | **Request** | Tenant-scoped endpoint with `tenant_id` in path |
| 2 | **TenantContext** | `TenantContextService` derives context from JWT |
| 3 | **Path Check** | `_require_path_tenant_matches_context()` compares path vs context |
| 4 | **Mismatch** | Path `tenant_id` ≠ `TenantContext.tenant_id` |
| 5 | **Response** | 403 Forbidden (indistinguishable from missing for cross-tenant) |

### Flow P: No Authorized Retrieval Context

| Step | Component | Action |
|---|---|---|
| 1-5 | Same as Flow A | Steps 1-5 identical |
| 6 | **ApprovedContext** | No tenant-scoped matches meet authorization threshold |
| 7 | **LLM** | No context provided; answer is `None` |
| 8 | **Response** | `IntelligenceAnswer(answer=None, context_used=False)` |

**Success:** No fabrication — `None` returned.

### Flow Q: LLM Provider Failure

| Step | Component | Action |
|---|---|---|
| 1-6 | Same as Flow A | Steps 1-6 identical |
| 7 | **LLM** | `LlmProvider.complete()` raises `LlmError` |
| 8 | **Propagation** | `LlmError` propagated to caller |
| 9 | **Response** | No partial answer (fail closed) |

### Flow R: Revoked Connector Credential

| Step | Component | Action |
|---|---|---|
| 1 | **Entry** | `POST /tenants/{tenant_id}/connectors/{id}/sync` |
| 2-3 | Same as Flow L | Auth + TenantContext |
| 4 | **Provider Adapter** | Adapter attempts API call with revoked credential |
| 5 | **Failure** | Provider returns 401/403 |
| 6 | **Error** | `ConnectorSyncError` with `error_kind` recorded |
| 7 | **Sync Record** | `ConnectorSyncRecord` with `status=FAILED` persisted |

---

## 32. Non-Functional Requirements

Source-supported qualitative requirements only. No invented NFRs.

### Security

| NFR | Requirement | Source | Status |
|---|---|---|---|
| S-1 | All API requests require authenticated JWT | PRD §5, TRD §9 | **Frozen** |
| S-2 | Cross-tenant access is denied at application level | PRD §5, ADR-002 | **Frozen** |
| S-3 | PII is sanitized before any AI/data boundary | PRD §12, TRD §12 | **Frozen** |
| S-4 | LLM never receives raw documents, vectors, or authorization state | PRD §14, ADR-001 | **Frozen** |
| S-5 | Tool execution requires `tool:execute` + per-tool permissions | TRD §14.2 | **Frozen** |
| S-6 | HIGH-risk tools require human approval (fail-closed until implemented) | PRD §21, TRD §17.3 | **Conditionally Frozen** |
| S-7 | Webhook payloads are verified via HMAC-SHA-256 with constant-time comparison | TRD §16.4 | **Frozen** |
| S-8 | No secrets are logged, persisted in API responses, or committed to repository | TRD §14.2, SECURITY.md | **Frozen** |

### Reliability

| NFR | Requirement | Source | Status |
|---|---|---|---|
| R-1 | Every security gate fails closed (deny on uncertainty) | §27 | **Frozen** |
| R-2 | Embedding or LLM failure propagates with no partial answer | §27 | **Frozen** |
| R-3 | Tool execution failures are recorded and halt Skill execution | TRD §14.1 | **Frozen** |
| R-4 | Approval creation failure is best-effort (logged and dropped) | §15 | **Frozen** |
| R-5 | Observability telemetry writes are best-effort (never fail business requests) | §18 | **Frozen** |

### Scalability (V1 Foundation)

| NFR | Requirement | Source | Status |
|---|---|---|---|
| SC-1 | Single-application architecture (not microservices) | TRD §4.1 | **Frozen** |
| SC-2 | Docker Compose for local development | TRD §3 | **Frozen** |
| SC-3 | PostgreSQL with pgvector for structured + vector data | TRD §3 | **Frozen** |
| SC-4 | Agent bounded to MAX_AGENT_STEPS=3 | §14 | **Frozen** |
| SC-5 | Skill bounded to MAX_TOOL_CALLS=10 | §11 | **Frozen** |

### Maintainability

| NFR | Requirement | Source | Status |
|---|---|---|---|
| M-1 | Platform-owned tool whitelist (tenants cannot register tools) | §12 | **Frozen** |
| M-2 | ADR-003 document identity for idempotent ingestion | ADR-003 | **Frozen** |
| M-3 | Ruff linting and formatting | TRD §3 | **Frozen** |
| M-4 | CI validation on every PR and push to main | TRD §3 | **Frozen** |

### Observability

| NFR | Requirement | Source | Status |
|---|---|---|---|
| O-1 | API request count, AI request count, token usage | PRD §17, TRD §17 | **Conditionally Frozen** |
| O-2 | Agent execution count, tool invocation count | PRD §17, TRD §17 | **Conditionally Frozen** |
| O-3 | Successful/failed execution tracking | PRD §17, TRD §17 | **Conditionally Frozen** |
| O-4 | Tenant usage summary | PRD §17, TRD §17 | **Frozen** |
| O-5 | Component health monitoring (database, LLM, embeddings) | TRD §17.1 | **Frozen** |
| O-6 | Agent execution trace (trigger, tenant, knowledge, skill, tools, result) | PRD §17 (agent observability) | **NOT YET IMPLEMENTED** |
| O-7 | Human escalation count | PRD §17 | **NOT YET IMPLEMENTED** |

---

## 33. Traceability Matrix

Requirements → Source → Current Implementation → Final Requirement → Status.

| Requirement | PRD | TRD | ADR | Current Implementation | Final Required | Status |
|---|---|---|---|---|---|---|
| Multi-tenancy | §5 | §9 | ADR-002 | TenantContext from JWT, cross-tenant denied | Same | **Frozen** |
| Authentication | §5 | §9 | — | HS256 JWT, sessionStorage | Same + SSO (excluded) | **Conditionally Frozen** |
| RBAC | §7 | §9 | — | 22 permissions, 4 roles | Same; Employee role conflict (C-1) | **Open Decision** |
| PII Guard | §12 | §12 | — | Presidio, 3 ingestion points | Same + webhooks + tool results | **Conditionally Frozen** |
| Company Brain | §8 | §11 | ADR-003 | Knowledge CRUD, atomic persistence | Same | **Frozen** |
| Secure RAG | §9 | §11 | ADR-001 | pgvector HNSW, ApprovedContext | Same + lexical/hybrid (deferred) | **Conditionally Frozen** |
| Skills Engine | §13 | §10 | ADR-006 | CRUD + execution, MAX_TOOL_CALLS=10 | Same + risk field + persistence | **Conditionally Frozen** |
| AI Tools | §15 | §14 | ADR-004 | 1 tool, platform-owned whitelist | Same + additional tools | **Conditionally Frozen** |
| Unified Intelligence | §14 | §8, §10 | ADR-001 | Deterministic, single tool proposal | Same + production LLM | **Conditionally Frozen** |
| AI Agent | §14 | §8, §10 | ADR-006 | Bounded orchestration, MAX_STEPS=3 | Same + memory + approval integration | **Conditionally Frozen** |
| Human Intervention | §21 | §17.3 | — | Fail-closed denial, creation + decision API | Full lifecycle + Agent integration | **NOT YET IMPLEMENTED** |
| Webhooks | §16 | §16 | — | Inbound HMAC, metadata-only | Same + downstream processing | **NOT YET IMPLEMENTED** |
| Connectors | §22 | §3 | — | GitHub/Slack/Linear, env credentials | Same + Google Drive + secret management | **Conditionally Frozen** |
| Observability | §17 | §17 | — | Aggregation, usage summary, health | Same + agent trace + escalation count | **Conditionally Frozen** |
| LLM Provider | — | §34 | ADR-001 | Deterministic only | OmniRoute → OpenRouter | **Deferred** |
| Embeddings | — | §11 | ADR-007 | Deterministic + OpenAI, 1536-dim | Same | **Frozen** |
| Database | §23 | §3 | — | 12 tables | Same + agent_runs + skill_executions (if C-4) | **Open Decision** |
| Frontend | §4 | §3 | — | 33 pages, sessionStorage | Same | **Frozen** |
| Deployment | — | §3 | — | Docker Compose, GitHub Actions CI | Same + AWS | **Deferred** |
| Testing | — | §25 | — | 13 test files, CI on PR | Same + expanded coverage | **Conditionally Frozen** |

---

## Appendix A: Permission Matrix

Full permission matrix is in §7. The 22 permissions use colon-based format:

```
tenant:create, tenant:read, user:create, membership:create,
knowledge:create, knowledge:read,
skill:create, skill:read, skill:update, skill:delete, skill:execute,
tool:read, tool:execute,
connector:create, connector:read, connector:sync,
webhook:read,
agent:execute,
approval:read, approval:decide,
observability:read, observability:platform_read
```

---

## Appendix B: Database Tables

Full schema is in `src/arc/db/schema.sql`. 12 tables total:

```
tenants, users, memberships, connector_configs,
knowledge_documents, knowledge_chunks, skills,
tool_execution_records, connector_sync_records,
webhook_events, api_request_records, approval_requests
```

---

## Appendix C: API Endpoints

Full endpoint list is in §23. 31 endpoints total across 15 resource groups. All tenant-scoped endpoints enforce `_require_path_tenant_matches_context()`. Webhook ingestion uses HMAC authentication (no RBAC).
