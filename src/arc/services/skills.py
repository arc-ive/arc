"""Skill service for Arc.

The ``SkillService`` accepts a trusted ``TenantContext`` established by
X-10 and extracts the tenant boundary from it.  The service never queries
tenancy tables, never authenticates users, and never authorizes callers.

The Skill body is a typed domain model; the exact serialization format
remains open (ADR-001, TRD 37).

The critical security boundary is the PII guard on textual Skill fields:

    RAW SKILL INPUT
        ↓
    PII Guard (PiiGuardService) on textual fields
        ↓
    SANITIZED SKILL INPUT
        ↓
    PERSISTENCE

The service receives a shared ``PiiGuardService`` instance via dependency
injection from the application composition root, ensuring a single
Presidio-backed guard is used across the application. If sanitization
fails, the service fails closed: no Skill is persisted and a
PiiGuardError is raised.

Skill-level validation (TRD 25):
- ``preconditions_met`` — invalid preconditions prevent execution.
- ``is_tool_allowed`` — unauthorized tools cannot be called.
These are validation helpers only; no execution engine is implemented.
"""

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable, Optional

from arc.domain.models import Skill, TenantContext
from arc.services.pii import PiiGuardService


class SkillService:
    """Domain service for Skill operations."""

    def __init__(self, skill_repo, pii_guard: Optional[PiiGuardService] = None):
        self.skill_repo = skill_repo
        self.pii_guard = pii_guard if pii_guard is not None else PiiGuardService()

    async def create_skill(self, context: TenantContext, skill: Skill) -> Skill:
        """Create a new Skill for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10. The service derives the tenant boundary
        exclusively from it, generates a fresh Skill ID, and returns a
        new Skill without mutating the caller-supplied model.

        Textual user-authored fields are sanitized through PiiGuardService
        before persistence. If sanitization fails, the Skill is not
        persisted (fail closed).
        """
        if not skill.name:
            raise ValueError("Skill name cannot be empty")
        if not skill.purpose:
            raise ValueError("Skill purpose cannot be empty")

        # PII boundary first — on every path.
        sanitized_name = self.pii_guard.sanitize(skill.name).sanitized_text
        sanitized_purpose = self.pii_guard.sanitize(skill.purpose).sanitized_text
        sanitized_inputs = [self.pii_guard.sanitize(text).sanitized_text for text in skill.inputs]
        sanitized_steps = [self.pii_guard.sanitize(text).sanitized_text for text in skill.steps]
        sanitized_expected_output = (
            self.pii_guard.sanitize(skill.expected_output).sanitized_text
            if skill.expected_output is not None
            else None
        )
        sanitized_failure_behavior = (
            self.pii_guard.sanitize(skill.failure_behavior).sanitized_text
            if skill.failure_behavior is not None
            else None
        )
        sanitized_risk = (
            self.pii_guard.sanitize(skill.risk).sanitized_text if skill.risk is not None else None
        )

        trusted_skill = replace(
            skill,
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            name=sanitized_name,
            purpose=sanitized_purpose,
            inputs=sanitized_inputs,
            steps=sanitized_steps,
            expected_output=sanitized_expected_output,
            failure_behavior=sanitized_failure_behavior,
            risk=sanitized_risk,
        )
        return await self.skill_repo.create(trusted_skill)

    async def get_skill(self, context: TenantContext, skill_id: str) -> Skill:
        """Get a Skill by ID within a tenant."""
        return await self.skill_repo.get_by_id(skill_id, context.tenant_id)

    async def list_skills(self, context: TenantContext) -> list:
        """List all Skills for a tenant."""
        return await self.skill_repo.list_for_tenant(context.tenant_id)

    async def list_skills_paginated(self, context: TenantContext, limit: int, offset: int) -> tuple:
        """List Skills with LIMIT/OFFSET and total count."""
        return await self.skill_repo.list_for_tenant_paginated(context.tenant_id, limit, offset)

    async def update_skill(self, context: TenantContext, skill: Skill) -> Skill:
        """Update an existing Skill for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10. The service derives the tenant boundary
        exclusively from it, updates the Skill, and returns the updated
        Skill without mutating the caller-supplied model.

        Textual user-authored fields are sanitized through PiiGuardService
        before persistence. If sanitization fails, the Skill is not
        updated (fail closed).
        """
        if not skill.name:
            raise ValueError("Skill name cannot be empty")
        if not skill.purpose:
            raise ValueError("Skill purpose cannot be empty")

        # PII boundary first — on every path.
        sanitized_name = self.pii_guard.sanitize(skill.name).sanitized_text
        sanitized_purpose = self.pii_guard.sanitize(skill.purpose).sanitized_text
        sanitized_inputs = [self.pii_guard.sanitize(text).sanitized_text for text in skill.inputs]
        sanitized_steps = [self.pii_guard.sanitize(text).sanitized_text for text in skill.steps]
        sanitized_expected_output = (
            self.pii_guard.sanitize(skill.expected_output).sanitized_text
            if skill.expected_output is not None
            else None
        )
        sanitized_failure_behavior = (
            self.pii_guard.sanitize(skill.failure_behavior).sanitized_text
            if skill.failure_behavior is not None
            else None
        )
        sanitized_risk = (
            self.pii_guard.sanitize(skill.risk).sanitized_text if skill.risk is not None else None
        )

        trusted_skill = replace(
            skill,
            tenant_id=context.tenant_id,
            name=sanitized_name,
            purpose=sanitized_purpose,
            inputs=sanitized_inputs,
            steps=sanitized_steps,
            expected_output=sanitized_expected_output,
            failure_behavior=sanitized_failure_behavior,
            risk=sanitized_risk,
            updated_at=datetime.now(timezone.utc),
        )
        return await self.skill_repo.update(trusted_skill)

    async def delete_skill(self, context: TenantContext, skill_id: str) -> None:
        """Delete a Skill within a tenant."""
        await self.skill_repo.delete(skill_id, context.tenant_id)

    def preconditions_met(self, skill: Skill, satisfied_conditions: Iterable[str]) -> bool:
        """Return whether every Skill precondition is satisfied.

        A Skill with no preconditions is satisfied. This is the
        Skill-level gate that prevents execution when preconditions are
        not met (TRD 25). It performs no execution.
        """
        satisfied = set(satisfied_conditions)
        return all(precondition in satisfied for precondition in skill.preconditions)

    def is_tool_allowed(self, skill: Skill, tool_name: str) -> bool:
        """Return whether a tool is within the Skill's allowed tools.

        A Skill with no allowed_tools allows nothing. This is the
        Skill-level gate that prevents calling unauthorized tools
        (TRD 25). It performs no execution.
        """
        return tool_name in skill.allowed_tools
