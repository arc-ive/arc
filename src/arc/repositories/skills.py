"""PostgreSQL implementation of the SkillRepository contract.

Follows the same conventions as ``arc.repositories.connectors``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query that reads or modifies a skill row includes a
``tenant_id`` condition so that cross-tenant access is impossible at the
SQL level.

The ``skills`` table stores the scalar Skill envelope in dedicated columns
(id, tenant_id, name, version, purpose, status) and the structured Skill
body (inputs, preconditions, steps, constraints, allowed_tools,
approval_required, expected_output, failure_behavior, provenance) in a
JSONB ``definition`` column. This is a persistence detail: the typed
``Skill`` model remains the application-level contract, and the exact
Skill serialization format remains open (ADR-001, TRD 37).
"""

import json
from typing import List

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import Skill, SkillStatus


class PostgreSQLSkillRepository:
    """PostgreSQL implementation of the SkillRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    @staticmethod
    def _definition(skill: Skill) -> dict:
        """Return the structured Skill body for the JSONB definition column."""
        return {
            "inputs": skill.inputs,
            "preconditions": skill.preconditions,
            "steps": skill.steps,
            "constraints": skill.constraints,
            "allowed_tools": skill.allowed_tools,
            "approval_required": skill.approval_required,
            "expected_output": skill.expected_output,
            "failure_behavior": skill.failure_behavior,
            "provenance": skill.provenance,
        }

    @staticmethod
    def _from_row(row) -> Skill:
        """Reconstruct a typed Skill from a database row."""
        definition = json.loads(row["definition"]) if row["definition"] else {}
        return Skill(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            version=row["version"],
            purpose=row["purpose"],
            status=SkillStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            inputs=definition.get("inputs", []),
            preconditions=definition.get("preconditions", []),
            steps=definition.get("steps", []),
            constraints=definition.get("constraints", []),
            allowed_tools=definition.get("allowed_tools", []),
            approval_required=definition.get("approval_required", False),
            expected_output=definition.get("expected_output"),
            failure_behavior=definition.get("failure_behavior"),
            provenance=definition.get("provenance"),
        )

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        async with self.db.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO skills
                        (id, tenant_id, name, version, purpose, status,
                         definition, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    skill.id,
                    skill.tenant_id,
                    skill.name,
                    skill.version,
                    skill.purpose,
                    skill.status.value,
                    json.dumps(self._definition(skill)),
                    skill.created_at,
                    skill.updated_at,
                )
                return skill
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Skill '{skill.name}' version '{skill.version}' already exists "
                    f"in tenant {skill.tenant_id}"
                ) from e
            except Exception as e:
                raise Exception(f"Failed to create skill: {e}") from e

    async def get_by_id(self, skill_id: str, tenant_id: str) -> Skill:
        """Get a skill by ID, scoped to a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, name, version, purpose, status,
                       definition, created_at, updated_at
                FROM skills
                WHERE id = $1 AND tenant_id = $2
                """,
                skill_id,
                tenant_id,
            )
            if not row:
                raise NotFoundError(f"Skill {skill_id} not found in tenant {tenant_id}")
            return self._from_row(row)

    async def list_for_tenant(self, tenant_id: str) -> List[Skill]:
        """List all skills for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, name, version, purpose, status,
                       definition, created_at, updated_at
                FROM skills
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
            return [self._from_row(row) for row in rows]

    async def exists(self, skill_id: str, tenant_id: str) -> bool:
        """Check if a skill exists within a tenant."""
        try:
            await self.get_by_id(skill_id, tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete(self, skill_id: str, tenant_id: str) -> None:
        """Delete a skill, scoped to a tenant."""
        async with self.db.transaction() as conn:
            await conn.execute(
                "DELETE FROM skills WHERE id = $1 AND tenant_id = $2",
                skill_id,
                tenant_id,
            )
