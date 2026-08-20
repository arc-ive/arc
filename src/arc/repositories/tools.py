"""PostgreSQL implementation of the ToolExecutionRepository contract.

Follows the same conventions as ``arc.repositories.skills``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query that reads or writes a tool execution record
includes a ``tenant_id`` condition so that cross-tenant access is
impossible at the SQL level.

Records store only safe, sanitized summaries produced by the tool
execution service (TRD 14.2): secrets, credentials, raw sensitive
payloads, and internal stack traces must never reach this table.
"""

from typing import List

from arc.db.connection import ArcDatabase
from arc.domain.models import ToolExecutionRecord, ToolExecutionStatus, ToolRiskLevel


class PostgreSQLToolExecutionRepository:
    """PostgreSQL implementation of the ToolExecutionRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    @staticmethod
    def _from_row(row) -> ToolExecutionRecord:
        """Reconstruct a typed ToolExecutionRecord from a database row."""
        return ToolExecutionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            tool_name=row["tool_name"],
            tool_version=row["tool_version"],
            status=ToolExecutionStatus(row["status"]),
            risk_level=ToolRiskLevel(row["risk_level"]),
            input_summary=row["input_summary"],
            output_summary=row["output_summary"],
            error_kind=row["error_kind"],
            created_at=row["created_at"],
        )

    async def create_record(self, record: ToolExecutionRecord) -> ToolExecutionRecord:
        """Persist a tool execution record."""
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO tool_execution_records
                    (id, tenant_id, tool_name, tool_version, status,
                     risk_level, input_summary, output_summary, error_kind,
                     created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                record.id,
                record.tenant_id,
                record.tool_name,
                record.tool_version,
                record.status.value,
                record.risk_level.value,
                record.input_summary,
                record.output_summary,
                record.error_kind,
                record.created_at,
            )
            return record

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[ToolExecutionRecord]:
        """List the most recent tool execution records for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, tool_name, tool_version, status,
                       risk_level, input_summary, output_summary, error_kind,
                       created_at
                FROM tool_execution_records
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
            return [self._from_row(row) for row in rows]
