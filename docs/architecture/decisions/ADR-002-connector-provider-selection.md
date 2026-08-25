# ADR-002: Connector Provider Selection

## Status

Accepted

## Date

2026-08-19

## Decision Owners

- Arc Maintainers

## Context

Arc is an enterprise multi-tenant AI platform in Foundation Phase / Sprint 0. The following foundations are merged on `main`:

- X-10 tenancy foundations.
- X-11 authentication and authorization (JWT-based `AuthenticatedPrincipal`, `ApplicationRole`, permission matrix).
- X-13 tenant-aware connector foundation: `ConnectorProvider` and `ConnectorStatus` domain enums, `ConnectorConfig`, `ConnectorService` (trusted `TenantContext` only), tenant-scoped `PostgreSQLConnectorRepository`, the `connector_configs` table with `UNIQUE(tenant_id, provider, name)`, and a passing test suite.

The `ConnectorProvider` enum defines four candidates: GitHub, Slack, Google Drive, and Linear. ADR-001 explicitly left connector selection as an open implementation decision; this ADR resolves that item.

Product requirements constrain the decision:

- PRD §22: Arc may integrate with 2–3 practical external systems where free/open-source or controlled APIs are available. Connector selection is based on ease of integration, cost, usefulness to the demonstration, and ability to support company knowledge or operational workflows. Connector-specific technical decisions are implementation decisions and should not unnecessarily expand infrastructure.
- TRD §33: The project may use approximately 2–3 useful real connectors where they are free, easy to integrate, and useful for demonstrating the product. Controlled/fake APIs are acceptable where real integrations introduce unnecessary complexity or cost. Connector selection remains an implementation planning decision and should not dictate unnecessary platform infrastructure.

The PRD states approximately 2–3 practical external systems. This ADR commits to 3 as the implementation target. Google Drive is recorded as a conditional 4th connector that is only considered if it later proves genuinely practical under the documented criteria. The fourth connector is not mandatory and is not an expansion of the committed scope.

This ADR records provider selection only. It does not implement OAuth flows, provider API clients, credential storage, synchronization, webhooks, background jobs, or provider-specific code.

## Decision

Arc commits to GitHub, Slack, and Linear as the primary connector implementation target, with a minimum of 3 practical connectors.

Google Drive is a conditional 4th connector. It will be considered only if it proves genuinely practical under the documented selection criteria after the primary three are delivered. It must not be treated as mandatory.

Provider selection follows the documented selection criteria, which operationalize PRD §22 and TRD §33:

- API accessibility
- Free/accessible development and demo usage
- OAuth/authentication complexity
- Company Brain/company knowledge usefulness
- Operational workflow usefulness
- Integration complexity
- Tenant isolation compatibility
- X-11 compatibility
- PII Guard boundary compatibility
- Avoidance of unnecessary infrastructure
- Maintainability
- Demonstration suitability
- Paid API/infrastructure requirements

GitHub, Slack, and Linear are implementation candidates selected through this engineering decision; they are not mandated by the PRD or TRD. Future connectors are not excluded, but they must be justified against the same criteria before adoption.

## Options Considered

### Option 1 — Select GitHub, Slack, and Linear now, with Google Drive conditional

Description: Commit to the three primary connectors and record Google Drive as a conditional fourth subject to the documented criteria.

Advantages:

- Meets the PRD's 2–3 practical system guidance with a committed target of 3.
- GitHub, Slack, and Linear all offer free tiers suitable for development and demonstration.
- Covers both company knowledge (GitHub repositories and documentation) and operational workflows (Slack channels and messages, Linear issues).
- Avoids the Google Cloud project and OAuth consent-screen setup overhead while Google Drive remains available if practical.
- Does not expand platform infrastructure.

Disadvantages:

- Google Drive document knowledge is not part of the committed scope unless it later proves practical.
- Demonstration breadth is limited to three providers.

### Option 2 — Select all four connectors now

Description: Commit to GitHub, Slack, Linear, and Google Drive as an unconditional implementation target.

Advantages:

- Broader provider coverage, including document-based company knowledge.
- A single decision covers every candidate in the current `ConnectorProvider` enum.

Disadvantages:

- Exceeds the approximately 2–3 systems described by the PRD and TRD.
- Google Drive integration requires a Google Cloud project and OAuth consent-screen setup, adding configuration and demonstration friction.
- Expands implementation scope and cost without a corresponding committed product requirement.

### Option 3 — Defer connector selection

Description: Keep connector selection open and make no selection in this ADR.

Advantages:

- No commitment until provider integrations are imminent.

Disadvantages:

- ADR-001 lists connector selection as an open decision; deferral leaves the last open item before the ingestion/Company Brain phase unresolved.
- Provider planning for the next phase cannot proceed with a defined target.
- Contradicts the product requirement to move toward practical external integrations.

### Provider Comparison

#### GitHub

- API accessibility: Public REST/GraphQL APIs are freely accessible.
- Free/accessible development and demo usage: Free accounts and repositories support development and demonstration.
- OAuth/authentication complexity: Low; fine-grained personal access tokens or OAuth are available for a controlled demo setup.
- Company Brain/company knowledge usefulness: High; repositories and documentation are natural company knowledge sources.
- Operational workflow usefulness: Moderate; issues and pull requests support operational workflows.
- Integration complexity: Low.
- Tenant isolation compatibility: Compatible; provider data remains associated with a tenant through the existing tenant-scoped repository boundary.
- X-11 compatibility: Compatible; no new permissions required.
- PII Guard boundary compatibility: Compatible; data enters through the ingestion/validation and PII boundary.
- Avoidance of unnecessary infrastructure: No additional infrastructure required.
- Maintainability: High; widely documented APIs and SDKs.
- Demonstration suitability: High.
- Paid API/infrastructure requirements: None for the committed scope.

#### Slack

- API accessibility: Public API with free workspace tiers.
- Free/accessible development and demo usage: Free workspaces support development and demonstration.
- OAuth/authentication complexity: Moderate; requires a Slack app and OAuth setup.
- Company Brain/company knowledge usefulness: Moderate; channels and messages are useful company knowledge sources.
- Operational workflow usefulness: High; channels and messages represent operational workflows directly.
- Integration complexity: Moderate.
- Tenant isolation compatibility: Compatible; provider data remains tenant-scoped through the existing repository boundary.
- X-11 compatibility: Compatible; no new permissions required.
- PII Guard boundary compatibility: Compatible; message content passes through the ingestion/validation and PII boundary.
- Avoidance of unnecessary infrastructure: No additional infrastructure required.
- Maintainability: High; documented API.
- Demonstration suitability: High; familiar and visible in demonstrations.
- Paid API/infrastructure requirements: None for the committed scope.

#### Linear

- API accessibility: Public API with a free plan.
- Free/accessible development and demo usage: Free plans support development and demonstration.
- OAuth/authentication complexity: Low; token-based access avoids an OAuth consent screen.
- Company Brain/company knowledge usefulness: Moderate; issues are company knowledge sources.
- Operational workflow usefulness: High; issues represent operational workflows directly.
- Integration complexity: Low.
- Tenant isolation compatibility: Compatible; provider data remains tenant-scoped through the existing repository boundary.
- X-11 compatibility: Compatible; no new permissions required.
- PII Guard boundary compatibility: Compatible; issue content passes through the ingestion/validation and PII boundary.
- Avoidance of unnecessary infrastructure: No additional infrastructure required.
- Maintainability: High; simple documented API.
- Demonstration suitability: High.
- Paid API/infrastructure requirements: None for the committed scope.

#### Google Drive

- API accessibility: Public API but requires a Google Cloud project.
- Free/accessible development and demo usage: Free Google accounts support development and demonstration.
- OAuth/authentication complexity: Higher; requires a Google Cloud project and OAuth consent-screen configuration.
- Company Brain/company knowledge usefulness: High; documents are a natural company knowledge source.
- Operational workflow usefulness: Moderate; documents support operational workflows.
- Integration complexity: Moderate to high due to project and consent-screen setup.
- Tenant isolation compatibility: Compatible; provider data remains tenant-scoped through the existing repository boundary.
- X-11 compatibility: Compatible; no new permissions required.
- PII Guard boundary compatibility: Compatible; document content passes through the ingestion/validation and PII boundary.
- Avoidance of unnecessary infrastructure: No additional infrastructure required, but Google Cloud project configuration is external setup.
- Maintainability: Moderate; documented API with a greater setup surface.
- Demonstration suitability: Moderate; setup friction can delay demonstrations.
- Paid API/infrastructure requirements: None for the committed scope, but Google Cloud project administration is required.

## Rationale

- GitHub, Slack, and Linear satisfy the PRD and TRD criteria: they are free for development and demonstration, easy to integrate, and useful for demonstrating the product.
- The trio covers both required workflow types: company knowledge (GitHub repositories and documentation) and operational workflows (Slack channels and messages, Linear issues).
- The trio avoids Google Drive's Google Cloud project and OAuth consent-screen overhead while keeping the door open for a conditional fourth connector.
- Three connectors satisfy the PRD's approximately 2–3 practical external systems guidance with a committed target.
- Google Drive is retained as a conditional option rather than excluded, preserving the option to add document knowledge if it later proves genuinely practical under the documented criteria.
- The selection criteria are deliberately aligned with PRD §22 and TRD §33 so future connectors are evaluated consistently.
- The decision keeps the current implementation untouched: provider selection is a planning decision, not a code change.

## Consequences

### Positive

- Resolves the connector selection item left open by ADR-001.
- Provides a committed target of 3 practical connectors within the PRD's approximately 2–3 system guidance.
- Covers company knowledge and operational workflows with free, demo-suitable providers.
- Keeps platform infrastructure unchanged.
- Establishes reusable criteria for evaluating future connectors.
- Provides a defined basis for the next implementation phase (ingestion and Company Brain).

### Negative

- Google Drive document knowledge is not committed unless it later proves practical.
- Demonstration breadth is limited to three providers.
- Slack requires a Slack app and OAuth setup during implementation.

### Risks

- Free-tier API changes or rate limits could affect a chosen provider.
- A chosen provider could prove impractical during implementation; TRD §33 permits controlled/fake APIs as a fallback.
- Provider API changes could require connector maintenance over time.
- Google Drive, if pursued later, could introduce Google Cloud project and consent-screen setup friction.

## Security Considerations

- The current X-11 permission matrix defines only `tenant:create`, `user:create`, `membership:create`, and `tenant:read`. This ADR does not invent connector permissions; provider selection does not depend on permissions that do not exist.
- No second authentication system is introduced. Connector provider selection sits behind the existing X-11 JWT-based authentication and authorization.
- No connector-specific tenant context is introduced. The existing trust chain is preserved:

```text
Authenticated Principal
    -> X-11 authorization
    -> trusted TenantContext
    -> ConnectorService
    -> tenant-scoped ConnectorRepository
    -> persistence
    -> future provider integration
    -> future PII/data-processing boundary
```

- No credentials or secrets are proposed inside `ConnectorConfig`. Credential handling for future provider integrations remains a separate design decision.
- Tenant isolation is preserved: provider data remains tenant-scoped through the existing repository boundary; cross-tenant data cannot enter another tenant's context.
- ADR-001 requires connector data to pass through ingestion, validation, and applicable PII/security controls (PII Guard, approved technology Microsoft Presidio) before Company Brain/Unified Intelligence processing. Provider selection is compatible with this boundary.
- This ADR does not authorize external network access, OAuth flows, or provider API calls.

## Operational Considerations

- The committed connectors operate on free tiers, with no new containers, infrastructure, or paid services required.
- Google Drive, if pursued later, would add Google Cloud project and OAuth consent-screen administration to operational setup.
- Future provider integration must remain proportional to the 7-day scope, as required by ADR-001.

## Testing / Validation

- This ADR is a documentation-only decision; it makes no code changes.
- Validity will be confirmed during the provider integration phase by demonstrating that each committed provider is accessible on a free tier, integrates behind the existing X-11 authorization and `TenantContext` boundary, and preserves tenant isolation.
- The existing connector test suite remains the baseline for connector behavior; it is unaffected by this decision.
- Provider integrations must demonstrate that data passes through the ingestion/validation and PII boundary before Company Brain/Unified Intelligence processing.

## Related Documents

- ADR-001: Arc Unified Intelligence Architecture
- PRD §22 (Connectors)
- TRD §33 (External Integrations)
- ADR_TEMPLATE.md

## Related Work

- Linear: None verified in the repository; no issue numbers exist for this decision.
- GitHub:
  - PR #17 (X-13 tenant-aware connector foundation, merged)
  - PR #19 (X-11 authentication and authorization, merged)

## Supersedes

This ADR does not supersede an existing ADR. It resolves the connector selection item left open by ADR-001.

## Superseded By

None.
