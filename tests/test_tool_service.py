"""AI Tool execution service tests (TRD 14.1 flow, real PostgreSQL).

The service executes the controlled flow: selection -> per-tool
authorization (``tool:execute`` AND every declared required permission,
fail closed) -> tool policy check -> input validation -> execution ->
result handling -> execution/audit record. Every controlled attempt,
including controlled failures and authorization denials, produces an
observable tenant-scoped record.
"""

import uuid
from dataclasses import replace

import pytest
from pydantic import BaseModel, ConfigDict

from arc.domain.models import (
    Tenant,
    TenantContext,
    ToolAuthorizationOutcome,
    ToolExecutionStatus,
    ToolRiskLevel,
    UserRole,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import (
    KNOWLEDGE_READ,
    TENANT_CREATE,
    TOOL_EXECUTE,
    AuthorizationService,
)
from arc.security.models import ApplicationRole, AuthenticatedPrincipal, Permission
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionPolicy,
    ToolExecutionPolicyMode,
    ToolExecutionService,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    _summarize,
    build_platform_tool_registry,
)

RESTART_PERMISSION = Permission(resource="tool", action="restart")


class EchoInput(BaseModel):
    """Test-only input model that accepts arbitrary fields."""

    model_config = ConfigDict(extra="allow")


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


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(
    user_id: str = "user-1", role: ApplicationRole = ApplicationRole.OPERATIONS_USER
) -> AuthorizationService:
    return AuthorizationService({user_id: role})


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


def _malformed_definition(required_permissions):
    """Build a ToolDefinition bypassing construction-time validation.

    Proves the service fails closed even when a malformed definition
    somehow exists in a registry (defense in depth).
    """
    tool = object.__new__(type(SERVICE_HEALTH_TOOL))
    for key, value in SERVICE_HEALTH_TOOL.__dict__.items():
        object.__setattr__(tool, key, value)
    object.__setattr__(tool, "required_permissions", required_permissions)
    return tool


async def test_list_tools_returns_platform_catalog(repositories, db):
    service, _, _ = await _build_service(repositories, db)
    tools = service.list_tools(_context("tenant-a"))
    assert [tool.name for tool in tools] == ["check_service_health"]


async def test_check_service_health_executes_deterministically(repositories, db):
    service, _, tenant = await _build_service(repositories, db)
    context = _context(tenant.id)

    first = await service.execute_tool(
        context, _principal(), "check_service_health", {}, _authorization()
    )
    second = await service.execute_tool(
        context, _principal(), "check_service_health", {}, _authorization()
    )

    assert first.tool_name == "check_service_health"
    assert first.tool_version == "1"
    assert first.output == second.output
    assert first.output["tenant_id"] == tenant.id
    assert {entry["status"] for entry in first.output["services"]} == {"healthy"}


async def test_successful_execution_creates_success_record(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    await service.execute_tool(
        _context(tenant.id), _principal(), "check_service_health", {}, _authorization()
    )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.authorization_outcome == ToolAuthorizationOutcome.GRANTED
    assert record.user_id == "user-1"
    assert record.error_kind is None
    assert record.tool_name == "check_service_health"
    assert record.tool_version == "1"
    assert record.risk_level == SERVICE_HEALTH_TOOL.risk_level
    assert record.output_summary is not None


async def test_unknown_tool_fails_closed_and_records_failure(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolNotFoundError):
        await service.execute_tool(
            _context(tenant.id), _principal(), "restart_service", {}, _authorization()
        )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert records[0].error_kind == "unknown_tool"
    assert records[0].tool_name == "restart_service"


async def test_unknown_tool_never_invokes_anything(repositories, db):
    service, _, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolNotFoundError):
        await service.execute_tool(
            _context(tenant.id), _principal(), "__import__", {}, _authorization()
        )

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
        await service.execute_tool(
            context, _principal(), "check_service_health", {"extra": 1}, _authorization()
        )

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

    await service.execute_tool(
        _context(tenant.id), _principal(), "check_service_health", {}, _authorization()
    )

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
        await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )

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
        execution_policy=ToolExecutionPolicy(mode=ToolExecutionPolicyMode.DENY),
    )
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "not_allowed"


async def test_human_approval_policy_fails_closed(repositories, db):
    """REQUIRE_HUMAN_APPROVAL is an explicit future/fail-closed state:
    the Human Intervention gate is not implemented, so execution is
    denied and audited instead of silently proceeding."""
    tool = replace(
        SERVICE_HEALTH_TOOL,
        execution_policy=ToolExecutionPolicy(mode=ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL),
    )
    service = ToolExecutionService(
        ToolRegistry({tool.name: tool}), PostgreSQLToolExecutionRepository(db)
    )
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            context, _principal(), "check_service_health", {}, _authorization()
        )

    records = await service.record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "requires_human_approval"


async def test_execution_requires_tool_execute_and_each_required_permission(repositories, db):
    """Per-tool authorization: the caller must hold ``tool:execute`` AND
    every permission declared by the tool (TRD 14.2)."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    dual_permission_tool = replace(
        SERVICE_HEALTH_TOOL,
        name="dual_permission_tool",
        required_permissions=frozenset({TOOL_EXECUTE, KNOWLEDGE_READ}),
    )
    service = ToolExecutionService(
        ToolRegistry({dual_permission_tool.name: dual_permission_tool}), record_repo
    )

    # OPERATIONS_USER holds tool:execute AND knowledge:read -> allowed.
    result = await service.execute_tool(
        context,
        _principal("ops-user"),
        "dual_permission_tool",
        {},
        _authorization("ops-user", ApplicationRole.OPERATIONS_USER),
    )
    assert result.tool_name == "dual_permission_tool"

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.SUCCESS
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.GRANTED
    assert records[0].user_id == "ops-user"


async def test_tool_execute_alone_does_not_grant_tool_specific_permission(repositories, db):
    """tool:execute must NOT be a universal master key: a user holding it
    but missing a tool-declared permission is denied (403-equivalent)."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    elevated_tool = replace(
        SERVICE_HEALTH_TOOL,
        name="provisioning_tool",
        required_permissions=frozenset({TOOL_EXECUTE, TENANT_CREATE}),
    )
    service = ToolExecutionService(ToolRegistry({elevated_tool.name: elevated_tool}), record_repo)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            context,
            _principal("ops-user"),
            "provisioning_tool",
            {},
            _authorization("ops-user", ApplicationRole.OPERATIONS_USER),
        )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert records[0].error_kind == "authorization_denied"
    assert records[0].user_id == "ops-user"


async def test_user_with_all_required_permissions_is_allowed(repositories, db):
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    elevated_tool = replace(
        SERVICE_HEALTH_TOOL,
        name="provisioning_tool",
        required_permissions=frozenset({TOOL_EXECUTE, TENANT_CREATE}),
    )
    service = ToolExecutionService(ToolRegistry({elevated_tool.name: elevated_tool}), record_repo)

    result = await service.execute_tool(
        context,
        _principal("platform-user"),
        "provisioning_tool",
        {},
        _authorization("platform-user", ApplicationRole.PLATFORM_ADMINISTRATOR),
    )
    assert result.tool_name == "provisioning_tool"


async def test_unknown_permission_in_definition_denies_execution(repositories, db):
    """A tool declaring a permission no role holds is denied (fail closed)."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    unknown_permission_tool = replace(
        SERVICE_HEALTH_TOOL,
        name="unknown_permission_tool",
        required_permissions=frozenset({RESTART_PERMISSION}),
    )
    service = ToolExecutionService(
        ToolRegistry({unknown_permission_tool.name: unknown_permission_tool}), record_repo
    )

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            context,
            _principal("platform-user"),
            "unknown_permission_tool",
            {},
            _authorization("platform-user", ApplicationRole.PLATFORM_ADMINISTRATOR),
        )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert records[0].error_kind == "authorization_denied"


async def test_missing_permission_metadata_fails_closed(repositories, db):
    """Malformed definition with EMPTY required_permissions: denied before
    any handler runs (fail closed), audited as invalid metadata."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    malformed = _malformed_definition(required_permissions=frozenset())
    service = ToolExecutionService(ToolRegistry({malformed.name: malformed}), record_repo)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(context, _principal(), malformed.name, {}, _authorization())

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert records[0].error_kind == "invalid_permission_metadata"


async def test_invalid_permission_metadata_fails_closed(repositories, db):
    """Malformed definition with NON-Permission entries: denied before any
    handler runs (fail closed), audited as invalid metadata."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    malformed = _malformed_definition(required_permissions=frozenset({"tool:execute"}))
    service = ToolExecutionService(ToolRegistry({malformed.name: malformed}), record_repo)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(context, _principal(), malformed.name, {}, _authorization())

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert records[0].error_kind == "invalid_permission_metadata"


async def test_unassigned_user_is_denied(repositories, db):
    """A user with no application role is denied (default DENY)."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)
    service = ToolExecutionService(build_platform_tool_registry(), record_repo)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            context,
            _principal("unknown-user"),
            "check_service_health",
            {},
            _authorization("somebody-else"),
        )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].error_kind == "authorization_denied"
    assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED


async def test_invalid_tenant_context_fails_closed_without_record(repositories, db):
    """A missing/invalid tenant context denies the attempt with NO record:
    there is no trusted tenant to attribute an audit record to."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    service = ToolExecutionService(build_platform_tool_registry(), record_repo)

    invalid_context = TenantContext(
        tenant_id=tenant.id,
        tenant_name="Tool Service Tenant",
        user_id="user-1",
        role=None,  # invalid: no trusted role
    )
    assert not invalid_context.is_valid

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(
            invalid_context, _principal(), "check_service_health", {}, _authorization()
        )

    assert await record_repo.list_for_tenant(tenant.id) == []


async def test_sensitive_input_values_never_reach_audit_records(repositories, db):
    """Data minimization (TRD 14.2): API keys, passwords, and tokens are
    redacted from execution records."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    def echo(input_data, tenant_id):
        return {"echoed": input_data}

    spy_tool = replace(SERVICE_HEALTH_TOOL, name="echo_tool", input_model=EchoInput, handler=echo)
    service = ToolExecutionService(ToolRegistry({spy_tool.name: spy_tool}), record_repo)

    await service.execute_tool(
        context,
        _principal(),
        "echo_tool",
        {
            "api_key": "sk-live-1234567890",
            "password": "hunter2-secret",
            "token": "eyJhbGciOiJIUzI1NiJ9.payload",
            "safe_field": "plain-value",
        },
        _authorization(),
    )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    record = records[0]
    for sensitive in ("sk-live-1234567890", "hunter2-secret", "eyJhbGciOiJIUzI1NiJ9"):
        assert sensitive not in record.input_summary
        assert sensitive not in (record.output_summary or "")
        assert sensitive not in (record.error_kind or "")
    assert "[REDACTED]" in record.input_summary
    assert "[REDACTED]" in (record.output_summary or "")
    assert "plain-value" in record.input_summary


async def test_execution_records_are_tenant_scoped(repositories, db):
    service, record_repo, _ = await _build_service(repositories, db)
    tenant_repo, _, _ = repositories
    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant B"))

    await service.execute_tool(
        _context(tenant_a.id), _principal(), "check_service_health", {}, _authorization()
    )
    await service.execute_tool(
        _context(tenant_b.id), _principal(), "check_service_health", {}, _authorization()
    )

    tenant_a_records = await record_repo.list_for_tenant(tenant_a.id)
    tenant_b_records = await record_repo.list_for_tenant(tenant_b.id)
    assert len(tenant_a_records) == 1
    assert len(tenant_b_records) == 1
    assert tenant_a_records[0].tenant_id == tenant_a.id
    assert tenant_b_records[0].tenant_id == tenant_b.id


async def test_validation_error_before_execution_never_records_success(repositories, db):
    service, record_repo, tenant = await _build_service(repositories, db)

    with pytest.raises(ToolValidationError):
        await service.execute_tool(
            _context(tenant.id),
            _principal(),
            "check_service_health",
            {"extra": 1},
            _authorization(),
        )

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED


def test_summary_is_truncated_and_safe():
    long_value = {"data": "x" * 10000}
    summary = _summarize(long_value, max_length=100)
    assert len(summary) <= 100
    assert summary.startswith('{"data": "xxx')


def test_summary_redacts_sensitive_keys():
    value = {"password": "hunter2", "note": {"api_key": "sk-live"}, "keep": "ok"}
    summary = _summarize(value)
    assert "hunter2" not in summary
    assert "sk-live" not in summary
    assert '"keep": "ok"' in summary
    assert "[REDACTED]" in summary


async def test_high_risk_tool_never_executes_with_allow_mode(repositories, db):
    """The service denies a high-risk tool even if its policy somehow
    claims direct execution (defense in depth for the catalog invariant)."""
    tenant_repo, _, _ = repositories
    record_repo = PostgreSQLToolExecutionRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tool Service Tenant"))
    context = _context(tenant.id)

    tool = object.__new__(type(SERVICE_HEALTH_TOOL))
    for key, value in SERVICE_HEALTH_TOOL.__dict__.items():
        object.__setattr__(tool, key, value)
    object.__setattr__(tool, "risk_level", ToolRiskLevel.HIGH)
    object.__setattr__(
        tool, "execution_policy", ToolExecutionPolicy(mode=ToolExecutionPolicyMode.ALLOW)
    )
    service = ToolExecutionService(ToolRegistry({tool.name: tool}), record_repo)

    with pytest.raises(ToolDeniedError):
        await service.execute_tool(context, _principal(), tool.name, {}, _authorization())

    records = await record_repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status == ToolExecutionStatus.FAILED
    assert records[0].error_kind == "invalid_policy_metadata"
