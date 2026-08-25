"""PostgreSQL implementation of the ObservabilityRepository contract.

Observability is an aggregation/read layer, NOT a second source of truth
(approved architecture decision). This repository therefore has exactly
one write path — the HTTP telemetry table Observability itself owns — and
every other method is a read-side aggregate issued directly against the
AUTHORITATIVE subsystem tables:

- tool_execution_records  (AI Tools owner)
- connector_sync_records  (Connectors owner)
- webhook_events          (Webhooks owner; MAY BE ABSENT while PR #34 is
                            unmerged — detected via to_regclass and reported
                            as unavailable instead of being duplicated)

Every tenant-scoped aggregate enforces ``tenant_id`` at the SQL level.
Passing ``tenant_id=None`` selects the PLATFORM view: strictly tenant-
agnostic operational totals (no GROUP BY tenant_id ever leaves this
module). No raw rows are returned by any method.
"""

from typing import Optional

from arc.db.connection import ArcDatabase
from arc.domain.models import (
    ApiRequestRecord,
    ConnectorSyncActivityMetrics,
    HttpUsageMetrics,
    ToolExecutionActivityMetrics,
    WebhookEventActivityMetrics,
)


class PostgreSQLObservabilityRepository:
    """PostgreSQL implementation of the ObservabilityRepository contract."""

    WEBHOOK_SOURCE_RELATION = "public.webhook_events"

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create_api_request_record(self, record: ApiRequestRecord) -> ApiRequestRecord:
        """Persist one HTTP telemetry record (best-effort callers only).

        Raises DuplicateKeyError on an identifier collision; callers wrap
        persistence failures so business requests are never affected.
        """
        async with self.db.transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO api_request_records
                    (id, tenant_id, request_id, method, route_template,
                     status_code, duration_ms, error_kind, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING created_at
                """,
                record.id,
                record.tenant_id,
                record.request_id,
                record.method,
                record.route_template,
                record.status_code,
                record.duration_ms,
                record.error_kind,
                record.created_at,
            )
        record.created_at = row["created_at"]
        return record

    @staticmethod
    def _scope_clause(alias: str = "") -> str:
        """Return the shared tenant/window WHERE fragment.

        ``$1`` is the optional tenant scope (NULL = platform-wide) and
        ``$2`` the window length in hours.
        """
        prefix = f"{alias}." if alias else ""
        return (
            f"({prefix}tenant_id = $1 OR $1::varchar IS NULL) "
            f"AND {prefix}created_at >= NOW() - make_interval(hours => $2::int)"
        )

    async def api_request_summary(self, tenant_id: Optional[str], hours: int) -> HttpUsageMetrics:
        """Aggregate HTTP usage for a tenant, or platform-wide when None."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status_code >= 400) AS errors,
                       COALESCE(AVG(duration_ms), 0) AS avg_ms,
                       COALESCE(
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), 0
                       ) AS p95_ms
                FROM api_request_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        total = row["total"]
        errors = row["errors"]
        return HttpUsageMetrics(
            total_requests=total,
            error_count=errors,
            error_rate=(errors / total) if total else 0.0,
            avg_duration_ms=float(row["avg_ms"]),
            p95_duration_ms=float(row["p95_ms"]),
        )

    async def tool_execution_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> ToolExecutionActivityMetrics:
        """Aggregate authoritative AI Tool execution records in place."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'success') AS successful,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE authorization_outcome = 'denied') AS denied
                FROM tool_execution_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return ToolExecutionActivityMetrics(
            total_executions=row["total"],
            successful=row["successful"],
            failed=row["failed"],
            denied=row["denied"],
        )

    async def connector_sync_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> ConnectorSyncActivityMetrics:
        """Aggregate authoritative connector sync records in place."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'success') AS successful,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COALESCE(SUM(items_fetched), 0) AS items
                FROM connector_sync_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return ConnectorSyncActivityMetrics(
            total_syncs=row["total"],
            successful=row["successful"],
            failed=row["failed"],
            items_fetched=row["items"],
        )

    async def _webhook_source_exists(self, conn) -> bool:
        """Detect whether the authoritative webhook_events table exists.

        While the Webhooks foundation (PR #34) is unmerged, main has no
        such table. Observability reports the source as UNAVAILABLE rather
        than creating any duplicate or replacement structure; once PR #34
        merges, aggregation starts consuming it without redesign.
        """
        row = await conn.fetchrow(
            "SELECT to_regclass($1) AS relation", self.WEBHOOK_SOURCE_RELATION
        )
        return row["relation"] is not None

    async def webhook_event_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> WebhookEventActivityMetrics:
        """Aggregate authoritative webhook events when the source exists."""
        async with self.db._connection_pool.acquire() as conn:
            if not await self._webhook_source_exists(conn):
                return WebhookEventActivityMetrics(available=False)
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT event_type) AS distinct_types,
                       COALESCE(SUM(payload_size_bytes), 0) AS payload_bytes
                FROM webhook_events
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return WebhookEventActivityMetrics(
            available=True,
            total_events=row["total"],
            distinct_event_types=row["distinct_types"],
            total_payload_bytes=row["payload_bytes"],
        )

    async def database_reachable(self) -> bool:
        """Component health probe: true when the database answers."""
        try:
            async with self.db._connection_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False
