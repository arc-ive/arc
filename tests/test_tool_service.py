"""AI Tool execution service tests (TRD 14.1 flow, real PostgreSQL).

The service executes the controlled flow: selection -> (authorization,
enforced upstream by the controller dependency) -> tool policy check ->
input validation -> execution -> result handling -> execution/audit
record. Every controlled attempt, including controlled failures, produces
an observable tenant-scoped record.
"""

import uuid
from dataclasses import replace

import pytest

from arc.domain.models import Tenant, TenantContext, ToolExecutionStatus, UserRole
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionPolicy,
    ToolExecutionService,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    _summarize,
    build_platform_tool_registry,
)


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-service-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Tool Service Tenant",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


async def _build_service(repositories, db):
    """Create a service wired to real PostgreSQL and a fresh tenant."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    service = ToolExecutionService(build_platform_tool_registry(), record_repo)
    return service, record_repo, tenant


def _registry_with_handler(handler):
    """Build a registry containing check_service_health with a custom handler."""
    tool = replace(SERVICE_HEALTH_TOOL, handler=handler)
    return ToolRegistry({tool.name: tool})


async def test_list_tools_returns_platform_catalog(repositories, db):
    service, _, _ = await _build_service(repositories, db)
    tools = service.list_tools(_context("tenant-a"))
    assert [tool.name for tool in tools] == ["check_service_health"]


async def test_check_service_health_executes_deterministically(repositories, db):
    service, _, tenant = await _build_service(repositories, db)

    first = await service.execute_tool(_context(tenant.id), "check_service_health", {})
    second = await service.execute_tool(_context(tenant.id), "check_service_health", {})

    assert first.tool_name == "check_service_health"
    assert first.tool_version == "1"
    assert first.output == second.output
    assert first.output["tenant_id"] == tenant.id
    assert {entry["status"] for entry in first.output["services"]} == {"healthy"}


async def test_successful_execution_creates_success_record(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    await service.execute_tool(_context(tenant.id), "check_service_health", {})

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.error_kind is None
    assert record.tool_name == "check_service_health"
    assert record.tool_version == "1"
    assert record.risk_level == SERVICE_HEALTH_TOOL.risk_level
    assert record.output_summary is not None


async def test_unknown_tool_fails_closed_and_records_failure(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolNotFoundError):
        await service.execute_tool(_context(tenant.id), "restart_service", {})

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "unknown_tool"
    assert records[0].tool_name == "restart_service"


async def test_unknown_tool_never_invokes_anything(repositories, db):
    service, _, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolNotFoundError):
        await service.execute_tool(_context(tenant.id), "__import__", {})

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].error_kind == "unknown_tool"


async def test_invalid_input_is_rejected_and_handler_never_runs(repositories, db):
    calls = []

    def spy(input_data, tenant_id):
        calls.append((input_data, tenant_id))
        return {"tenant_id": tenant_id, "services": []}

    service = ToolExecutionService(
        _registry_with_handler(spy), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    with pytest.raises(ToolValidationError):
        await service.execute_tool(context, "check_service_health", {"extra": 1})

    assert calls == []
    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "invalid_input"


async def test_valid_input_reaches_handler_with_trusted_tenant(repositories, db):
    calls = []

    def spy(input_data, tenant_id):
        calls.append((input_data, tenant_id))
        return {"tenant_id": tenant_id, "services": []}

    service = ToolExecutionService(
        _registry_with_handler(spy), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))

    await service.execute_tool(_context(tenant.id), "check_service_health", {})

    assert calls == [({}, tenant.id)]


async def test_handler_failure_records_controlled_failure(repositories, db):
    def boom(input_data, tenant_id):
        raise RuntimeError("secret internal detail")

    service = ToolExecutionService(
        _registry_with_handler(boom), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    with pytest.raises(ToolExecutionError):
        await service.execute_tool(context, "check_service_health", {})

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.FAILED
    assert record.error_kind == "execution_error"
    assert "secret internal detail" not in record.input_summary
    assert "secret internal detail" not in (record.output_summary or "")
    assert "secret internal detail" not in (record.error_kind or "")


async def test_policy_denial_records_failure(repositories, db):
    tool = replace(
        SERVICE_HEALTH_TOOL,
        execution_policy=ToolExecutionPolicy(direct_execution_allowed=False),
    )
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(context, "check_service_health", {})

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "not_allowed"


async def test_execution_records_are_tenant_scoped(repositories, db):
    service, record_repo, _ = await _build_service(repositories, db)
    tenant_repo, _, _ = repositories
    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant B"))

    await service.execute_tool(_context(tenant_a.id), "check_service_health", {})
    await service.execute_tool(_context(tenant_b.id), "check_service_health", {})

    tenant_a_records = await record_repo.list_for_tenant(tenant_a.id)
    tenant_b_records = await record_repo.list_for_tenant(tenant_b.id)
    assert len(tenant_a_records) == 1
    assert len(tenant_b_records) == 1
    assert tenant_a_records[0].tenant_id == tenant_a.id
    assert tenant_b_records[0].tenant_id == tenant_b.id


async def test_validation_error_before_execution_never_records_success(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolValidationError):
        await service.execute_tool(_context(tenant.id), "check_service_health", {"extra": 1})

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED


def test_summary_is_truncated_and_safe():
    long_value = {"data": "x" * 10000}
    summary = _summarize(long_value, max_length=100)
    assert len(summary) <= 100
    assert summary.startswith('{"data": "xxx')
