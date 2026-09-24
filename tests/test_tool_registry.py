"""AI Tools platform-owned registry tests.

The registry is a static, code-defined, platform-approved whitelist
(PRD 15, TRD 14, ADR-001). These tests prove:

- the approved catalog and its PRD 15 metadata are complete;
- ``check_service_health`` is the one approved foundation tool;
- the registry exposes no runtime registration or mutation API;
- definitions fail closed on missing/invalid permission metadata and
  on high-risk tools that would bypass the approval policy;
- the tool layer contains no arbitrary/dynamic execution mechanism.
"""

import inspect
import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from arc.domain.models import ToolRiskLevel
from arc.security.authorization import CONNECTOR_ACT, TOOL_EXECUTE
from arc.security.models import Permission
from arc.services.tools import (
    PLATFORM_TOOLS,
    SERVICE_HEALTH_TOOL,
    ToolAuditPolicy,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolExecutionPolicyMode,
    ToolRegistry,
    build_platform_tool_registry,
)


class _EmptyInput(BaseModel):
    """Minimal schema for definitions that must fail construction."""

    model_config = ConfigDict(extra="forbid")


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-registry-{prefix}-{uuid.uuid4().hex[:10]}"


def test_platform_catalog_contains_check_service_health():
    assert SERVICE_HEALTH_TOOL.name == "check_service_health"
    assert any(tool.name == "check_service_health" for tool in PLATFORM_TOOLS)


def test_platform_catalog_has_expected_approved_tools():
    assert len(PLATFORM_TOOLS) == 3
    assert {tool.name for tool in PLATFORM_TOOLS} == {
        "check_service_health",
        "grant_temporary_access",
        "post_channel_message",
    }


def test_platform_registry_names():
    registry = build_platform_tool_registry()
    assert registry.names() == frozenset(
        {"check_service_health", "grant_temporary_access", "post_channel_message"}
    )


def test_definition_metadata_complete():
    """PRD 15: every approved tool declares purpose, schemas, permissions,
    risk level, execution policy, audit policy, and a handler."""
    for tool in PLATFORM_TOOLS:
        assert tool.name
        assert tool.version
        assert tool.description
        assert tool.input_schema.get("type") == "object"
        assert tool.output_schema.get("type") == "object"
        assert tool.required_permissions
        assert all(isinstance(p, Permission) for p in tool.required_permissions)
        assert tool.risk_level in ToolRiskLevel
        assert tool.execution_policy.mode in ToolExecutionPolicyMode
        assert tool.audit_policy.record_summary_only is True
        # Exactly one handler, and the right kind for the tool (ADR-013).
        assert callable(tool.handler) ^ callable(tool.action_handler)


def test_every_external_action_tool_is_gated_by_human_approval():
    """ADR-013: anything that leaves the tenant boundary needs a human.

    Asserted over the whole catalog rather than over one tool, so a tool
    added later cannot arrive ungated.
    """
    actions = [tool for tool in PLATFORM_TOOLS if tool.is_external_action]
    assert actions, "the catalog should contain at least one external action"
    for tool in actions:
        assert tool.risk_level == ToolRiskLevel.HIGH
        assert tool.execution_policy.mode == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL
        assert CONNECTOR_ACT in tool.required_permissions


def test_an_external_action_tool_cannot_be_declared_low_risk():
    """The rule above is enforced at construction, not only asserted."""

    async def _handler(input_data, invocation):  # pragma: no cover - never called
        return {}

    with pytest.raises(ValueError, match="external action"):
        ToolDefinition(
            name=_unique("low-risk-action"),
            version="1",
            description="Should not be constructible",
            input_model=_EmptyInput,
            output_model=_EmptyInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(),
            action_handler=_handler,
        )


def test_a_tool_must_declare_exactly_one_handler():
    async def _action(input_data, invocation):  # pragma: no cover - never called
        return {}

    def _sync(input_data, tenant_id):  # pragma: no cover - never called
        return {}

    with pytest.raises(ValueError, match="exactly one"):
        ToolDefinition(
            name=_unique("no-handler"),
            version="1",
            description="No handler at all",
            input_model=_EmptyInput,
            output_model=_EmptyInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(),
        )

    with pytest.raises(ValueError, match="exactly one"):
        ToolDefinition(
            name=_unique("two-handlers"),
            version="1",
            description="Both handlers",
            input_model=_EmptyInput,
            output_model=_EmptyInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.HIGH,
            execution_policy=ToolExecutionPolicy(mode=ToolExecutionPolicyMode.DENY),
            audit_policy=ToolAuditPolicy(),
            handler=_sync,
            action_handler=_action,
        )


def test_check_service_health_requires_tool_execute_permission():
    assert SERVICE_HEALTH_TOOL.required_permissions == frozenset({TOOL_EXECUTE})


def test_check_service_health_is_low_risk():
    assert SERVICE_HEALTH_TOOL.risk_level == ToolRiskLevel.LOW


def test_grant_temporary_access_is_high_risk_requiring_approval():
    from arc.services.tools import GRANT_TEMPORARY_ACCESS_TOOL

    assert GRANT_TEMPORARY_ACCESS_TOOL.risk_level == ToolRiskLevel.HIGH
    assert (
        GRANT_TEMPORARY_ACCESS_TOOL.execution_policy.mode
        == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL
    )


def test_check_service_health_input_schema_forbids_extra_fields():
    schema = SERVICE_HEALTH_TOOL.input_schema
    assert schema["additionalProperties"] is False
    assert schema["properties"] == {}


def test_unknown_tool_is_not_resolved():
    registry = build_platform_tool_registry()
    assert registry.get("restart_service") is None
    assert registry.get("__import__") is None
    assert registry.get("eval") is None


def test_registry_has_no_runtime_registration_or_mutation_api():
    """The whitelist is closed by construction: only read operations exist."""
    registry = build_platform_tool_registry()
    for mutation_name in ("register", "add", "unregister", "update", "clear", "set"):
        assert not hasattr(registry, mutation_name)


def test_registry_exposes_only_read_operations():
    registry = build_platform_tool_registry()
    assert callable(registry.get)
    assert callable(registry.list)
    assert callable(registry.names)
    assert {tool.name for tool in registry.list()} == {
        "check_service_health",
        "grant_temporary_access",
        "post_channel_message",
    }


def test_empty_registry_approves_nothing():
    registry = ToolRegistry({})
    assert registry.names() == frozenset()
    assert registry.get("check_service_health") is None


def test_definition_without_required_permissions_fails_closed():
    """Missing permission metadata must never construct (fail closed)."""
    with pytest.raises(ValueError):
        ToolDefinition(
            name="no_permissions",
            version="1",
            description="should be rejected",
            input_model=SERVICE_HEALTH_TOOL.input_model,
            output_model=SERVICE_HEALTH_TOOL.output_model,
            required_permissions=frozenset(),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=SERVICE_HEALTH_TOOL.audit_policy,
            handler=SERVICE_HEALTH_TOOL.handler,
        )


def test_definition_with_invalid_permission_metadata_fails_closed():
    """Invalid permission metadata (non-Permission entries) must never
    construct (fail closed)."""
    with pytest.raises(ValueError):
        ToolDefinition(
            name="bad_permission",
            version="1",
            description="should be rejected",
            input_model=SERVICE_HEALTH_TOOL.input_model,
            output_model=SERVICE_HEALTH_TOOL.output_model,
            required_permissions=frozenset({"tool:execute"}),  # not a Permission
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=SERVICE_HEALTH_TOOL.audit_policy,
            handler=SERVICE_HEALTH_TOOL.handler,
        )


def test_high_risk_tool_with_allow_policy_is_rejected():
    """A high-risk tool must never silently bypass the approval policy."""
    with pytest.raises(ValueError):
        ToolDefinition(
            name="restart_service",
            version="1",
            description="high-risk tool that must require human approval",
            input_model=SERVICE_HEALTH_TOOL.input_model,
            output_model=SERVICE_HEALTH_TOOL.output_model,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.HIGH,
            execution_policy=ToolExecutionPolicy(mode=ToolExecutionPolicyMode.ALLOW),
            audit_policy=SERVICE_HEALTH_TOOL.audit_policy,
            handler=SERVICE_HEALTH_TOOL.handler,
        )


def test_high_risk_tool_may_reserve_human_approval():
    """HIGH risk with REQUIRE_HUMAN_APPROVAL (or DENY) is representable
    as an explicit future/fail-closed state; the approval gate itself is
    not implemented in this slice."""
    tool = ToolDefinition(
        name="restart_service",
        version="1",
        description="high-risk tool reserving the approval gate",
        input_model=SERVICE_HEALTH_TOOL.input_model,
        output_model=SERVICE_HEALTH_TOOL.output_model,
        required_permissions=frozenset({TOOL_EXECUTE}),
        risk_level=ToolRiskLevel.HIGH,
        execution_policy=ToolExecutionPolicy(mode=ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL),
        audit_policy=SERVICE_HEALTH_TOOL.audit_policy,
        handler=SERVICE_HEALTH_TOOL.handler,
    )
    assert tool.execution_policy.mode == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL


def test_handlers_are_plain_platform_owned_functions():
    """Approved handlers are module-level functions owned by the platform,
    never closures over user input or dynamically generated code."""
    for tool in PLATFORM_TOOLS:
        handler = tool.handler or tool.action_handler
        assert inspect.isfunction(handler)
        assert handler.__module__ == "arc.services.tools"


def test_tool_layer_has_no_arbitrary_execution_mechanism():
    """Security guard: the tool layer must not contain any path for
    arbitrary Python, operating-system, database, or network execution."""
    from arc.services import tools as tools_module

    source = inspect.getsource(tools_module)
    forbidden = [
        "eval(",
        "exec(",
        "subprocess",
        "os.system",
        "importlib.",
        "__import__",
    ]
    for token in forbidden:
        assert token not in source, f"forbidden dynamic-execution token found: {token}"


def test_handlers_cannot_reach_external_systems():
    """Security guard: no handler opens a channel of its own.

    ADR-013 gave one tool the ability to affect the outside world, and
    this guard is what keeps that from becoming "handlers may do network
    I/O". The rule is unchanged for every handler -- no client, no socket,
    no file, no database, and no import to fetch one -- and an action
    handler reaches outward ONLY through the ``external_actions`` boundary
    it is handed, which applies the capability ceiling, the destination
    check and the act-credential scope.
    """
    for tool in PLATFORM_TOOLS:
        handler = tool.handler or tool.action_handler
        source = inspect.getsource(handler)
        for token in ("import ", "requests", "httpx", "asyncpg", "open(", "socket"):
            assert token not in source, f"forbidden channel token found in handler: {token}"


def test_action_handlers_reach_outward_only_through_the_boundary():
    """An action handler's only route outside is the injected service."""
    actions = [tool for tool in PLATFORM_TOOLS if tool.is_external_action]
    assert actions
    for tool in actions:
        source = inspect.getsource(tool.action_handler)
        assert "invocation.external_actions" in source
