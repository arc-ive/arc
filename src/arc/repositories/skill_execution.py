"""PostgreSQL implementation of the SkillExecutionRecordRepository.

Follows the same conventions as ``arc.repositories.tools``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query that reads or writes a skill execution record
includes a ``tenant_id`` condition so that cross-tenant access is
impossible at the SQL level.

Records are append-oriented audit artifacts: each
``SkillExecutionService.execute()`` call produces exactly one row. The
record persists before execution and is updated on completion so that
crashes or unexpected failures still leave an auditable trace.
"""

from typing import List, Optional

from arc.db.connection import ArcDatabase
from arc.domain.models import SkillExecutionRecord, SkillExecutionStatus


class PostgreSQLSkillExecutionRecordRepository:
    """PostgreSQL implementation of the skill execution record repository."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> SkillExecutionRecord:
        return SkillExecutionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            skill_id=row["skill_id"],
            skill_version=row["skill_version"],
            principal_id=row["principal_id"],
            agent_run_id=row["agent_run_id"],
            status=SkillExecutionStatus(row["status"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            failure_code=row["failure_code"],
            failure_message=row["failure_message"],
            metadata_json=row["metadata_json"],
            result_summary=row["result_summary"],
            created_at=row["created_at"],
        )

    async def create_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        """Persist a skill execution record (initial state, typically started)."""
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO skill_execution_records
                    (id, tenant_id, skill_id, skill_version, principal_id,
                     agent_run_id, status, started_at, completed_at,
                     failure_code, failure_message, metadata_json,
                     result_summary, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                record.id,
                record.tenant_id,
                record.skill_id,
                record.skill_version,
                record.principal_id,
                record.agent_run_id,
                record.status.value,
                record.started_at,
                record.completed_at,
                record.failure_code,
                record.failure_message,
                record.metadata_json,
                record.result_summary,
                record.created_at,
            )
            return record

    async def update_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        """Update a skill execution record with terminal state."""
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                UPDATE skill_execution_records
                SET status = $2, completed_at = $3, failure_code = $4,
                    failure_message = $5, result_summary = $6
                WHERE id = $1 AND tenant_id = $7
                """,
                record.id,
                record.status.value,
                record.completed_at,
                record.failure_code,
                record.failure_message,
                record.result_summary,
                record.tenant_id,
            )
            return record

    async def get_record(self, record_id: str, tenant_id: str) -> Optional[SkillExecutionRecord]:
        """Read one skill execution record within the trusted tenant."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, skill_id, skill_version, principal_id,
                       agent_run_id, status, started_at, completed_at,
                       failure_code, failure_message, metadata_json,
                       result_summary, created_at
                FROM skill_execution_records
                WHERE id = $1 AND tenant_id = $2
                """,
                record_id,
                tenant_id,
            )
        if row is None:
            return None
        return self._from_row(row)

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[SkillExecutionRecord]:
        """List the most recent skill execution records for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, skill_id, skill_version, principal_id,
                       agent_run_id, status, started_at, completed_at,
                       failure_code, failure_message, metadata_json,
                       result_summary, created_at
                FROM skill_execution_records
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
            return [self._from_row(row) for row in rows]

    async def list_for_skill(
        self, tenant_id: str, skill_id: str, limit: int = 50
    ) -> List[SkillExecutionRecord]:
        """List the most recent skill execution records for a specific skill."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, skill_id, skill_version, principal_id,
                       agent_run_id, status, started_at, completed_at,
                       failure_code, failure_message, metadata_json,
                       result_summary, created_at
                FROM skill_execution_records
                WHERE tenant_id = $1 AND skill_id = $2
                ORDER BY created_at DESC
                LIMIT $3
                """,
                tenant_id,
                skill_id,
                limit,
            )
            return [self._from_row(row) for row in rows]

    async def list_for_agent_run(
        self, agent_run_id: str, tenant_id: str
    ) -> List[SkillExecutionRecord]:
        """List skill execution records linked to a specific agent run."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, skill_id, skill_version, principal_id,
                       agent_run_id, status, started_at, completed_at,
                       failure_code, failure_message, metadata_json,
                       result_summary, created_at
                FROM skill_execution_records
                WHERE agent_run_id = $1 AND tenant_id = $2
                ORDER BY created_at ASC
                """,
                agent_run_id,
                tenant_id,
            )
            return [self._from_row(row) for row in rows]
