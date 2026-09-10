# Arc V2 Governing Documentation

These documents form the proposed final V2 baseline for Arc.

## Documents

1. `ARC_V2_PRD.md` — Product Requirements Document
2. `ARC_V2_TRD.md` — Technical Requirements & Design
3. `ARC_V2_ADR.md` — Architecture Decision Records

## Authority

Use the documents together:

- PRD = what Arc V2 must provide
- TRD = how it should be engineered
- ADR = binding architectural decisions and conflict resolution

When an old document or current implementation conflicts with these V2 decisions, do not silently preserve the old behavior. Stop and resolve the contradiction explicitly.

## Core V2 Direction

Arc V2 is not a feature checklist.

The goal is to make the important AI workflows work end-to-end:

- Company Brain
- Secure hybrid RAG
- Production LLM
- Skills
- Tools
- Agent
- Human approval
- Connector → knowledge → RAG
- Webhook → Skill → Tool
- AI observability/evaluation

AI domains receive production-grade engineering.

Non-AI domains receive solid, secure, maintainable engineering without unnecessary enterprise infrastructure.

## Implementation Rule

No direct pushes to `main`.

Use:

feature branch → tests → commit → push → PR → review → merge
