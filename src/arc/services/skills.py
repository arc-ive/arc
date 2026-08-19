"""Skill service for Arc.

The ``SkillService`` accepts a trusted ``TenantContext`` established by
X-10 and extracts the tenant boundary from it.  The service never queries
tenancy tables, never authenticates users, and never authorizes callers.

The Skill body is a typed domain model; the exact serialization format
remains open (ADR-001, TRD 37).

Skill-level validation (TRD 25):
- ``preconditions_met`` — invalid preconditions prevent execution.
- ``is_tool_allowed`` — unauthorized tools cannot be called.
These are validation helpers only; no execution engine is implemented.
"""

import uuid
from dataclasses import replace
from typing import Iterable, List

from arc.domain.models import Skill, TenantContext


class SkillService:
    """Domain service for Skill operations."""

    def __init__(self, skill_repo):
        self.skill_repo = skill_repo

    async def create_skill(self, context: TenantContext, skill: Skill) -> Skill:
        """Create a new Skill for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10. The service derives the tenant boundary
        exclusively from it, generates a fresh Skill ID, and returns a
        new Skill without mutating the caller-supplied model.
        """
        if not skill.name:
            raise ValueError("Skill name cannot be empty")
        if not skill.purpose:
            raise ValueError("Skill purpose cannot be empty")
        trusted_skill = replace(
            skill,
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
        )
        return await self.skill_repo.create(trusted_skill)

    async def get_skill(self, context: TenantContext, skill_id: str) -> Skill:
        """Get a Skill by ID within a tenant."""
        return await self.skill_repo.get_by_id(skill_id, context.tenant_id)

    async def list_skills(self, context: TenantContext) -> List[Skill]:
        """List all Skills for a tenant."""
        return await self.skill_repo.list_for_tenant(context.tenant_id)

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
