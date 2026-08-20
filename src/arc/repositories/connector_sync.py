"""PostgreSQL implementation of the ConnectorSyncRepository contract.

Follows the same conventions as ``arc.repositories.connectors``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query includes a ``tenant_id`` condition so that
cross-tenant access is impossible at the SQL level. Records store only
safe summaries (item counts and generic error kinds); credentials and
raw external payloads never reach this repository.
"""

from typing import List

from arc.db.connection import ArcDatabase
from arc.domain.models import (
    ConnectorProvider,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
)


class PostgreSQLConnectorSyncRepository:
    """PostgreSQL implementation of the ConnectorSyncRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create_record(self, record: ConnectorSyncRecord) -> ConnectorSyncRecord:
        """Persist a connector synchronization record."""
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO connector_sync_records
                    (id, tenant_id, connector_id, provider, status,
                     items_fetched, error_kind, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                record.id,
                record.tenant_id,
                record.connector_id,
                record.provider.value,
                record.status.value,
                record.items_fetched,
                record.error_kind,
                record.created_at,
            )
            return record

    async def list_for_tenant(self, tenant_id: str) -> List[ConnectorSyncRecord]:
        """List all connector synchronization records for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, connector_id, provider, status,
                       items_fetched, error_kind, created_at
                FROM connector_sync_records
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
            return [
                ConnectorSyncRecord(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    connector_id=row["connector_id"],
                    provider=ConnectorProvider(row["provider"]),
                    status=ConnectorSyncStatus(row["status"]),
                    items_fetched=row["items_fetched"],
                    error_kind=row["error_kind"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
