"""PostgreSQL implementation of the ConnectorRepository contract.

Follows the same conventions as ``arc.repositories.tenancy``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg.  Every query that reads or modifies a connector row includes a
``tenant_id`` condition so that cross-tenant access is impossible at the
SQL level.
"""

from typing import List

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import ConnectorConfig, ConnectorProvider, ConnectorStatus


class PostgreSQLConnectorRepository:
    """PostgreSQL implementation of the ConnectorRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, connector: ConnectorConfig) -> ConnectorConfig:
        """Create a new connector configuration."""
        async with self.db.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO connector_configs
                        (id, tenant_id, provider, name, target, status, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    connector.id,
                    connector.tenant_id,
                    connector.provider.value,
                    connector.name,
                    connector.target,
                    connector.status.value,
                    connector.created_at,
                    connector.updated_at,
                )
                return connector
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Connector '{connector.name}' already exists for provider "
                    f"'{connector.provider.value}' in tenant {connector.tenant_id}"
                ) from e
            except Exception as e:
                raise Exception(f"Failed to create connector: {e}") from e

    async def get_by_id(self, connector_id: str, tenant_id: str) -> ConnectorConfig:
        """Get a connector configuration by ID, scoped to a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, provider, name, target, status, created_at, updated_at
                FROM connector_configs
                WHERE id = $1 AND tenant_id = $2
                """,
                connector_id,
                tenant_id,
            )
            if not row:
                raise NotFoundError(f"Connector {connector_id} not found in tenant {tenant_id}")
            return ConnectorConfig(
                id=row["id"],
                tenant_id=row["tenant_id"],
                provider=ConnectorProvider(row["provider"]),
                name=row["name"],
                target=row["target"],
                status=ConnectorStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def list_for_tenant(self, tenant_id: str) -> List[ConnectorConfig]:
        """List all connector configurations for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, provider, name, target, status, created_at, updated_at
                FROM connector_configs
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
            return [
                ConnectorConfig(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    provider=ConnectorProvider(row["provider"]),
                    name=row["name"],
                    target=row["target"],
                    status=ConnectorStatus(row["status"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    async def list_for_tenant_paginated(self, tenant_id: str, limit: int, offset: int) -> tuple:
        """List connector configs with LIMIT/OFFSET and total count."""
        async with self.db._connection_pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM connector_configs WHERE tenant_id = $1",
                tenant_id,
            )
            total = count_row["cnt"]
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, provider, name, target, status, created_at, updated_at
                FROM connector_configs
                WHERE tenant_id = $1
                ORDER BY created_at DESC, id ASC
                LIMIT $2 OFFSET $3
                """,
                tenant_id,
                limit,
                offset,
            )
            items = [
                ConnectorConfig(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    provider=ConnectorProvider(row["provider"]),
                    name=row["name"],
                    target=row["target"],
                    status=ConnectorStatus(row["status"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
            return items, total

    async def exists(self, connector_id: str, tenant_id: str) -> bool:
        """Check if a connector configuration exists within a tenant."""
        try:
            await self.get_by_id(connector_id, tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete(self, connector_id: str, tenant_id: str) -> None:
        """Delete a connector configuration, scoped to a tenant."""
        async with self.db.transaction() as conn:
            await conn.execute(
                "DELETE FROM connector_configs WHERE id = $1 AND tenant_id = $2",
                connector_id,
                tenant_id,
            )
