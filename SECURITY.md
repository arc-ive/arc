# Security Guidelines

## 1. Purpose

This document defines the initial security baseline for Arc during development.

These are engineering requirements for the project foundation.

This document does not claim that Arc is currently production-ready, compliant with any specific regulation, or certified under any security framework.

Detailed security architecture will be defined as the product requirements and architecture evolve.

## 2. Secrets

Never commit the following to Git:

- API keys
- Passwords
- Access tokens
- OAuth client secrets
- Webhook signing secrets
- Private keys
- Certificates containing private material
- Cloud credentials
- Database passwords
- Production credentials
- Customer credentials

Use environment variables or an approved secret-management mechanism.

`.env.example` may contain variable names and safe placeholders only.

Actual `.env` files must remain local and must not be committed.

## 3. Development Credentials

Development credentials must:

- Be stored outside the repository.
- Use the minimum permissions required.
- Be different from production credentials.
- Never be copied into source code.
- Never be included in screenshots or documentation.
- Never be provided to AI coding tools.

Developers should use separate credentials for separate environments where practical.

## 4. Production and Customer Data

Real production or customer data must not be used for normal development.

Do not place production/customer data in:

- Local databases
- Test fixtures
- Git repositories
- Pull Requests
- Debug logs
- Screenshots
- AI prompts
- AI context files
- Development datasets

Use synthetic or explicitly approved test data.

## 5. AI Security

AI development tools are subject to the same security expectations as other development tools.

AI tools must not receive:

- Production credentials
- Customer credentials
- Private customer documents
- Sensitive production logs
- API keys
- Passwords
- Private keys
- Unapproved personal or regulated data

AI-generated code must be reviewed by a developer before being committed or merged.

AI-generated suggestions must not override:

- Security policies
- Authorization rules
- Repository instructions
- Approved architecture decisions
- Human approval requirements

External content retrieved by AI tools should be treated as untrusted input.

## 6. Multi-Tenant Security Principle

Arc is intended to support multiple customers/tenants.

The initial security principle is:

> A tenant must not be able to access another tenant's resources, data, configuration, credentials, or operational information unless an explicitly authorized cross-tenant operation exists.

Tenant boundaries must be enforced by trusted server-side controls.

Tenant identity must not be trusted solely because it was supplied by a client.

Detailed tenant-isolation architecture will be defined through the requirements and architecture process.

## 7. Authentication and Authorization

Authentication answers:

> Who is this user or service?

Authorization answers:

> What is this identity allowed to access?

Authentication must not be treated as sufficient for resource access.

Protected APIs must perform appropriate authorization checks before accessing tenant-scoped resources.

Future authorization design must consider:

- User identity
- Organization/tenant
- Role
- Resource ownership
- Resource permissions
- Service identity
- Administrative privileges

## 8. Least Privilege

Access should follow the principle of least privilege.

Development tools, AI tools, CI workflows, services, and users should receive only the permissions required for their task.

AI development tools should initially have:

Allowed:
- Read repository files
- Search repository files
- Inspect Git state
- Run approved local tests
- Modify the local working tree with human oversight

Restricted or human-gated:
- Production database writes
- Production deployment
- Billing/financial actions
- Production credentials
- Customer data access
- Cloud-admin operations

MCP tools, when introduced, must be added individually and their permissions documented.

## 9. Logging

Logs must not expose secrets or unnecessary sensitive information.

Do not log:

- Passwords
- API keys
- Access tokens
- Private keys
- Database credentials
- Webhook secrets
- Customer document contents
- Unnecessary PII

Sensitive values must be redacted before logging.

Future structured logging should use an agreed correlation/request ID without exposing sensitive data.

## 10. Input Validation

All external input must be treated as untrusted.

Validate relevant:

- Types
- Formats
- Sizes
- Allowed values
- Resource identifiers
- Authorization context

Do not rely solely on client-side validation.

## 11. Error Handling

Errors must not reveal sensitive internal information to untrusted users.

Avoid exposing:

- Credentials
- Tokens
- Internal secrets
- Database connection details
- Sensitive stack traces
- Customer data belonging to another tenant

Detailed diagnostics should remain in appropriately controlled server-side logs.

## 12. Pull Request Security Review

Security-sensitive Pull Requests should answer the following:

- [ ] Authentication impact checked
- [ ] Authorization / tenant scope checked
- [ ] Secrets checked
- [ ] PII / data leakage checked
- [ ] Input validation checked
- [ ] Logging checked
- [ ] Error messages checked
- [ ] Dependencies checked
- [ ] Security regression test added where needed
- [ ] Relevant documentation updated

## 13. Dependencies

Dependencies should be reviewed before introduction.

Consider:

- Maintenance status
- Known vulnerabilities
- License implications
- Transitive dependencies
- Necessity of the dependency
- Whether the same capability can be implemented with an existing approved dependency

Do not introduce dependencies merely for convenience without understanding their impact.

## 14. GitHub Security

The repository should use appropriate GitHub controls including:

- Protected `main`
- Pull Requests
- Required CI checks
- Code review
- Appropriate repository permissions
- Secret scanning/security features where available and appropriate

Repository security settings should be reviewed as the project evolves.

## 15. Vulnerability Reporting

Security vulnerabilities should not be disclosed through public issue discussions.

During the private-project phase, report suspected vulnerabilities directly to the project maintainers through the team's private communication channel.

The report should contain:

- Description
- Affected component
- Reproduction steps
- Security impact
- Suggested mitigation, if known

Do not include real customer data or secrets in the report.

## 16. Security Architecture Decisions

Significant security architecture decisions must be recorded as Architecture Decision Records.

Examples include:

- Tenant-isolation strategy
- Authentication architecture
- Authorization model
- Secrets management
- AI security boundaries
- PII handling
- Data-access controls
- External integration trust boundaries

ADRs are stored in:

```text
docs/architecture/decisions/
```

## 17. Security Is a Shared Responsibility

Bala owns the Foundation security baseline and coordinates security architecture.

However, all three developers are responsible for following the security rules.

Security concerns must be raised during:

- Design
- Development
- Code review
- Testing
- CI
- Deployment preparation

Security must not be treated as a final-stage activity.