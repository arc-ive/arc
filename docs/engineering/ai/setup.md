# Arc AI Development Environment Setup



## Status



Foundation Phase / Sprint 0



This document defines the reproducible setup procedure for the Arc standardized AI-assisted development environment.



The approved development flow is:



```text

Developer

&#x20;   ↓

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configurable Model

```



This document describes the development environment only.



It does not establish Arc's production architecture or permanently select specific AI models.



---



## 1. Purpose



The purpose of this setup is to allow an Arc developer to reproduce the approved AI-assisted development environment using:



- OpenCode as the coding-agent interface

- OmniRoute as the local routing layer

- OpenRouter as the initial model gateway

- Configurable model selection

- Arc repository documentation as durable project context



The setup must not require secrets to be committed to the repository.



---



## 2. Prerequisites



The developer should have:



- Git

- A working Arc repository clone

- Internet connectivity for initial installation and model-provider access

- A supported terminal

- Node.js and npm where required by the selected installation method

- Windows developers may use WSL when following the recommended Linux-based workflow



The exact application runtime, backend framework, frontend framework, database, and production infrastructure are outside the scope of this setup.



---



## 3. Windows Development

For Windows, OpenCode supports direct Windows installation as well as development through WSL.

WSL is the recommended environment when a Linux-based development workflow provides better compatibility or consistency with the developer's broader tooling requirements.

However, WSL is **not a mandatory prerequisite for X-9**.

### 3.1 Recommended Windows Workflow

For developers who prefer a Linux-based development environment, the recommended workflow is:

```text
Windows
    ↓
WSL 2
    ↓
Linux distribution
    ↓
OpenCode
    ↓
OmniRoute
    ↓
OpenRouter
```

WSL provides:

- A Linux development environment
- Compatibility with Linux-oriented development tooling
- Access to Windows files through `/mnt/`
- A consistent Linux shell environment

Example Windows drive mappings:

```text
C: → /mnt/c/
D: → /mnt/d/
```

For an Arc repository located on the Windows D: drive, the repository may therefore be accessed from WSL through a path similar to:

```text
/mnt/d/balasubrahmanya/arc
```

The exact local path differs between developers.

### 3.2 Direct Windows Workflow

Direct Windows installation is also valid when the required AI development tooling operates correctly on the developer's machine.

The following environment was verified on Bala's development machine on 2026-08-14. This is machine-scoped verification and does not constitute project-wide verification.

```text
Windows
    ↓
Node.js / npm
    ↓
OpenCode
    ↓
OmniRoute
    ↓
OpenRouter
```

The versions recorded on Bala's development machine were:

```text
Node.js: 24.15.0
npm: 11.12.1
OpenCode: 1.18.18
OmniRoute: 3.8.49
```

This machine-scoped verification does not establish that every Arc developer can reproduce the environment. Independent reproduction on another developer's machine remains pending (see §27.9).

The standardized requirement is the functioning AI development workflow, not a particular operating-system shell.

### 3.3 Reproducibility Requirement

Regardless of whether a developer uses direct Windows installation, WSL, or macOS, the following logical workflow must remain consistent:

```text
Developer
    ↓
OpenCode
    ↓
OmniRoute
    ↓
OpenRouter
    ↓
Configurable Model
```

Platform-specific differences must not change:

- AI security boundaries
- Model-role strategy
- Repository context workflow
- Credential-handling rules
- Human approval requirements
- GitHub contribution workflow

Platform-specific installation details should be documented only when they are required for successful reproduction.



---



## 4. macOS Development



macOS developers may run OpenCode directly in a supported terminal environment.



The same logical architecture applies:



```text

Developer

&#x20;   ↓

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configured Model

```



The setup must not depend on Windows-specific paths or tooling.



---



## 5. OpenCode Installation



OpenCode is the standardized coding-agent interface for Arc.



The current official OpenCode documentation provides multiple installation methods.



The recommended installation method for Windows WSL is the official installation script:



```bash

curl -fsSL https://opencode.ai/install | bash

```



OpenCode can also be installed using supported package managers where appropriate.



For example:



```bash

npm install -g opencode-ai

```



The team should prefer the installation method recommended by the current official OpenCode documentation for the developer's operating system.



Do not install beta or experimental OpenCode versions unless the team explicitly decides to evaluate them.



---



## 6. Verify OpenCode Installation



After installation, verify that the executable is available:



```bash

opencode --version

```



Record the installed version as part of X-9 verification evidence.



Do not claim the installation is verified in this document until the command succeeds on the developer's machine.



---



## 7. OmniRoute Installation



OmniRoute is the local routing and policy layer between OpenCode and downstream model providers.



The current documented npm installation method is:



```bash

npm install -g omniroute

```



After installation, start OmniRoute using:



```bash

omniroute

```



The default local OmniRoute API endpoint is:



```text

http://localhost:20128/v1

```



The OmniRoute dashboard is available at:



```text

http://localhost:20128

```



The exact installation method may change as OmniRoute evolves.



When reproducing the environment, developers should verify the current official OmniRoute documentation before installation.



---



## 8. Verify OmniRoute



After starting OmniRoute, verify that the local service is reachable.



The preferred verification method is to use the OmniRoute dashboard and API endpoint provided by the installed version.



Where an API key has been configured, the model endpoint can be checked using an OpenAI-compatible models request.



Example:



```bash

curl http://localhost:20128/v1/models \\

&#x20; -H "Authorization: Bearer <OMNIROUTE_API_KEY>"

```



Do not place a real API key in:



- Git

- Markdown documentation

- Shell history where avoidable

- Screenshots

- Issue descriptions

- Pull Requests



Replace `<OMNIROUTE_API_KEY>` with the locally configured credential only when performing the verification.



---



## 9. OpenRouter Configuration



OpenRouter is the initial external model gateway used by the Arc AI development environment.



The OpenRouter credential must be configured locally and must never be committed to the repository.



The credential should be provided through an approved local secret/configuration mechanism.



The repository must contain only safe configuration examples.



The actual OpenRouter credential must remain outside Git.



---



## 10. Provider Configuration Through OmniRoute



OpenRouter should be configured as a downstream provider of OmniRoute.



The provider configuration must remain local to the developer environment.



The exact provider configuration depends on the current OmniRoute version and its supported provider configuration mechanism.



After configuration, verify that:



1\. OmniRoute is running.

2\. The OpenRouter provider is reachable.

3\. At least one approved model is available through OmniRoute.

4\. The model can respond successfully through the OmniRoute endpoint.



Do not hard-code a permanent Arc model name into the repository during the initial setup.



---



## 11. OpenCode → OmniRoute Configuration



OpenCode must use OmniRoute as its model endpoint rather than connecting directly to OpenRouter for the standardized Arc workflow.



The logical configuration is:



```text

OpenCode

&#x20;   ↓

OmniRoute local API

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configured model

```



The OmniRoute OpenAI-compatible API endpoint is:



```text

http://localhost:20128/v1

```



The exact OpenCode configuration format must follow the currently installed OpenCode and OmniRoute versions.



Where supported by the installed OmniRoute version, the OmniRoute OpenCode configuration helper may be used to generate or update the OpenCode provider configuration.



The generated configuration must not expose credentials in committed files.



---



## 12. Model Configuration



The AI development environment must use configurable model selection.



The repository must not depend on a single hard-coded model.



Model assignments should conceptually follow:



```text

Primary Role

&#x20;   ↓

Configured Model



Review Role

&#x20;   ↓

Configured Model



Fast Role

&#x20;   ↓

Configured Model

```



The actual model names are established only after the X-9 benchmark process is completed.



Until benchmarking is complete, documentation must not describe a specific model as the permanent Arc Primary, Review, or Fast model.



---



## 13. Model Availability Verification



After connecting OpenCode to OmniRoute, verify that OpenCode can access the configured model catalog.



The verification should establish:



- OpenCode starts successfully.

- OmniRoute is reachable.

- The configured provider is reachable.

- At least one configured model is available.

- OpenCode can send a request through OmniRoute.

- A valid model response is returned.



The exact model used for the initial connectivity test may be temporary and does not constitute final model-role selection.



---



## 14. Start OpenCode in the Arc Repository



OpenCode must be started from the Arc repository.



Example in WSL:



```bash

cd /mnt/d/balasubrahmanya/arc

opencode

```



For another operating system, use the corresponding local repository path.



Before performing AI-assisted development, the developer must confirm that the current working directory is the Arc repository.



The agent must therefore have access to the repository's current:



- `AGENTS.md`

- `PROJECT_CONTEXT.md`

- `CURRENT_STATE.md`

- Product documentation

- Requirements

- Architecture documentation

- ADRs

- Relevant source code

- Git history



---



## 15. Repository Context Verification



The first OpenCode verification should be read-only.



The developer should ask OpenCode to summarize the current Arc repository using only repository information.



The test should verify that the agent can correctly identify:



- The project name

- Current Foundation phase

- Current engineering state

- Repository contribution workflow

- Security rules

- AI development rules

- Current product-definition status



The test must not require modification of repository files.



The developer should compare the response against the authoritative repository documents.



The AI conversation itself is not evidence that the information is correct.



---



## 16. Small AI-Assisted Development Test



After the read-only test succeeds, perform one small, non-production AI-assisted change.



The change should be:



- Low risk

- Easy to review

- Reversible

- Unrelated to production infrastructure

- Within the scope of the X-9 Foundation work



Examples include:



- Documentation improvement

- Small test improvement

- Repository tooling documentation

- Minor formatting or configuration correction



The developer must review the resulting diff manually.



The change must not:



- Introduce secrets

- Access production systems

- Modify production data

- Introduce unapproved architecture

- Bypass repository workflow

- Modify unrelated product functionality



---



## 17. AI Context Loading Workflow



Before beginning a significant AI-assisted task, the developer should ensure the agent has access to the relevant repository context.



The general workflow is:



```text

Read repository instructions

&#x20;       ↓

Understand project context

&#x20;       ↓

Check current project state

&#x20;       ↓

Read relevant requirements

&#x20;       ↓

Read relevant architecture documentation

&#x20;       ↓

Read applicable ADRs

&#x20;       ↓

Inspect relevant source code

&#x20;       ↓

Inspect relevant Git history

&#x20;       ↓

Begin task

```



The agent should not rely on a previous private AI conversation as a substitute for repository context.



---



## 18. Credentials and Secrets



The following must never be committed:



- OpenRouter API keys

- OmniRoute credentials

- Provider credentials

- Access tokens

- Passwords

- Private certificates

- Production secrets

- Customer credentials



The following may be committed when they contain only safe placeholders:



- `.env.example`

- Documentation describing variable names

- Non-sensitive configuration examples



A developer must verify `git status` before committing AI-assisted configuration changes.



---



## 19. Local Configuration



Local credentials and configuration should remain outside the repository unless the repository explicitly requires a safe, non-secret configuration file.



Before adding a new environment variable, verify that the variable is actually required by the implemented X-9 setup.



Do not add speculative variables for future services.



Do not add environment variables for:



- Databases not yet selected

- Redis

- Kafka

- Vector databases

- Object storage

- Kubernetes

- Production infrastructure

- Unimplemented product services



---



## 20. MCP and External Tool Configuration



MCP servers and external tools are not enabled automatically.



Each tool must be evaluated before use.



The evaluation should identify:



- Purpose

- Required permissions

- Data accessible to the tool

- External systems accessible to the tool

- Write capabilities

- Credential requirements

- Security risks



Only tools required for the current development workflow should be enabled.



Production-capable tools must remain outside the normal autonomous development permission boundary.



---



## 21. Fallback Configuration



The AI development environment should support model fallback where the configured routing layer provides the capability.



Fallback may be triggered by:



- Rate limits

- Timeouts

- Temporary provider failures

- Model unavailability

- Gateway failures



Fallback behavior must remain:



- Configurable

- Deterministic

- Documented

- Observable

- Independent of hard-coded application logic



A fallback must not grant additional permissions to the AI agent.



Detailed model fallback policy is documented in:



`docs/engineering/ai/model-strategy.md`



---



## 22. Troubleshooting Principles



When the AI environment fails, diagnose the layers independently.



```text

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

Provider

&#x20;   ↓

Model

```



Do not immediately change multiple layers at once.



### OpenCode failure



Check:



- Installation

- Version

- PATH

- Repository location

- OpenCode configuration



### OmniRoute failure



Check:



- Installation

- Process status

- Local port

- Dashboard

- Provider configuration

- Endpoint configuration



### Provider failure



Check:



- Provider credentials

- Provider availability

- Model availability

- Rate limits

- Network connectivity



### Model failure



Check:



- Model identifier

- Provider availability

- Model access

- Rate limits

- Timeout behavior

- Fallback configuration



---



## 23. Reproducibility Test



A second developer should eventually reproduce the environment without relying on private conversations.



The reproduction procedure should be:



```text

Clone Arc

&#x20;   ↓

Read repository documentation

&#x20;   ↓

Install required tooling

&#x20;   ↓

Configure local credentials

&#x20;   ↓

Start OmniRoute

&#x20;   ↓

Configure OpenCode

&#x20;   ↓

Verify provider/model connectivity

&#x20;   ↓

Start OpenCode in Arc

&#x20;   ↓

Run repository-context test

&#x20;   ↓

Perform controlled AI-assisted change

```



The second developer should record any undocumented steps or failures.



Those findings must be incorporated into the repository documentation before X-9 is considered reproducible.



---



## 24. Verification Evidence



X-9 verification evidence should include:



- OpenCode installation/version

- OmniRoute installation/version

- OmniRoute health/reachability

- Provider connectivity

- Model endpoint verification

- OpenCode → OmniRoute verification

- Read-only repository-context test

- Small AI-assisted development change

- Security/secret-handling verification

- Model benchmark results

- Fallback verification

- Second-developer reproduction evidence when available



Sensitive credentials must never be included in the evidence.



Screenshots must be reviewed for accidental exposure of:



- API keys

- Tokens

- Passwords

- Personal credentials

- Customer data

- Private configuration



---



## 25. Version and Documentation Maintenance



AI tooling changes independently of the Arc product.



Therefore:



- Installation procedures must be verified against current official documentation.

- Tool versions must be recorded during verification.

- Changes in installation procedures must be reflected in this document.

- Temporary workarounds must be clearly identified.

- Deprecated commands must be removed.

- Experimental tooling must not silently become the team standard.



This document should describe the verified Arc workflow rather than copying external documentation in full.



---



## 26. Security Requirements



This setup is governed by:



`SECURITY.md`



AI-specific architecture is documented in:



`docs/engineering/ai/architecture.md`



Repository AI instructions are defined in:



`AGENTS.md`



Engineering contribution rules are defined in:



`CONTRIBUTING.md`



These documents remain authoritative for their respective responsibilities.



---



## 27. Current Verification Status

This section records machine-scoped observations from Bala's development machine only.

These observations:

- Are NOT proof that every Arc developer can reproduce the environment.
- Are NOT proof that the capability is project-wide verified.
- Represent the current verification status as of 2026-08-14 unless an actual evidence artifact/link exists in the repository to establish otherwise.

The following environment components were installed and tested on Bala's development machine:

| Component | Version Recorded | Status on Bala's Development Machine |
|---|---:|---|
| Node.js | 24.15.0 | Verified |
| npm | 11.12.1 | Verified |
| OpenCode | 1.18.18 | Verified |
| OmniRoute | 3.8.49 | Verified |
| OpenRouter provider | Configured in OmniRoute | Verified |
| OmniRoute provider connectivity | OpenRouter | Passed |
| OpenCode OmniRoute integration | Bundled OmniRoute plugin | Verified |
| End-to-end model request | OmniRoute downstream route | Passed |

Detailed machine-scoped verification evidence is maintained in [verification-evidence.md](verification-evidence.md).

### 27.5 OpenCode Integration Path

The generated integration is stored in the developer's local OpenCode configuration directory and is not part of the Arc repository.

The plugin-based authentication flow must use the OmniRoute integration's supported authentication mechanism.

The OpenCode configuration must point to the OmniRoute OpenAI-compatible endpoint rather than directly to OpenRouter.

The logical client path is:

```text
OpenCode
    ↓
OmniRoute OpenCode integration
    ↓
http://localhost:20128/v1
    ↓
OmniRoute
    ↓
OpenRouter
    ↓
Selected downstream model
```

---

### 27.7 Model Discovery

The OmniRoute OpenCode integration supports dynamic model discovery through:

```text
/v1/models
```

Model discovery is intentionally dynamic.

The X-9 Foundation must not hard-code a permanent model list into the Arc repository.

The final model assignments will be established separately through the model-role and benchmark process.

---

### 27.8 Authentication and Credential Boundary

There are two distinct credential classes:

```text
OpenRouter provider credential
    ↓
Used by OmniRoute to access OpenRouter

OmniRoute client/API credential
    ↓
Used by development clients to access OmniRoute
```

These credentials must never be treated as interchangeable.

OpenCode must not receive the OpenRouter provider credential directly when using the standardized Arc workflow.

Credentials must remain in the approved local credential stores for their respective tools.

Real credentials must never be placed in:

- Git
- `.env.example`
- Markdown documentation
- Pull Request descriptions
- GitHub Issues
- Linear issue descriptions
- Screenshots
- AI prompts
- Committed configuration files

---

### 27.9 Current X-9 Verification Checklist

Checklist scope is defined as follows:

- **Documented/defined:** the step is documented as part of the standardized setup.
- **Verified on Bala's development machine:** recorded output from Bala's development machine exists (see [verification-evidence.md](verification-evidence.md)).
- **Independently reproduced / project-wide accepted:** not yet established; requires recorded evidence from another developer's machine.

The current status on Bala's development machine is:

- [x] OpenCode installation documented and verified on Bala's development machine.
- [x] OpenCode version recorded on Bala's development machine.
- [x] OmniRoute installation documented and verified on Bala's development machine.
- [x] OmniRoute version recorded on Bala's development machine.
- [x] OpenRouter provider configuration documented and verified on Bala's development machine.
- [x] OpenRouter provider connectivity verified on Bala's development machine.
- [x] OmniRoute initialization documented and performed on Bala's development machine.
- [x] OmniRoute server started on Bala's development machine.
- [x] OpenCode OmniRoute integration installed on Bala's development machine.
- [x] OpenCode can route a real request through OmniRoute on Bala's development machine.
- [x] Downstream model request succeeded on Bala's development machine.
- [x] No repository credentials were committed (repository-wide; checked against repository history).

The following remain incomplete:

- [ ] Final Primary model selection.
- [ ] Final Review model selection.
- [ ] Final Fast model selection.
- [ ] Repeatable 8–10 task model benchmark.
- [ ] Model-role benchmark results documented.
- [ ] Formal fallback policy verification.
- [ ] Complete AI least-privilege verification.
- [ ] MCP/tool permission review.
- [ ] Second-developer reproduction.
- [ ] Final X-9 Foundation acceptance.

These items must not be marked complete until evidence exists.
---



## 28. Non-Goals



This setup does not:



- Implement Arc product functionality

- Select the final application architecture

- Select the production database

- Configure production infrastructure

- Grant AI production access

- Introduce Kubernetes

- Introduce microservices

- Introduce Redis

- Introduce Kafka

- Introduce a vector database

- Introduce object storage

- Permanently select a single AI model

- Treat AI conversations as authoritative documentation



---



## 29. Completion Criteria



The following are Foundation acceptance conditions. They describe what must be demonstrated for acceptance; they do not claim that those conditions are already satisfied. Reference-machine verification is recorded in §27 and does not by itself constitute acceptance.



Reference-machine verification alone does not satisfy Foundation acceptance. Unless explicitly stated otherwise, each verification condition below requires independent reproduction and recorded evidence before it can be considered accepted project-wide.



1. OpenCode installation is documented and has been verified on the reference development machine; acceptance requires successful reproduction by another developer.

2. OmniRoute installation is documented and has been verified on the reference development machine; acceptance requires successful reproduction by another developer.

3. OpenRouter provider connectivity is documented and has been verified on the reference development machine; acceptance requires successful reproduction by another developer.

4. An approved model endpoint responds successfully on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

5. OpenCode operates against the Arc repository through OmniRoute on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

6. The repository-context test succeeds on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

7. A small AI-assisted development change is completed safely on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

8. Security and least-privilege rules are documented and verified on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

9. The model benchmark procedure has been completed and its results documented.

10. Primary, Review, and Fast model roles are documented.

11. Fallback behavior is documented and verified on the reference development machine; acceptance requires successful independent reproduction and recorded evidence.

12. Another developer can reproduce the setup from repository documentation (independent reproduction).

13. No secrets or production/customer data entered Git or the development AI workflow.



---



## 30. Summary



The standardized Arc AI development environment is:



```text

Developer

&#x20;   ↓

OpenCode

&#x20;   ↓

OmniRoute

&#x20;   ↓

OpenRouter

&#x20;   ↓

Configurable Model

```



The environment is a development-time system.



It must remain:



- Secure

- Reproducible

- Model-independent

- Product-agnostic where requirements remain unsettled

- Traceable through GitHub and Linear

- Governed by human engineering review



Specific tool versions and provider configuration are recorded in this document only after they have been actually tested on a developer's machine (see §27). Model assignments, benchmark results, and project-acceptance verification evidence must be recorded only after they have been actually tested and evidenced.
