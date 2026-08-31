"""Real-PostgreSQL tests for the ObservabilityRepository contract.

Covers the write path (metadata-only HTTP telemetry), SQL-level tenant
isolation for every aggregate, cascade behavior, aggregation correctness
against seeded fixtures, time-window filtering, and the TEMPORARY
sequencing behavior around the authoritative webhook_events source:
while PR #34 (Webhooks foundation) is unmerged the table does not exist
on main and aggregates MUST report it as unavailable — never fabricate
or duplicate it. When a table with that exact name exists (as it will
after the merge), aggregation consumes it in place.
"""

import uuid

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import ApiRequestRecord, Tenant
from arc.repositories.observability import PostgreSQLObservabilityRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

# Exact authoritative shape of webhook_events from the Webhooks foundation
# branch (test fixture ONLY: simulates the post-merge state; Observability
# neither creates nor owns this table in product code).
WEBHOOK_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS webhook_events (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    endpoint_id VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'received',
    payload_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_webhook_events_status CHECK (status IN ('received')),
    CONSTRAINT ck_webhook_events_payload_size CHECK (payload_size_bytes >= 0),
    CONSTRAINT uq_webhook_events_tenant_event UNIQUE (tenant_id, event_id)
)
"""


def _api_record(tenant_id=None, status_code=200, duration_ms=10, created_at=None):
    from datetime import datetime, timezone

    return ApiRequestRecord(
        id=f"obs-{uuid.uuid4().hex[:12]}",
        request_id=str(uuid.uuid4()),
        method="GET",
        route_template="/tenants/{tenant_id}/tools",
        status_code=status_code,
        duration_ms=duration_ms,
        tenant_id=tenant_id,
        error_kind=None if status_code < 400 else "client_error",
        created_at=created_at if created_at is not None else datetime.now(timezone.utc),
    )


async def _seed_api_rows(db: ArcDatabase, rows):
    async with db._connection_pool.acquire() as conn:
        for record in rows:
            await conn.execute(
                """
                INSERT INTO api_request_records
                    (id, tenant_id, request_id, method, route_template,
                     status_code, duration_ms, error_kind, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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


class TestApiRequestRecordPersistence:
    async def test_create_round_trip_returns_timestamp(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        record = _api_record()
        result = await repo.create_api_request_record(record)
        assert result is record
        assert result.created_at is not None

    async def test_public_request_persists_with_null_tenant(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        await repo.create_api_request_record(_api_record())
        async with db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tenant_id, error_kind FROM api_request_records "
                "ORDER BY created_at DESC LIMIT 1"
            )
        assert row["tenant_id"] is None
        assert row["error_kind"] is None


class TestAggregationIsolationAndWindows:
    async def test_tenant_isolation_across_every_aggregate(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant_a = await tenants.create(Tenant(id=f"obs-a-{uuid.uuid4().hex[:8]}", name="A"))
        tenant_b = await tenants.create(Tenant(id=f"obs-b-{uuid.uuid4().hex[:8]}", name="B"))
        try:
            await _seed_api_rows(
                db,
                [_api_record(tenant_id=tenant_a.id, status_code=500, duration_ms=500)],
            )
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO tool_execution_records
                       (id, tenant_id, user_id, tool_name, tool_version, status,
                        authorization_outcome, risk_level, input_summary)
                       VALUES ($1,$2,$3,'check_service_health','1','failed','granted','low','x')""",
                    f"tool-{uuid.uuid4().hex[:8]}",
                    tenant_b.id,
                    f"user-{uuid.uuid4().hex[:6]}",
                )
            repo = PostgreSQLObservabilityRepository(db)

            http_a = await repo.api_request_summary(tenant_a.id, 24)
            assert http_a.total_requests == 1 and http_a.error_count == 1

            http_b = await repo.api_request_summary(tenant_b.id, 24)
            assert http_b.total_requests == 0

            tools_a = await repo.tool_execution_activity(tenant_a.id, 24)
            assert tools_a.total_executions == 0

            connectors_b = await repo.connector_sync_activity(tenant_b.id, 24)
            assert connectors_b.total_syncs == 0
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenants WHERE id IN ($1, $2)", tenant_a.id, tenant_b.id
                )

    async def test_cascade_delete_removes_telemetry(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(Tenant(id=f"obs-c-{uuid.uuid4().hex[:8]}", name="C"))
        try:
            await _seed_api_rows(db, [_api_record(tenant_id=tenant.id)])
            async with db._connection_pool.acquire() as conn:
                before = await conn.fetchval(
                    "SELECT COUNT(*) FROM api_request_records WHERE tenant_id = $1", tenant.id
                )
            assert before == 1
        finally:
            await tenants.delete(tenant.id)
        async with db._connection_pool.acquire() as conn:
            after = await conn.fetchval(
                "SELECT COUNT(*) FROM api_request_records WHERE tenant_id = $1", tenant.id
            )
        assert after == 0

    async def test_aggregation_math_and_error_rate(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(Tenant(id=f"obs-d-{uuid.uuid4().hex[:8]}", name="D"))
        try:
            await _seed_api_rows(
                db,
                [
                    _api_record(tenant_id=tenant.id, duration_ms=100),
                    _api_record(tenant_id=tenant.id, duration_ms=200),
                    _api_record(tenant_id=tenant.id, duration_ms=300),
                    _api_record(tenant_id=tenant.id, status_code=404, duration_ms=400),
                ],
            )
            repo = PostgreSQLObservabilityRepository(db)
            summary = await repo.api_request_summary(tenant.id, 24)
            assert summary.total_requests == 4
            assert summary.error_count == 1
            assert summary.error_rate == pytest.approx(0.25)
            assert summary.avg_duration_ms == pytest.approx(250.0)
            assert summary.p95_duration_ms == pytest.approx(380.0, rel=0.05)
        finally:
            await tenants.delete(tenant.id)

    async def test_time_window_excludes_old_records(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(Tenant(id=f"obs-e-{uuid.uuid4().hex[:8]}", name="E"))
        try:
            old = _api_record(tenant_id=tenant.id)
            from datetime import datetime, timedelta, timezone

            old.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
            await _seed_api_rows(db, [old, _api_record(tenant_id=tenant.id)])
            repo = PostgreSQLObservabilityRepository(db)
            recent = await repo.api_request_summary(tenant.id, 24)
            wide = await repo.api_request_summary(tenant.id, 72)
            assert recent.total_requests == 1
            assert wide.total_requests == 2
        finally:
            await tenants.delete(tenant.id)


class TestAuthoritativeSourceAggregation:
    async def test_platform_view_aggregates_without_tenant_dimension(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        http = await repo.api_request_summary(None, 24)
        tools = await repo.tool_execution_activity(None, 24)
        assert http.total_requests >= 0 and tools.total_executions >= 0

    async def test_webhook_source_absent_reports_unavailable(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        async with db._connection_pool.acquire() as conn:
            exists = await conn.fetchval("SELECT to_regclass('public.webhook_events') IS NOT NULL")
        if exists:
            pytest.skip("webhook_events already present (PR #34 merged locally)")
        metrics = await repo.webhook_event_activity(None, 24)
        assert metrics.available is False
        assert metrics.total_events == 0

    async def test_webhook_aggregation_consumes_authoritative_table_when_present(self, db):
        tenants = PostgreSQLTenantRepository(db)
        repo = PostgreSQLObservabilityRepository(db)
        async with db._connection_pool.acquire() as conn:
            already = await conn.fetchval("SELECT to_regclass('public.webhook_events') IS NOT NULL")
        if not already:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(WEBHOOK_EVENTS_DDL)
        tenant = await tenants.create(Tenant(id=f"obs-f-{uuid.uuid4().hex[:8]}", name="F"))
        try:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO webhook_events
                       (id, tenant_id, endpoint_id, event_id, event_type, payload_size_bytes)
                       VALUES ($1,$2,'ep-1','evt-1','health.alert',120),
                              ($2 || '-2',$2,'ep-1','evt-2','health.alert',80)""",
                    f"wh-{uuid.uuid4().hex[:8]}",
                    tenant.id,
                )
            metrics = await repo.webhook_event_activity(tenant.id, 24)
            assert metrics.available is True
            assert metrics.total_events == 2
            assert metrics.distinct_event_types == 1
            assert metrics.total_payload_bytes == 200
            other = await repo.webhook_event_activity(f"other-{uuid.uuid4().hex[:6]}", 24)
            assert other.total_events == 0
        finally:
            await tenants.delete(tenant.id)
            if not already:
                async with db._connection_pool.acquire() as conn:
                    await conn.execute("DROP TABLE IF EXISTS webhook_events")

    async def test_database_reachable_true_on_healthy_database(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        assert await repo.database_reachable() is True


class TestApprovalAggregate:
    async def test_tenant_isolation_for_approval_aggregate(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant_a = await tenants.create(Tenant(id=f"obs-app-a-{uuid.uuid4().hex[:6]}", name="AppA"))
        tenant_b = await tenants.create(Tenant(id=f"obs-app-b-{uuid.uuid4().hex[:6]}", name="AppB"))
        try:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO approval_requests
                       (id, tenant_id, requested_by_user_id, tool_name, tool_version,
                        risk_level, input_summary, arguments_digest, status, expires_at)
                       VALUES ($1,$2,$3,'check_service_health','1','low','s',
                               repeat('a', 64), 'pending',
                               CURRENT_TIMESTAMP + INTERVAL '24 hours')""",
                    f"apr-{uuid.uuid4().hex[:8]}",
                    tenant_a.id,
                    f"u-{uuid.uuid4().hex[:6]}",
                )
            repo = PostgreSQLObservabilityRepository(db)
            agg_a = await repo.approval_activity(tenant_a.id, 24)
            agg_b = await repo.approval_activity(tenant_b.id, 24)
            assert agg_a.total == 1
            assert agg_a.pending == 1
            assert agg_b.total == 0
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenants WHERE id IN ($1, $2)", tenant_a.id, tenant_b.id
                )

    async def test_approval_aggregation_math(self, db):
        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(Tenant(id=f"obs-app-c-{uuid.uuid4().hex[:6]}", name="AppC"))
        try:
            async with db._connection_pool.acquire() as conn:
                statuses = [
                    "pending",
                    "approved",
                    "rejected",
                    "expired",
                    "consumed",
                ]
                for i, status in enumerate(statuses):
                    await conn.execute(
                        """INSERT INTO approval_requests
                           (id, tenant_id, requested_by_user_id,
                            tool_name, tool_version, risk_level,
                            input_summary, arguments_digest,
                            status, expires_at)
                           VALUES ($1,$2,$3,
                                   'check_service_health','1','low','s',
                                   repeat('a', 64), $4,
                                   CURRENT_TIMESTAMP
                                   + INTERVAL '24 hours')""",
                        f"apr-math-{i}-{uuid.uuid4().hex[:6]}",
                        tenant.id,
                        f"u-{uuid.uuid4().hex[:6]}",
                        status,
                    )
            repo = PostgreSQLObservabilityRepository(db)
            metrics = await repo.approval_activity(tenant.id, 24)
            assert metrics.total == 5
            assert metrics.pending == 1
            assert metrics.approved == 1
            assert metrics.rejected == 1
            assert metrics.expired == 1
            assert metrics.consumed == 1
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute("DELETE FROM tenants WHERE id = $1", tenant.id)

    async def test_time_window_excludes_old_approval_records(self, db):
        from datetime import datetime, timedelta, timezone

        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(Tenant(id=f"obs-app-d-{uuid.uuid4().hex[:6]}", name="AppD"))
        try:
            old_time = datetime.now(timezone.utc) - timedelta(hours=48)
            old_expiry = old_time + timedelta(hours=24)
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO approval_requests
                       (id, tenant_id, requested_by_user_id, tool_name, tool_version,
                        risk_level, input_summary, arguments_digest, status, created_at, expires_at)
                       VALUES ($1,$2,$3,'check_service_health','1','low','s',
                               repeat('a', 64), 'pending', $4, $5)""",
                    f"apr-old-{uuid.uuid4().hex[:6]}",
                    tenant.id,
                    f"u-{uuid.uuid4().hex[:6]}",
                    old_time,
                    old_expiry,
                )
                await conn.execute(
                    """INSERT INTO approval_requests
                       (id, tenant_id, requested_by_user_id,
                        tool_name, tool_version, risk_level,
                        input_summary, arguments_digest,
                        status, expires_at)
                       VALUES ($1,$2,$3,
                               'check_service_health','1','low','s',
                               repeat('a', 64), 'approved',
                               CURRENT_TIMESTAMP
                               + INTERVAL '24 hours')""",
                    f"apr-new-{uuid.uuid4().hex[:6]}",
                    tenant.id,
                    f"u-{uuid.uuid4().hex[:6]}",
                )
            repo = PostgreSQLObservabilityRepository(db)
            recent = await repo.approval_activity(tenant.id, 24)
            wide = await repo.approval_activity(tenant.id, 72)
            assert recent.total == 1
            assert recent.approved == 1
            assert wide.total == 2
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute("DELETE FROM tenants WHERE id = $1", tenant.id)

    async def test_platform_view_includes_approval_totals(self, db):
        repo = PostgreSQLObservabilityRepository(db)
        metrics = await repo.approval_activity(None, 24)
        assert metrics.total >= 0
        assert isinstance(metrics.pending, int)
