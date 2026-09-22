# Arc UX Specification

**Status:** Proposed product/UX layer for Arc V2  
**Goal:** Turn the existing Arc V2 implementation into a coherent, production-quality enterprise UX without expanding product scope.

## 1. Core UX Principles

### Product, not implementation

Never expose internal engineering state as customer-facing UX.

Do not display:
- backend contract pending
- telemetry not wired
- internal service names
- database terminology
- implementation TODOs

Use honest product states instead.

Examples:

**No records:** `No activity yet`

**Temporary loading:** `Loading activity…`

**Request failure:** `Unable to load activity. Try again.`

**Permission:** `You don't have access to this area.`

**Feature unavailable:** `This feature isn't enabled for your workspace.`

### Existing scope only

The redesign may reorganize existing pages, merge related screens, rename confusing labels, improve workflows, improve states, navigation, accessibility and responsive behavior.

It must not invent backend capabilities, create fake functionality, expand V2 scope or redesign backend architecture.

### One product, role-aware experience

All roles use the same Arc product. Permissions determine navigation visibility, available actions and data access.

Do not create completely separate visual products for employee, company administrator, and operations user application roles. (Tenant membership roles — OWNER, MEMBER, VIEWER — are a separate authorization concept, not application personas.)

## 2. Primary Workspace Experience

### Ask Arc

Ask Arc is the primary conversational entry point for normal users.

A knowledge interaction should communicate:
1. question
2. answer
3. citation/source information
4. whether company context was used

An action interaction should communicate:
1. requested action
2. proposed action
3. authorization/policy result
4. approval requirement if applicable
5. execution status
6. result/failure

Never make users infer whether something was proposed or actually executed.

### Company Brain

Company Brain is the user-facing knowledge layer.

Organize existing functionality around:
- knowledge
- sources
- connectors
- ingestion/search state
- provenance

Make clear what knowledge exists, where it came from, whether it is searchable, and whether ingestion failed.

Avoid exposing chunk IDs, embedding details, repository names or other implementation concepts unless genuinely needed.

## 3. AI Workflows

### Agents

Agent pages are configuration and operational surfaces for existing bounded Agents.

Where supported by the current backend, organize:
- identity/name
- purpose
- status
- skills
- tools
- permissions/policy information
- activity
- testing/configuration

Do not invent lifecycle capabilities that do not exist.

### Skills

Skills represent reusable business procedures.

Communicate:
- purpose
- status
- risk
- allowed capabilities
- relevant configuration
- execution/activity where available

### Tools

Tools are execution capabilities.

Do not make Tools a prominent employee-facing concept merely because tools exist in the backend. Expose tool management only where an actual user/admin workflow requires it.

## 4. Approvals

Approvals are part of an execution lifecycle.

Clearly distinguish:
- pending
- approved
- rejected
- expired
- consumed

Show what action is requested, who requested it, why approval is required, what happens if approved, and current status.

Never imply that approval itself grants authorization.

## 5. Operations

Operations should answer:

> What is happening in this workspace, and what happened recently?

Use existing activity/telemetry where available.

Possible existing areas:
- activity
- agent runs
- skill executions
- tool executions
- approvals
- connector activity
- webhook activity
- usage/AI telemetry

Do not create a dashboard full of metrics simply because metrics exist.

If a metric is unavailable, omit it, show a meaningful unavailable state, or expose it only when its data contract is real. Avoid unexplained `N/A`.

## 6. Administration

Administration should be task-oriented around existing:
- people
- access
- workspace configuration
- relevant policies/settings

Avoid exposing implementation concepts such as capability registries unless an administrator actually needs them.

## 7. Platform Control Plane

Platform administration remains separate.

Focus on existing:
- tenants
- global users
- platform configuration
- capability availability
- platform operations
- administrative visibility

Do not mix customer Company Brain data into the platform interface merely because a Platform Administrator exists.

## 8. Navigation Rules

Keep primary navigation intentionally small.

Conceptual company navigation:
- Ask Arc
- Company Brain
- AI Workflows
- Operations
- Administration

Platform has separate control-plane navigation.

Detailed capabilities belong in sub-navigation/contextual views where appropriate.

No new feature should be created to fill navigation.

## 9. State Design

Every important screen explicitly designs:

### Loading
Stable skeleton/progress state matching the eventual content.

### Empty
Explain what the area is, why it is empty, and the next legitimate action when applicable.

### Error
Explain the user-relevant problem and provide recovery where possible.

### Permission denied
Explain unavailable access without exposing security-sensitive details.

### Not configured
Explain required configuration when the user has permission to configure it.

### Success
Confirm the actual outcome. Never show success merely because a frontend click occurred.

## 10. Forms

Forms should group related information, use clear labels, validate inline, preserve input after recoverable errors, prevent duplicate submissions and show meaningful success/failure feedback.

Do not build giant forms that expose every backend field.

## 11. Tables

Use tables only where comparison/list management is useful.

Support search/filtering/pagination/sorting/status/actions where applicable. Avoid displaying database columns merely because they exist.

## 12. Accessibility

Production UX includes:
- semantic structure
- keyboard navigation
- visible focus
- accessible labels
- sufficient contrast
- accessible dialogs
- accessible tables
- meaningful screen-reader states
- non-color-only status communication

## 13. Responsive Behavior

The primary experience is enterprise web, but layouts must remain usable across common desktop/tablet widths.

Preserve navigation, readable tables, dialogs, forms, primary actions and status visibility. Do not merely shrink desktop layouts.

## 14. Design Language

Arc should feel:
- professional
- restrained
- modern
- trustworthy
- information-dense where useful
- calm
- consistent

Avoid excessive gradients, glassmorphism, glowing cards, excessive rounded containers, decorative AI effects, unnecessary animation and generic dashboard-template styling.

## 15. Backend-Incomplete Rule

The backend is still under development.

Use clean frontend boundaries:
- typed API contracts
- loading states
- empty states
- errors
- permission states
- feature availability states

Where an API does not yet exist, create a clean integration boundary rather than fake data or fake success.

Controlled reference/mock data may be used for design/testing only when clearly isolated from production behavior.

## 16. Completion Standard

A redesigned screen is complete only when it:
- fits the approved information architecture
- uses the Arc design system
- has meaningful states
- respects RBAC
- avoids implementation details
- works with current contracts
- degrades honestly when backend functionality is incomplete
- is accessible
- is browser-tested

## 17. Scope Guard

Success means Arc becomes easier to understand, navigate, use, maintain and trust.

Success does NOT mean adding more pages or features.
