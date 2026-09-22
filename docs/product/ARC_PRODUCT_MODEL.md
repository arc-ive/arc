# Arc Product Model

**Status:** Proposed product/UX layer for Arc V2  
**Purpose:** Define how the existing Arc V2 capabilities are presented as a coherent enterprise product.  
**Scope:** Product structure and information architecture only. This does not add backend capabilities or change V2 technical architecture.

## 1. Authority

The existing Arc V2 PRD, TRD and ADRs remain authoritative for product scope, architecture, security and implementation constraints.

This document adds the missing product/UX layer: how existing capabilities are organized and presented.

Authority order remains:

1. V2 ADRs
2. V2 TRD
3. V2 PRD
4. This product/UX layer
5. Frontend implementation

Do not use this document to justify adding a capability that V2 does not already require.

## 2. Product Model

Arc has two product scopes:

### Platform

For Arc operators responsible for the Arc platform:
- tenant lifecycle administration
- global user directory
- platform-level operational visibility
- global capability availability/configuration
- platform configuration
- administrative visibility

Platform administration must not automatically imply unrestricted access to customer business data.

### Company Workspace

For a customer organization using Arc.

Existing V2 capabilities are organized around user jobs rather than backend services:

- **Ask Arc** — primary conversational entry point
- **Company Brain** — company knowledge and its sources
- **AI Workflows** — existing Skills and Agents presented as business workflows
- **Operations** — existing operational activity, executions, approvals and relevant telemetry
- **Administration** — people, access and tenant/workspace configuration

These are information-architecture groupings, not new backend services.

## 3. Existing Capability Placement

### Ask Arc

Primary employee-facing entry point.

It may use existing:
- Company Brain / RAG
- Skills
- Tools
- bounded Agents
- authorization and execution policy

The UI must distinguish knowledge answers, proposed actions, executed actions, approval-required actions, denied actions and failures.

### Company Brain

Groups existing:
- direct knowledge
- connector-sourced knowledge
- ingestion status
- retrieval/search
- source/provenance

Knowledge and Connectors should not automatically become unrelated top-level concepts when they serve the same Company Brain workflow.

### AI Workflows

Groups existing:
- Agents
- Skills
- relevant workflow configuration

Tools remain execution infrastructure and should only be exposed prominently where an actual user/admin workflow requires tool management.

### Operations

Groups existing operational information such as:
- activity
- Agent runs
- Skill executions
- Tool executions where appropriate
- approvals
- connector activity
- webhook activity
- usage/AI telemetry where available

Present operational outcomes, not raw database/service concepts.

### Administration

Groups existing:
- users/people
- access/RBAC-related management
- tenant/workspace configuration
- relevant policies/settings

### Platform

Remains separate from company workspace.

## 4. Navigation Principles

1. Do not expose every backend service as a sidebar item.
2. A backend endpoint does not automatically deserve a UI page.
3. A feature should be visible only when it has a meaningful user purpose and belongs to approved V2 scope.
4. Prefer contextual/sub-navigation over additional top-level items.
5. Use role/permission-aware visibility rather than separate applications for each role.
6. Keep platform administration separate from customer workspace administration.
7. Hide unfinished or non-user-facing infrastructure rather than exposing development status.
8. Do not add navigation merely to make the application look feature-rich.

## 5. Role Model

Existing V2 roles remain the source of truth. The authoritative
application roles (`ApplicationRole`) are:

- platform_administrator
- company_administrator
- operations_user
- employee
- webhook_processor

`webhook_processor` is a synthetic, non-interactive service role for
webhook-triggered downstream execution — not a human persona, so the
frontend redesign must not present it as one.

Tenant membership roles (`OWNER`, `MEMBER`, `VIEWER`) are a separate
authorization concept. The two role systems are intentionally
independent with no mapping between them, and they must not be merged:
"Viewer" is a tenant membership role, never an application role.

These are permission/persona configurations within one coherent product, not five separate applications.

The frontend should derive visible actions and navigation from the existing authorization model.

Do not invent new roles during the frontend redesign.

## 6. Product Surface Rule

Every screen must answer:

- Who uses this?
- What job are they accomplishing?
- What existing Arc capability enables that job?
- What information/action is required?
- What happens on success?
- What happens when there is no data?
- What happens on failure?
- What happens when the user lacks permission?

If these questions cannot be answered, the screen should not be exposed as a finished product surface.

## 7. Explicit Non-Goals

This product model does NOT introduce:
- billing
- marketplace
- additional connectors
- agent memory
- new workflow engines
- new analytics systems
- new AI capabilities
- new backend services
- microservices
- new infrastructure

The objective is organization and presentation of existing V2 scope.
