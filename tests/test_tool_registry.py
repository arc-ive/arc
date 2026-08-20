"""AI Tools platform-owned registry tests.

The registry is a static, code-defined, platform-approved whitelist
(PRD 15, TRD 14, ADR-001). These tests prove:

- the approved catalog and its PRD 15 metadata are complete;
- ``check_service_health`` is the one approved foundation tool;
- the registry exposes no runtime registration or mutation API;
- the tool layer contains no arbitrary/dynamic execution mechanism.
"""

import inspect
import uuid

from arc.domain.models import ToolRiskLevel
from arc.security.authorization import TOOL_EXECUTE
from arc.services.tools import (
    PLATFORM_TOOLS,
    SERVICE_HEALTH_TOOL,
    ToolRegistry,
    build_platform_tool_registry,
)


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-registry-{prefix}-{uuid.uuid4().hex[:10]}"


def test_platform_catalog_contains_check_service_health():
    assert SERVICE_HEALTH_TOOL.name == "check_service_health"
    assert any(tool.name == "check_service_health" for tool in PLATFORM_TOOLS)


def test_platform_catalog_has_exactly_one_approved_tool():
    assert len(PLATFORM_TOOLS) == 1
    assert PLATFORM_TOOLS[0].name == "check_service_health"


def test_platform_registry_names():
    registry = build_platform_tool_registry()
    assert registry.names() == frozenset({"check_service_health"})


def test_definition_metadata_complete():
    """PRD 15: every approved tool declares purpose, schemas, permission,
    risk level, execution policy, audit policy, and a handler."""
    for tool in PLATFORM_TOOLS:
        assert tool.name
        assert tool.version
        assert tool.description
        assert tool.input_schema.get("type") == "object"
        assert tool.output_schema.get("type") == "object"
        assert isinstance(tool.required_permission.value, str)
        assert tool.risk_level in ToolRiskLevel
        assert tool.execution_policy.direct_execution_allowed is not None
        assert tool.audit_policy.record_summary_only is True
        assert callable(tool.handler)


def test_check_service_health_requires_tool_execute_permission():
    assert SERVICE_HEALTH_TOOL.required_permission == TOOL_EXECUTE


def test_check_service_health_is_low_risk():
    assert SERVICE_HEALTH_TOOL.risk_level == ToolRiskLevel.LOW


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
    assert {tool.name for tool in registry.list()} == {"check_service_health"}


def test_empty_registry_approves_nothing():
    registry = ToolRegistry({})
    assert registry.names() == frozenset()
    assert registry.get("check_service_health") is None


def test_handlers_are_plain_platform_owned_functions():
    """Approved handlers are module-level functions owned by the platform,
    never closures over user input or dynamically generated code."""
    for tool in PLATFORM_TOOLS:
        assert inspect.isfunction(tool.handler)
        assert tool.handler.__module__ == "arc.services.tools"


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
