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
    AgentRunActivityMetrics,
    AgentRunRecord,
    AgentRunRecordStep,
    ApiRequestRecord,
    ApprovalActivityMetrics,
    ConnectorSyncActivityMetrics,
    HttpUsageMetrics,
    LlmUsageActivityMetrics,
    LlmUsageRecord,
    SkillExecutionActivityMetrics,
    ToolExecutionActivityMetrics,
    WebhookEventActivityMetrics,
)
from arc.repositories import DEFAULT_LIST_LIMIT


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

    async def skill_execution_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> SkillExecutionActivityMetrics:
        """Aggregate authoritative skill execution records in place."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE status = 'approval_required') AS approval_required,
                       COUNT(*) FILTER (WHERE status = 'denied') AS denied
                FROM skill_execution_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return SkillExecutionActivityMetrics(
            total_executions=row["total"],
            succeeded=row["succeeded"],
            failed=row["failed"],
            approval_required=row["approval_required"],
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

    async def approval_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> ApprovalActivityMetrics:
        """Aggregate authoritative approval requests in place.

        The ``approval_requests`` table is always present (created by
        schema bootstrap).  Every tenant-scoped aggregate enforces
        ``tenant_id`` at the SQL level; ``None`` selects the platform
        view.
        """
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                       COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                       COUNT(*) FILTER (WHERE status = 'expired') AS expired,
                       COUNT(*) FILTER (WHERE status = 'consumed') AS consumed
                FROM approval_requests
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return ApprovalActivityMetrics(
            total=row["total"],
            pending=row["pending"],
            approved=row["approved"],
            rejected=row["rejected"],
            expired=row["expired"],
            consumed=row["consumed"],
        )

    # ------------------------------------------------------------------
    # Agent execution trace (PRD 17 O-6)
    # ------------------------------------------------------------------
    async def create_agent_run_record(self, record: AgentRunRecord) -> AgentRunRecord:
        """Persist one agent execution trace (best-effort callers only).

        The ``agent_run_records`` table is the authoritative write path
        for agent runs; no prior table persisted them.  Steps are stored
        as a JSONB array so the trace is fully queryable.
        """
        import json

        steps_json = json.dumps([step.to_dict() for step in record.steps])
        async with self.db.transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agent_run_records
                    (id, tenant_id, principal_id, goal, status, error_kind,
                     steps, created_at, started_at, completed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                RETURNING created_at
                """,
                record.id,
                record.tenant_id,
                record.principal_id,
                record.goal,
                record.status,
                record.error_kind,
                steps_json,
                record.created_at,
                record.started_at,
                record.completed_at,
            )
        record.created_at = row["created_at"]
        return record

    async def get_agent_run_record(self, record_id: str, tenant_id: str) -> AgentRunRecord:
        """Read one agent run trace within the trusted tenant."""
        import json

        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, principal_id, goal, status, error_kind,
                       steps, created_at, started_at, completed_at
                FROM agent_run_records
                WHERE id = $1 AND tenant_id = $2
                """,
                record_id,
                tenant_id,
            )
        if row is None:
            from arc.db.connection import NotFoundError

            raise NotFoundError(f"Agent run record {record_id} not found")
        steps_raw = row["steps"]
        if isinstance(steps_raw, str):
            steps_raw = json.loads(steps_raw)
        steps = [AgentRunRecordStep.from_dict(s) for s in steps_raw]
        return AgentRunRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],
            goal=row["goal"],
            status=row["status"],
            error_kind=row["error_kind"],
            steps=steps,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    async def list_agent_run_records(
        self, tenant_id: str, hours: int = 24, limit: int = DEFAULT_LIST_LIMIT
    ) -> list:
        """List agent run traces for a tenant within a time window."""
        import json

        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, tenant_id, principal_id, goal, status, error_kind,
                       steps, created_at, started_at, completed_at
                FROM agent_run_records
                WHERE {self._scope_clause()}
                ORDER BY created_at DESC, id ASC
                LIMIT $3
                """,
                tenant_id,
                hours,
                limit,
            )
        results = []
        for row in rows:
            steps_raw = row["steps"]
            if isinstance(steps_raw, str):
                steps_raw = json.loads(steps_raw)
            steps = [AgentRunRecordStep.from_dict(s) for s in steps_raw]
            results.append(
                AgentRunRecord(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    principal_id=row["principal_id"],
                    goal=row["goal"],
                    status=row["status"],
                    error_kind=row["error_kind"],
                    steps=steps,
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
            )
        return results

    async def list_agent_run_records_paginated(
        self, tenant_id: str, hours: int, limit: int, offset: int
    ) -> tuple:
        """List agent run traces with LIMIT/OFFSET and total count."""
        import json

        async with self.db._connection_pool.acquire() as conn:
            count_row = await conn.fetchrow(
                f"SELECT COUNT(*) AS cnt FROM agent_run_records WHERE {self._scope_clause()}",
                tenant_id,
                hours,
            )
            total = count_row["cnt"]
            rows = await conn.fetch(
                f"""
                SELECT id, tenant_id, principal_id, goal, status, error_kind,
                       steps, created_at
                FROM agent_run_records
                WHERE {self._scope_clause()}
                ORDER BY created_at DESC, id ASC
                LIMIT $3 OFFSET $4
                """,
                tenant_id,
                hours,
                limit,
                offset,
            )
        results = []
        for row in rows:
            steps_raw = row["steps"]
            if isinstance(steps_raw, str):
                steps_raw = json.loads(steps_raw)
            steps = [AgentRunRecordStep.from_dict(s) for s in steps_raw]
            results.append(
                AgentRunRecord(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    principal_id=row["principal_id"],
                    goal=row["goal"],
                    status=row["status"],
                    error_kind=row["error_kind"],
                    steps=steps,
                    created_at=row["created_at"],
                )
            )
        return results, total

    async def agent_run_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> AgentRunActivityMetrics:
        """Aggregate authoritative agent run records in place."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE status = 'approval_required') AS approval_required,
                       COUNT(*) FILTER (WHERE status = 'max_steps_reached') AS max_steps_reached
                FROM agent_run_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
        return AgentRunActivityMetrics(
            total_runs=row["total"],
            succeeded=row["succeeded"],
            failed=row["failed"],
            approval_required=row["approval_required"],
            max_steps_reached=row["max_steps_reached"],
        )

    # ------------------------------------------------------------------
    # Escalation count (PRD 17 O-7)
    # ------------------------------------------------------------------
    async def escalation_count(self, tenant_id: Optional[str], hours: int) -> int:
        """Count human escalations (approved + rejected approvals).

        Escalations are human decisions on approval requests: APPROVED
        or REJECTED statuses indicate a human intervened.
        """
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS cnt
                FROM approval_requests
                WHERE {self._scope_clause()}
                  AND status IN ('approved', 'rejected')
                """,
                tenant_id,
                hours,
            )
        return row["cnt"]

    async def database_reachable(self) -> bool:
        """Component health probe: true when the database answers."""
        try:
            async with self.db._connection_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # LLM usage telemetry (V2-ADR-024, TRD 13, Issue #141)
    # ------------------------------------------------------------------
    async def create_llm_usage_record(self, record: LlmUsageRecord) -> None:
        """Persist one LLM usage telemetry record (best-effort callers only)."""
        async with self.db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO llm_usage_records
                    (id, tenant_id, request_id, agent_run_id, principal_id,
                     provider, model, input_tokens, output_tokens, total_tokens,
                     latency_ms, cost_usd, call_type, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                record.id,
                record.tenant_id,
                record.request_id,
                record.agent_run_id,
                record.principal_id,
                record.provider,
                record.model,
                record.input_tokens,
                record.output_tokens,
                record.total_tokens,
                record.latency_ms,
                str(record.cost_usd) if record.cost_usd is not None else None,
                record.call_type,
                record.created_at,
            )

    async def llm_usage_activity(
        self, tenant_id: Optional[str], hours: int
    ) -> LlmUsageActivityMetrics:
        """Aggregate LLM usage for a tenant, or platform-wide when None."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    COUNT(*) AS total_calls,
                    COALESCE(SUM(input_tokens), 0) AS total_input,
                    COALESCE(SUM(output_tokens), 0) AS total_output,
                    COALESCE(SUM(total_tokens), 0) AS total_all,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency,
                    SUM(cost_usd) AS total_cost,
                    COUNT(*) FILTER (WHERE cost_usd IS NULL) AS unknown_cost,
                    COUNT(DISTINCT model) AS model_count
                FROM llm_usage_records
                WHERE {self._scope_clause()}
                """,
                tenant_id,
                hours,
            )
            type_rows = await conn.fetch(
                f"""
                SELECT call_type, COUNT(*) AS cnt
                FROM llm_usage_records
                WHERE {self._scope_clause()}
                GROUP BY call_type
                """,
                tenant_id,
                hours,
            )
            model_rows = await conn.fetch(
                f"""
                SELECT DISTINCT model
                FROM llm_usage_records
                WHERE {self._scope_clause()}
                ORDER BY model
                """,
                tenant_id,
                hours,
            )

        calls_by_type = {r["call_type"]: r["cnt"] for r in type_rows}
        models_used = [r["model"] for r in model_rows]
        total_cost_raw = row["total_cost"]

        from decimal import Decimal

        total_cost = Decimal(str(total_cost_raw)) if total_cost_raw is not None else None

        return LlmUsageActivityMetrics(
            total_calls=row["total_calls"],
            calls_by_type=calls_by_type,
            total_input_tokens=row["total_input"],
            total_output_tokens=row["total_output"],
            total_tokens=row["total_all"],
            avg_latency_ms=float(row["avg_latency"]),
            total_cost_usd=total_cost,
            unknown_cost_records=row["unknown_cost"],
            models_used=models_used,
        )

    async def llm_usage_records_page(
        self,
        tenant_id: str,
        hours: int,
        call_type: Optional[str],
        limit: int,
        offset: int,
    ) -> tuple:
        """Return (records, total_count) for paginated LLM usage records."""
        from decimal import Decimal as Dec

        async with self.db._connection_pool.acquire() as conn:
            if call_type:
                total_row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM llm_usage_records
                    WHERE {self._scope_clause()} AND call_type = $3
                    """,
                    tenant_id,
                    hours,
                    call_type,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT id, provider, model, input_tokens, output_tokens,
                           total_tokens, latency_ms, cost_usd, call_type,
                           request_id, agent_run_id, created_at
                    FROM llm_usage_records
                    WHERE {self._scope_clause()} AND call_type = $3
                    ORDER BY created_at DESC, id ASC
                    LIMIT $4 OFFSET $5
                    """,
                    tenant_id,
                    hours,
                    call_type,
                    limit,
                    offset,
                )
            else:
                total_row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM llm_usage_records
                    WHERE {self._scope_clause()}
                    """,
                    tenant_id,
                    hours,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT id, provider, model, input_tokens, output_tokens,
                           total_tokens, latency_ms, cost_usd, call_type,
                           request_id, agent_run_id, created_at
                    FROM llm_usage_records
                    WHERE {self._scope_clause()}
                    ORDER BY created_at DESC, id ASC
                    LIMIT $3 OFFSET $4
                    """,
                    tenant_id,
                    hours,
                    limit,
                    offset,
                )
        total_count = total_row["cnt"] if total_row else 0
        results = []
        for r in rows:
            cost = Dec(str(r["cost_usd"])) if r["cost_usd"] is not None else None
            results.append(
                {
                    "id": r["id"],
                    "provider": r["provider"],
                    "model": r["model"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "total_tokens": r["total_tokens"],
                    "latency_ms": r["latency_ms"],
                    "cost_usd": cost,
                    "call_type": r["call_type"],
                    "request_id": r["request_id"],
                    "agent_run_id": r["agent_run_id"],
                    "created_at": r["created_at"],
                }
            )
        return results, total_count
