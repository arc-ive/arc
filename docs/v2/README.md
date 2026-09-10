# Arc V2 Governing Documentation

These documents form the proposed final V2 baseline for Arc.

## Documents

1. `ARC_V2_PRD.md` — Product Requirements Document
2. `ARC_V2_TRD.md` — Technical Requirements & Design
3. `ARC_V2_ADR.md` — Architecture Decision Records (V2-ADR-001 through V2-ADR-028)

## Authority

Use the documents together:

- PRD = what Arc V2 must provide
- TRD = how it should be engineered
- V2-ADR = binding architectural decisions and conflict resolution

### Supersession

For Arc V2 implementation, this V2 document set (PRD, TRD, V2-ADR) supersedes the following historical documents, which remain available for reference but are **not authoritative** for V2 implementation:

- `docs/ARC_FINAL_PRODUCT_AND_ARCHITECTURE_SPECIFICATION.md`
- `docs/requirements/PRD.md`
- `docs/requirements/TRD.md`
- The historical ADRs under `docs/architecture/decisions/` (ADR-001 through ADR-008)

Those documents reflect earlier design thinking and prior product direction. They may contain outdated assumptions, incomplete security models, or pre-reconciliation decisions that have been superseded by the V2 governing set.

**A developer or coding agent must not choose the historical documents over the V2 governing set when implementing V2 features.** If a historical document conflicts with the V2 PRD, TRD, or V2-ADR, the V2 governing set controls.

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
