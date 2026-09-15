"""Tool evaluation: execution flow (Issue #139, V2-ADR-023).

5 deterministic cases testing tool execution lifecycle.
"""

import pytest

from arc.domain.models import (
    TenantContext,
    UserRole,
)
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolExecutionError,
    ToolExecutionService,
    ToolNotFoundError,
    ToolRegistry,
    build_platform_tool_registry,
)

from .golden_datasets import tool_execution_flow_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _principal(user_id="user-eval"):
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id="user-eval", role=ApplicationRole.OPERATIONS_USER):
    return AuthorizationService({user_id: role})


class FakeRecordRepo:
    """In-memory tool execution record repository."""

    def __init__(self):
        self.records = []

    async def create_record(self, record):
        self.records.append(record)
        return record

    async def list_for_tenant(self, tenant_id):
        return [r for r in self.records if r.tenant_id == tenant_id]


@pytest.fixture
def service_and_repo():
    """Create ToolExecutionService with real registry and fake record repo."""
    registry = build_platform_tool_registry()
    record_repo = FakeRecordRepo()
    service = ToolExecutionService(registry, record_repo)
    return service, record_repo


@pytest.mark.parametrize("fixture", tool_execution_flow_fixtures(), ids=lambda f: f["description"])
async def test_execution_flow(service_and_repo, fixture):
    """Tool execution lifecycle produces expected outcome."""
    service, record_repo = service_and_repo
    context = _context()

    if fixture["expected_outcome"] == "not_found":
        with pytest.raises(ToolNotFoundError):
            await service.execute_tool(
                context, _principal(), "nonexistent_tool", {}, _authorization()
            )

    elif fixture["expected_outcome"] == "success":
        result = await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )
        assert result is not None
        assert result.tool_name == "check_service_health"

    elif fixture["expected_outcome"] == "output_captured":
        result = await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )
        assert result.output is not None
        assert isinstance(result.output, dict)

    elif fixture["expected_outcome"] == "audit_created":
        await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )
        records = await record_repo.list_for_tenant(context.tenant_id)
        assert len(records) >= 1

    elif fixture["expected_outcome"] == "execution_error":
        # Create a tool that raises on execution
        from dataclasses import replace

        def failing_handler(ctx, args):
            raise ToolExecutionError("Simulated failure")

        tool = replace(SERVICE_HEALTH_TOOL, handler=failing_handler)
        failing_service = ToolExecutionService(ToolRegistry({tool.name: tool}), FakeRecordRepo())
        with pytest.raises(ToolExecutionError):
            await failing_service.execute_tool(
                context, _principal(), "check_service_health", {}, _authorization()
            )
