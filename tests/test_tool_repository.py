"""Tool execution repository tests (real PostgreSQL).

Follows the existing repository test conventions: tenant-scoped SQL,
cross-tenant impossibility at the SQL level, and FK cascade behavior
(PRD 15, TRD 14.2).
"""

import uuid

from arc.domain.models import (
    Tenant,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolRiskLevel,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-repo-{prefix}-{uuid.uuid4().hex[:10]}"


def _record(tenant_id: str, **overrides) -> ToolExecutionRecord:
    """Return a valid ToolExecutionRecord with overridable fields."""
    values = {
        "id": _unique("record"),
        "tenant_id": tenant_id,
        "tool_name": "check_service_health",
        "tool_version": "1",
        "status": ToolExecutionStatus.SUCCESS,
        "risk_level": ToolRiskLevel.LOW,
        "input_summary": "{}",
        "output_summary": '{"services": []}',
    }
    values.update(overrides)
    return ToolExecutionRecord(**values)


async def _seed_tenant(tenant_repo) -> Tenant:
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Repo Tenant"))


async def test_create_record_round_trip(db, repositories):
    repo = PostgreSQLToolExecutionRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await _seed_tenant(tenant_repo)

    record = _record(tenant.id)
    created = await repo.create_record(record)
    assert created.id == record.id

    records = await repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    persisted = records[0]
    assert persisted.id == record.id
    assert persisted.tenant_id == tenant.id
    assert persisted.tool_name == "check_service_health"
    assert persisted.tool_version == "1"
    assert persisted.status == ToolExecutionStatus.SUCCESS
    assert persisted.risk_level == ToolRiskLevel.LOW
    assert persisted.input_summary == "{}"
    assert persisted.output_summary == '{"services": []}'
    assert persisted.error_kind is None


async def test_failed_record_round_trip(db, repositories):
    repo = PostgreSQLToolExecutionRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await _seed_tenant(tenant_repo)

    await repo.create_record(
        _record(
            tenant.id,
            status=ToolExecutionStatus.FAILED,
            output_summary=None,
            error_kind="unknown_tool",
        )
    )

    records = await repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "unknown_tool"
    assert records[0].output_summary is None


async def test_records_are_tenant_isolated_at_sql_level(db, repositories):
    repo = PostgreSQLToolExecutionRepository(db)
    tenant_repo, _, _ = repositories
    tenant_a = await _seed_tenant(tenant_repo)
    tenant_b = await _seed_tenant(tenant_repo)

    await repo.create_record(_record(tenant_a.id))
    await repo.create_record(_record(tenant_a.id))
    await repo.create_record(_record(tenant_b.id))

    tenant_a_records = await repo.list_for_tenant(tenant_a.id)
    tenant_b_records = await repo.list_for_tenant(tenant_b.id)
    assert len(tenant_a_records) == 2
    assert len(tenant_b_records) == 1
    assert all(record.tenant_id == tenant_a.id for record in tenant_a_records)
    assert all(record.tenant_id == tenant_b.id for record in tenant_b_records)


async def test_records_cascade_on_tenant_delete(db, repositories):
    repo = PostgreSQLToolExecutionRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await _seed_tenant(tenant_repo)

    await repo.create_record(_record(tenant.id))
    await tenant_repo.delete(tenant.id)

    assert await repo.list_for_tenant(tenant.id) == []


async def test_list_limit_applies(db, repositories):
    repo = PostgreSQLToolExecutionRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await _seed_tenant(tenant_repo)

    for _ in range(5):
        await repo.create_record(_record(tenant.id))

    records = await repo.list_for_tenant(tenant.id, limit=3)
    assert len(records) == 3
