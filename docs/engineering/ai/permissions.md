# Arc AI Development Permissions

## Status

Foundation Phase / Sprint 0

This document defines the initial permission boundary for AI-assisted development in Arc.

It complements:

- `SECURITY.md`
- `docs/engineering/ai/security.md`
- `docs/engineering/ai/architecture.md`

This document defines what AI tools may do, what requires human approval, and what remains outside the normal AI development boundary.

---

## 1. Purpose

The Arc AI development environment follows least privilege.

The intended principle is:

```text
Required capability
    ↓
Minimum necessary permission
    ↓
Documented boundary
    ↓
Human approval for elevated actions
```

AI model capability does not determine permission.

A more capable model does not automatically receive broader access.

---

## 2. Permission Levels

Arc uses three practical permission levels:

```text
ALLOWED
    ↓
Available within normal AI-assisted development

HUMAN-GATED
    ↓
Possible only with explicit developer approval

PROHIBITED
    ↓
Outside the normal AI development environment
```

These labels apply to both built-in agent capabilities and additional tools such as MCP servers.

---

## 3. Repository Access

### 3.1 Read Repository

Status:

```text
ALLOWED
```

AI may:

- Read repository files.
- Search repository files.
- Inspect documentation.
- Inspect source code.
- Inspect tests.
- Inspect configuration that is safe to access.
- Inspect Git history.

AI must not intentionally read secrets or unnecessary sensitive local files.

---

### 3.2 Modify Local Working Tree

Status:

```text
ALLOWED
```

AI may modify files within the scope of an approved development task.

Examples:

- Source code
- Tests
- Documentation
- Development configuration
- Local repository artifacts required for the task

The developer must review the resulting diff before commit.

---

### 3.3 Delete Repository Files

Status:

```text
HUMAN-GATED
```

Deletion of files may be proposed or performed only when the task clearly requires it and the developer has approved the resulting change.

Destructive deletion outside the task scope is prohibited.

---

## 4. Git Permissions

### 4.1 Read Git History

Status:

```text
ALLOWED
```

AI may use:

```text
git log
git show
git blame
git diff
```

and equivalent read-only Git operations to understand project history.

---

### 4.2 Create or Switch Branches

Status:

```text
HUMAN-GATED
```

AI may assist with branch creation when the developer has explicitly requested the branch operation.

The branch must follow `CONTRIBUTING.md`.

---

### 4.3 Create Commits

Status:

```text
HUMAN-GATED
```

The developer should review:

```text
git status
git diff
git diff --check
```

before creating a commit.

AI may prepare a commit message.

The developer remains responsible for the final commit.

---

### 4.4 Push to Remote

Status:

```text
HUMAN-GATED
```

AI should not push changes to remote repositories without explicit developer approval.

The developer must confirm:

- Correct branch
- Correct remote
- Correct files
- No secrets
- Appropriate commit state

---

### 4.5 Open Pull Requests

Status:

```text
HUMAN-GATED
```

AI may prepare the PR title/body and verification summary.

The developer remains responsible for opening or approving the PR.

---

### 4.6 Merge Pull Requests

Status:

```text
HUMAN-GATED
```

AI must not independently merge a Pull Request.

Merge requires the repository's normal human review process.

---

## 5. Local Command Execution

### 5.1 Safe Development Commands

Status:

```text
ALLOWED
```

AI may run local commands required for development, such as:

- Tests
- Linters
- Formatters
- Type checks
- Build verification
- Repository inspection
- Local development servers
- Non-destructive diagnostics

---

### 5.2 Destructive Local Commands

Status:

```text
HUMAN-GATED
```

Examples:

```text
Delete files
Reset repository state
Clean large sets of untracked files
Drop local databases
Destroy development containers
Overwrite local configuration
```

The AI must clearly state the consequences before such operations are executed.

---

## 6. Credentials

### 6.1 Reading Credentials

Status:

```text
PROHIBITED
```

AI should not read or expose:

- API keys
- Passwords
- Access tokens
- Private keys
- Production credentials
- Customer credentials
- Authentication cookies
- Certificates

The existence of a credential on the developer machine does not authorize AI access to it.

---

### 6.2 Using Development Credentials

Status:

```text
PROHIBITED
```

AI agents must not read, copy, paste, expose, or otherwise receive development credentials.

Development tools may use locally configured credentials through their approved credential mechanisms without exposing those credentials to the AI agent.

---

### 6.3 Production Credentials

Status:

```text
PROHIBITED
```

Production credentials must not be made available to normal development AI tools.

---

## 7. Data Access

### 7.1 Synthetic Development Data

Status:

```text
ALLOWED
```

Synthetic data may be used for:

- Development
- Testing
- Benchmarking
- Debugging
- Demonstrations

---

### 7.2 Customer Data

Status:

```text
PROHIBITED
```

Development AI tools must not receive customer data unless an explicit approved security process authorizes a specific use.

---

### 7.3 Production Data

Status:

```text
PROHIBITED
```

Production data must not be supplied to the normal development AI environment.

---

## 8. Network Access

### 8.1 Required Development Services

Status:

```text
ALLOWED
```

AI may access services required for the approved development task.

Examples may include:

- Local OmniRoute
- Approved model gateway
- Public package registries
- Public technical documentation

---

### 8.2 Arbitrary External Systems

Status:

```text
HUMAN-GATED
```

Access to external systems should be limited to the task's requirements.

The developer should understand:

- What system is being accessed.
- Why it is required.
- What data is transmitted.
- What credentials are used.
- Whether the operation changes external state.

---

### 8.3 Production Network Access

Status:

```text
PROHIBITED
```

Normal AI-assisted development must not have unrestricted production network access.

---

## 9. Cloud Permissions

### 9.1 Read-Only Cloud Inspection

Status:

```text
HUMAN-GATED
```

Read-only cloud inspection may be allowed when necessary for a specific engineering task.

The scope should be limited to the required resources.

---

### 9.2 Cloud Resource Modification

Status:

```text
HUMAN-GATED
```

Examples:

- Creating resources
- Updating infrastructure
- Changing security groups
- Modifying IAM
- Changing networking
- Changing configuration

The developer must explicitly approve these actions.

---

### 9.3 Destructive Cloud Operations

Status:

```text
PROHIBITED
```

Examples:

- Deleting production resources
- Dropping production databases
- Destroying infrastructure
- Disabling security controls
- Removing audit data

Such operations must remain outside autonomous AI permissions.

---

## 10. Production Deployment

Status:

```text
PROHIBITED
```

The normal AI development environment must not independently deploy to production.

A human-controlled deployment pipeline must remain the authority for production release.

AI may assist with:

- Deployment preparation
- Configuration review
- Release documentation
- Pre-deployment checks

but may not independently trigger unrestricted production deployment.

---

## 11. Database Permissions

### 11.1 Local Development Database

Status:

```text
ALLOWED
```

AI may interact with a local development database when required for development.

The database should contain synthetic or approved non-production data.

---

### 11.2 Production Database Read

Status:

```text
PROHIBITED
```

Normal development AI tools should not access production databases.

---

### 11.3 Production Database Write

Status:

```text
PROHIBITED
```

Production database writes are outside the normal AI development permission boundary.

---

## 12. MCP Server Permissions

MCP servers must be reviewed individually before enabling them.

Every MCP server must have documented:

```text
Purpose:
Data Access:
Read Permissions:
Write Permissions:
External Systems:
Credentials:
Security Risks:
Owner:
Approval:
```

An MCP server must not be enabled merely because it is convenient.

---

## 13. MCP Default Policy

The default state for a new MCP server is:

```text
PROHIBITED
```

It may be moved to:

```text
ALLOWED
```

or:

```text
HUMAN-GATED
```

only after its purpose and permissions are reviewed.

---

## 14. File-System Scope

The AI agent should primarily operate within:

```text
Arc repository
```

Access to unrelated directories should be avoided unless explicitly required.

Sensitive directories should remain outside normal AI access.

Examples:

```text
Credential stores
Private certificates
Personal documents
Customer data directories
Production configuration
```

---

## 15. Environment Variables

### Safe Development Variables

Status:

```text
ALLOWED
```

Non-secret configuration values may be used when required.

Examples:

```text
APP_ENV

Local service URLs

Non-secret feature flags
```

---

### Secret Environment Variables

Status:

```text
PROHIBITED
```

AI should not expose or intentionally inspect:

```text
API keys
tokens
passwords
private credentials
```

The environment may contain such variables for local tooling without granting the AI agent authority to read or disclose them.

---

## 16. Model Permissions

Model selection and permission selection are independent.

For example:

```text
Primary Model
    ↓
Local repository access

Review Model
    ↓
Local repository access

Fast Model
    ↓
Local repository access
```

A model's benchmark score does not grant it additional authority.

---

## 17. Human-Gated Operations

The following require explicit human approval:

- Commit creation
- Remote push
- Pull Request opening
- Pull Request merge
- Destructive local operations
- External system writes
- Cloud modifications
- Security-sensitive configuration changes
- Architecture-changing operations

---

## 18. Prohibited Operations

The following remain outside the normal AI permission boundary:

- Production credential access
- Customer-data access
- Production database writes
- Unrestricted production deployment
- Destructive production operations
- Unrestricted cloud administration
- Credential exfiltration
- Security-control bypass
- Unauthorized tenant-data access

---

## 19. Permission Review Before Tool Use

Before enabling a new capability, ask:

```text
Why is this capability required?

What data can it access?

Can it modify data?

Can it reach external systems?

What credentials does it use?

What is the minimum permission required?

What happens if the tool is compromised?

Who approves the capability?
```

If these questions cannot be answered, the capability should remain disabled.

---

## 20. Permission Change Process

A new AI capability should follow:

```text
Need identified
    ↓
Capability defined
    ↓
Security impact reviewed
    ↓
Minimum permission established
    ↓
Human approval
    ↓
Documentation updated
    ↓
Capability enabled
```

Permission changes must be traceable through the normal engineering workflow.

---

## 21. Review and Audit

AI permissions should be reviewed when:

- A new MCP server is introduced.
- A new external integration is introduced.
- AI gains a new class of tool access.
- Production access is proposed.
- Security requirements change.
- The project architecture materially changes.

Unused capabilities should be removed.

---

## 22. Initial Arc Permission Matrix

| Capability | Initial Status | Notes |
|---|---|---|
| Read Arc repository | ALLOWED | Required for development |
| Search repository | ALLOWED | Required for context |
| Inspect Git history | ALLOWED | Required for engineering context |
| Run local tests | ALLOWED | Normal development |
| Run local tooling | ALLOWED | Within task scope |
| Modify working tree | ALLOWED | Developer reviews diff |
| Create branch | HUMAN-GATED | Follow contribution rules |
| Create commit | HUMAN-GATED | Developer reviews staged changes |
| Push remote branch | HUMAN-GATED | Explicit developer approval |
| Open Pull Request | HUMAN-GATED | Normal GitHub workflow |
| Merge Pull Request | HUMAN-GATED | Human review required |
| Read development secrets | PROHIBITED | Never expose credentials |
| Use development credentials | PROHIBITED | AI must not receive credentials |
| Read customer data | PROHIBITED | Use synthetic data |
| Read production data | PROHIBITED | Outside development boundary |
| Write production data | PROHIBITED | Outside AI boundary |
| Production deployment | PROHIBITED | Human-controlled workflow |
| Destructive cloud action | PROHIBITED | No autonomous access |
| New MCP server | PROHIBITED | Requires review |
| Approved MCP server | HUMAN-GATED | Explicit permission scope |
| Local development database | ALLOWED | Synthetic/non-production data |
| Production database | PROHIBITED | No normal AI access |

---

## 23. Current X-9 Boundary

The initial X-9 AI environment should operate primarily within:

```text
Arc repository
    ↓
Local development environment
    ↓
Approved AI tools
    ↓
Approved downstream model providers
```

No production capability is required to satisfy X-9.

The Foundation objective is to establish a secure development workflow, not autonomous production operation.

---

## 24. Verification Checklist

- [ ] Repository read access verified.
- [ ] Repository write boundary verified.
- [ ] Git workflow boundary verified.
- [ ] Local command boundary verified.
- [ ] Secret boundary verified.
- [ ] Customer-data boundary verified.
- [ ] Production-data boundary verified.
- [ ] Cloud-operation boundary verified.
- [ ] MCP policy documented.
- [ ] Human-gated operations documented.
- [ ] Prohibited operations documented.
- [ ] Permission matrix reviewed.
- [ ] Any enabled external tools have documented permissions.

---

## 25. Completion Criteria

This permission policy is complete when:

- [ ] Allowed AI capabilities are documented.
- [ ] Human-gated capabilities are documented.
- [ ] Prohibited capabilities are documented.
- [ ] Git permissions are documented.
- [ ] Local-command permissions are documented.
- [ ] Credential boundaries are documented.
- [ ] Data-access boundaries are documented.
- [ ] Cloud boundaries are documented.
- [ ] MCP permissions are documented.
- [ ] The initial permission matrix has been reviewed.

---

## 26. Summary

Arc follows a least-privilege AI development model:

```text
Read
    ↓
Reason
    ↓
Develop locally
    ↓
Verify
    ↓
Human review
    ↓
Controlled engineering workflow
```

AI agents are not autonomous production administrators.

The default policy is:

```text
Development capability → Allowed where necessary
External modification  → Human-gated
Production access      → Prohibited
New tools              → Reviewed before use
```

These boundaries may become more specific as Arc's product architecture and operational requirements mature, but expanding AI permissions requires explicit engineering and security review.