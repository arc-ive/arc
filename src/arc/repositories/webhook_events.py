"""PostgreSQL implementation of the WebhookEventRepository contract.

Follows the same conventions as ``arc.repositories.connector_sync``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query includes a ``tenant_id`` condition so that
cross-tenant access is impossible at the SQL level. Records store only
safe envelope metadata; raw external payloads never reach this
repository (ADR-001 webhook security boundary).
"""

from typing import List

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import WebhookEvent, WebhookEventStatus


class PostgreSQLWebhookEventRepository:
    """PostgreSQL implementation of the WebhookEventRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        """Persist a webhook event.

        Raises ``DuplicateKeyError`` when the ``(tenant_id, event_id)``
        uniqueness pair already exists.
        """
        async with self.db.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO webhook_events
                        (id, tenant_id, endpoint_id, event_id, event_type,
                         status, payload_size_bytes, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    event.id,
                    event.tenant_id,
                    event.endpoint_id,
                    event.event_id,
                    event.event_type,
                    event.status.value,
                    event.payload_size_bytes,
                    event.created_at,
                )
            except asyncpg.UniqueViolationError:
                raise DuplicateKeyError(
                    f"Webhook event '{event.event_id}' already exists for "
                    f"endpoint '{event.endpoint_id}' in tenant {event.tenant_id}"
                )
            return event

    async def get_by_event_id(self, event_id: str, tenant_id: str) -> WebhookEvent:
        """Get an event by sender-supplied identifier, scoped to a tenant.

        Raises ``NotFoundError`` when no such event exists for the tenant.
        """
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, endpoint_id, event_id, event_type,
                       status, payload_size_bytes, created_at
                FROM webhook_events
                WHERE event_id = $1 AND tenant_id = $2
                """,
                event_id,
                tenant_id,
            )
            if row is None:
                raise NotFoundError(f"Webhook event '{event_id}' not found in tenant {tenant_id}")
            return self._row_to_event(row)

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[WebhookEvent]:
        """List the most recent webhook events for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, endpoint_id, event_id, event_type,
                       status, payload_size_bytes, created_at
                FROM webhook_events
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
            return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: asyncpg.Record) -> WebhookEvent:
        return WebhookEvent(
            id=row["id"],
            tenant_id=row["tenant_id"],
            endpoint_id=row["endpoint_id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            status=WebhookEventStatus(row["status"]),
            payload_size_bytes=row["payload_size_bytes"],
            created_at=row["created_at"],
        )
