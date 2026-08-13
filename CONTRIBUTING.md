# Contributing to Arc

## 1. Purpose

This document defines the engineering workflow for contributing to Arc.

The goal is to ensure that all three developers follow the same development, review, testing, documentation, and merge process.

## 2. Core Development Workflow

Every meaningful change should follow:

```text
Linear Issue
    ↓
GitHub Branch
    ↓
Commit(s)
    ↓
Pull Request
    ↓
CI
    ↓
Code Review
    ↓
Merge
    ↓
Documentation / State Update
```

The exact workflow may be refined as the Foundation Phase progresses, but changes must not bypass the agreed engineering controls.

## 3. GitHub Issues

Every meaningful engineering task should have a corresponding work item.

The work item should describe:

- Problem
- Goal
- Scope
- Dependencies
- Acceptance criteria
- Security considerations
- Testing expectations
- Owner

Avoid vague work items such as:

- Build RAG
- Fix backend
- Improve AI

Prefer specific outcomes such as:

- Define the permission model required for tenant-scoped document retrieval.
- Add tests proving one tenant cannot access another tenant's resources.

Linear is used for team work management.

GitHub Issues and Pull Requests provide the engineering traceability required for implementation and review.

## 4. Branch Naming

Use the following branch naming convention:

```text
feature/<short-name>
fix/<short-name>
chore/<short-name>
docs/<short-name>
```

Examples:

```text
feature/tenant-context
fix/auth-token-validation
chore/repository-foundation
docs/ai-development-setup
```

Do not use personal or ambiguous branch names such as:

```text
bala
joe-work
test
new
final
```

## 5. Main Branch

`main` is the primary integration branch.

Normal development must not occur directly on `main`.

Changes should reach `main` through a Pull Request.

The repository has a configured branch-protection policy for `main`. Enforcement of that policy currently depends on GitHub repository and organization plan capabilities.

Force-pushing to `main` is prohibited by team policy.

Deleting `main` is prohibited by team policy.

## 6. Commits

Commits should be:

- Small
- Focused
- Descriptive
- Related to the current task

Preferred format:

```text
type: short description
```

Examples:

```text
chore: initialize repository foundation
docs: add AI development guidelines
fix: validate tenant context
feat: add connector retry policy
test: add tenant isolation tests
```

Avoid vague commit messages such as:

```text
update
changes
stuff
final
working
test
```

## 7. Pull Requests

Every meaningful code, configuration, architecture, or engineering change should go through a Pull Request.

A Pull Request should clearly explain:

### What changed?

Describe the implementation or documentation change.

### Why?

Explain the problem or requirement being addressed.

### Scope

Identify the affected files, components, or systems.

### Testing

Describe the tests or verification performed.

### Security impact

Explain security implications when the change affects:

- Authentication
- Authorization
- Tenant isolation
- Customer data
- Secrets
- AI
- External integrations
- Logging

### Additional information

Attach screenshots, logs, or other evidence when useful.

Document migrations, deployment implications, or configuration changes where applicable.

## 8. Pull Request Checklist

Before requesting review:

- [ ] Related issue/work item is linked.
- [ ] Scope is clearly described.
- [ ] Tests are described.
- [ ] Relevant tests pass.
- [ ] Security impact has been considered.
- [ ] No secrets are included.
- [ ] No unrelated changes are included.
- [ ] Documentation is updated when required.
- [ ] CI passes.
- [ ] Architecture changes have an ADR when required.

## 9. Code Review

Reviewers should evaluate:

- Correctness
- Scope
- Maintainability
- Tests
- Security
- Authorization
- Tenant-isolation implications
- Data handling
- Error handling
- Logging
- Documentation

Reviewers should challenge assumptions rather than approving changes only because the implementation appears to work.

## 10. CI

Required CI checks must pass before a Pull Request is merged.

If CI fails:

1. Understand the failure.
2. Reproduce it locally where practical.
3. Fix the underlying problem.
4. Run the relevant checks again.
5. Push the correction.
6. Request another review when necessary.

CI is an independent quality gate and should not be treated as optional.

## 11. Architecture Decisions

Significant architecture, infrastructure, data, security, or AI-routing decisions must be recorded through an Architecture Decision Record.

ADRs are stored in:

```text
docs/architecture/decisions/
```

Do not silently change an important architectural contract.

Do not create ADRs for trivial implementation details.

When an ADR becomes obsolete, supersede it rather than silently deleting the historical decision.

## 12. AI-Assisted Development

AI coding tools may be used during development.

However:

- Developers remain responsible for generated code.
- AI-generated code must be reviewed before merging.
- AI must not receive production credentials.
- AI must not receive customer secrets.
- AI must not receive sensitive production/customer data.
- AI output must not override repository security or architectural rules.
- Important project knowledge must be stored in the repository.
- Significant architectural decisions must be recorded through ADRs.

AI tools are development aids, not sources of truth.

## 13. Documentation

Update documentation when a change affects:

- Repository setup
- Development workflow
- Architecture
- Security
- Operations
- AI development
- Configuration
- Developer commands
- Important project state

Documentation changes should normally be included in the same Pull Request as the change they describe.

## 14. Keep Changes Focused

Avoid mixing unrelated work into the same Pull Request.

A focused Pull Request is easier to:

- Review
- Test
- Revert
- Understand
- Debug

## 15. Cross-Owner Changes

If a change crosses another developer's ownership boundary, involve that owner before changing the relevant contract.

Examples:

Bala → Bharath:
Architecture changes affecting services, Docker, CI, or local infrastructure.

Bala → Joe:
Technical constraints affecting product requirements or roadmap decisions.

Bharath → Bala:
Infrastructure or environment decisions affecting architecture.

Joe → Bala:
Requirements requiring technical feasibility or architecture validation.

## 16. Source of Truth

The team should not allow important engineering decisions to exist only in:

- Private AI conversations
- WhatsApp
- Discord
- Personal notes

Important project knowledge should be committed to the appropriate repository documentation, GitHub issue, Pull Request, or ADR.

## 17. Responsibility

Every developer is responsible for:

- Following the Git workflow
- Reviewing teammate work
- Running appropriate tests
- Protecting secrets
- Keeping documentation accurate
- Reporting blockers
- Raising architectural or security concerns