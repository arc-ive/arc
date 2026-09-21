"""PostgreSQL repository for platform and tenant capability state (V2-ADR-004).

Platform capabilities are global (one row per known capability). Tenant
capabilities are scoped per (tenant_id, capability_id). Every query is
grounded in the database; capability state is never cached or guessed.
"""

from typing import List, Optional

from arc.db.connection import ArcDatabase, NotFoundError
from arc.domain.models import PlatformCapability, TenantCapability


class PostgreSQLCapabilityRepository:
    """PostgreSQL-backed capability storage."""

    def __init__(self, db: ArcDatabase):
        self._db = db

    async def get_platform_capability(self, capability_id: str) -> Optional[PlatformCapability]:
        async with self._db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT capability_id, enabled, created_at, updated_at
                FROM platform_capabilities
                WHERE capability_id = $1
                """,
                capability_id,
            )
        if row is None:
            return None
        return PlatformCapability(
            capability_id=row["capability_id"],
            enabled=row["enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_platform_capabilities(self) -> List[PlatformCapability]:
        async with self._db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT capability_id, enabled, created_at, updated_at
                FROM platform_capabilities
                ORDER BY capability_id
                """
            )
        return [
            PlatformCapability(
                capability_id=r["capability_id"],
                enabled=r["enabled"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def set_platform_capability(
        self, capability_id: str, enabled: bool
    ) -> PlatformCapability:
        async with self._db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO platform_capabilities (capability_id, enabled, updated_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (capability_id) DO UPDATE
                    SET enabled = $2, updated_at = CURRENT_TIMESTAMP
                """,
                capability_id,
                enabled,
            )
            row = await conn.fetchrow(
                """
                SELECT capability_id, enabled, created_at, updated_at
                FROM platform_capabilities
                WHERE capability_id = $1
                """,
                capability_id,
            )
        return PlatformCapability(
            capability_id=row["capability_id"],
            enabled=row["enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_tenant_capability(
        self, tenant_id: str, capability_id: str
    ) -> Optional[TenantCapability]:
        async with self._db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tenant_id, capability_id, enabled, created_at, updated_at
                FROM tenant_capabilities
                WHERE tenant_id = $1 AND capability_id = $2
                """,
                tenant_id,
                capability_id,
            )
        if row is None:
            return None
        return TenantCapability(
            tenant_id=row["tenant_id"],
            capability_id=row["capability_id"],
            enabled=row["enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_tenant_capabilities(self, tenant_id: str) -> List[TenantCapability]:
        async with self._db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tenant_id, capability_id, enabled, created_at, updated_at
                FROM tenant_capabilities
                WHERE tenant_id = $1
                ORDER BY capability_id
                """,
                tenant_id,
            )
        return [
            TenantCapability(
                tenant_id=r["tenant_id"],
                capability_id=r["capability_id"],
                enabled=r["enabled"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def set_tenant_capability(
        self, tenant_id: str, capability_id: str, enabled: bool
    ) -> TenantCapability:
        async with self._db._connection_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM tenants WHERE id = $1)",
                tenant_id,
            )
            if not exists:
                raise NotFoundError("Tenant not found")
            await conn.execute(
                """
                INSERT INTO tenant_capabilities (tenant_id, capability_id, enabled, updated_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (tenant_id, capability_id) DO UPDATE
                    SET enabled = $3, updated_at = CURRENT_TIMESTAMP
                """,
                tenant_id,
                capability_id,
                enabled,
            )
            row = await conn.fetchrow(
                """
                SELECT tenant_id, capability_id, enabled, created_at, updated_at
                FROM tenant_capabilities
                WHERE tenant_id = $1 AND capability_id = $2
                """,
                tenant_id,
                capability_id,
            )
        return TenantCapability(
            tenant_id=row["tenant_id"],
            capability_id=row["capability_id"],
            enabled=row["enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
