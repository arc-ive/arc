# Arc AI Development Environment Verification Evidence

## Status

Foundation Phase / Sprint 0

This document records machine-scoped verification evidence from Bala's development machine.

This document is a developer/machine-scoped verification record. It is NOT normative setup instructions. The reproducible setup procedure is defined in [setup.md](setup.md).

## Purpose

This document captures detailed verification evidence, including:

- Command history

- Observed command output

- Local installation paths

- Localhost endpoints

- Installation and repair history

- End-to-end verification observations

These observations:

- Are NOT proof that every Arc developer can reproduce the environment.

- Are NOT proof that the capability is project-wide verified.

- Represent the verification status as of 2026-08-14 unless a later evidence artifact exists in the repository.

This document is not a setup guide. It does not replace [setup.md](setup.md), which remains the normative setup reference.

## Verified Installation

OpenCode was installed using npm and verified on Bala's development machine with:

```text
opencode --version
```

Result recorded on Bala's development machine:

```text
1.18.18
```

OmniRoute was installed using npm and verified on Bala's development machine with:

```text
omniroute --version
```

Result recorded on Bala's development machine:

```text
3.8.49
```

The installed executables were resolved successfully through the developer's local npm installation path.

## OpenRouter Provider Verification

OpenRouter was configured as the initial downstream provider for OmniRoute on Bala's development machine.

The configured provider was verified on Bala's development machine using:

```text
omniroute providers list
```

The provider was then validated using:

```text
omniroute providers validate
```

The provider connection was tested using:

```text
omniroute providers test openrouter
```

The result recorded on Bala's development machine was:

```text
OK OpenRouter: provider test passed
```

On Bala's development machine, this confirms that OmniRoute can authenticate and communicate with the configured OpenRouter provider.

The OpenRouter credential is stored in OmniRoute's local credential storage and must not be committed to the Arc repository.

## OmniRoute Initialization and Repair History

During initial OmniRoute startup, the local SQLite storage required initialization and migration processing.

The initial installation exposed:

- Pending database migrations

- Missing `better-sqlite3` native binary

- Server health failures before migration completion

These issues were resolved on Bala's development machine using the supported OmniRoute setup and runtime-repair mechanisms.

After initialization:

- The local OmniRoute database was created.

- Required migrations were applied.

- The native SQLite dependency was repaired.

- OmniRoute was able to start successfully on Bala's development machine.

The resulting local OmniRoute data directory is:

```text
%USERPROFILE%\.omniroute
```

This directory is local developer state and must not be copied into the Arc repository.

## OmniRoute Server Verification

OmniRoute was started on Bala's development machine using:

```text
omniroute serve
```

On Bala's development machine, the server reported successful startup and exposed the local service on:

```text
http://localhost:20128
```

The OpenAI-compatible API base is:

```text
http://localhost:20128/v1
```

The local dashboard is available at:

```text
http://localhost:20128
```

The server must remain running while clients such as OpenCode communicate with it.

## OpenCode Integration Installation

OmniRoute's supported OpenCode integration was installed on Bala's development machine using:

```text
omniroute setup opencode --non-interactive
```

This created the local OpenCode configuration and installed the OmniRoute OpenCode plugin.

The generated integration is stored in the developer's local OpenCode configuration directory and is not part of the Arc repository.

## End-to-End Verification

On Bala's development machine, a real model request was successfully completed through the standardized development path:

```text
OpenCode
    ↓
OmniRoute
    ↓
OpenRouter
    ↓
Downstream model
```

The successful test on Bala's development machine demonstrated that:

- OpenCode can operate with the OmniRoute integration.

- OmniRoute can route requests to a configured downstream provider.

- OpenRouter can serve as the downstream model gateway.

- A downstream model can return a successful response.

These results are machine-scoped observations and do not constitute project-wide verification.

The specific model used for this connectivity test does not constitute the final Arc Primary, Review, or Fast model selection.
