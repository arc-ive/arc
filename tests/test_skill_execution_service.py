"""Skill execution engine tests (real PostgreSQL, real ToolExecutionService).

The engine is security-sensitive: these tests prove that every proposed
tool call is gated by ``Skill.allowed_tools`` FIRST and then executed
EXCLUSIVELY through ``ToolExecutionService`` (platform whitelist,
centralized RBAC, per-tool permissions, execution/approval policy, input
schemas, tenant-scoped audit records). The engine holds no registry and
no handlers; failures stop the workflow; the tenant boundary always comes
from the trusted X-10 ``TenantContext``.
"""

import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from arc.db.connection import NotFoundError
from arc.domain.models import (
    Skill,
    SkillExecutionStatus,
    SkillStatus,
    Tenant,
    TenantContext,
    ToolExecutionStatus,
    UserRole,
)
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import TOOL_EXECUTE, AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal, Permission
from arc.services.skill_execution import MAX_TOOL_CALLS, SkillExecutionService
from arc.services.skills import SkillService
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolAuditPolicy,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolExecutionPolicyMode,
    ToolExecutionService,
    ToolRegistry,
    ToolRiskLevel,
)

RESTART_PERMISSION = Permission(resource="tool", action="restart")


class EchoInput(BaseModel):
    """Permissive input model for the deterministic echo test tool."""

    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"skill-exec-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Skill Execution Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id: str = "user-1") -> AuthorizationService:
    return AuthorizationService({user_id: ApplicationRole.OPERATIONS_USER})


async def _build_environment(repositories, db):
    """Wire the real service stack plus controlled test tools.

    Returns everything a test needs: the engine under test, the tool
    audit repository (to prove delegation produces real records), a fresh
    tenant with its trusted context, and the shared handler-call log.
    """
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Skill Execution"))

    calls: list = []

    def _echo_handler(input_data, tenant_id):
        calls.append(("echo_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "echo": input_data}

    def _restricted_handler(input_data, tenant_id):
        calls.append(("restricted_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "ok": True}

    def _denied_handler(input_data, tenant_id):
        calls.append(("denied_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id}

    def _gated_handler(input_data, tenant_id):
        calls.append(("gated_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id}

    def _failing_handler(input_data, tenant_id):
        calls.append(("failing_tool", dict(input_data), tenant_id))
        raise RuntimeError("simulated handler crash")

    def _tool(name, *, permissions=None, policy=None, handler=None):
        return ToolDefinition(
            name=name,
            version="1",
            description=f"Deterministic {name} test tool",
            input_model=EchoInput,
            output_model=EchoInput,
            required_permissions=frozenset(permissions or {TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=policy or ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(record_summary_only=True),
            handler=handler or (lambda input_data, tenant_id: {"tenant_id": tenant_id}),
        )

    registry = ToolRegistry(
        {
            "check_service_health": SERVICE_HEALTH_TOOL,
            "echo_tool": _tool("echo_tool", handler=_echo_handler),
            "restricted_tool": _tool(
                "restricted_tool",
                permissions={TOOL_EXECUTE, RESTART_PERMISSION},
                handler=_restricted_handler,
            ),
            "denied_tool": _tool(
                "denied_tool", policy=ToolExecutionPolicy(ToolExecutionPolicyMode.DENY)
            ),
            "gated_tool": _tool(
                "gated_tool",
                policy=ToolExecutionPolicy(ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL),
                handler=_gated_handler,
            ),
            "failing_tool": _tool("failing_tool", handler=_failing_handler),
        }
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    record_repo = PostgreSQLToolExecutionRepository(db)
    tool_service = ToolExecutionService(registry, record_repo)
    engine = SkillExecutionService(skill_service=skill_service, tool_service=tool_service)

    context = _context(tenant.id)
    return {
        "engine": engine,
        "skill_service": skill_service,
        "record_repo": record_repo,
        "tenant": tenant,
        "context": context,
        "principal": _principal(),
        "authorization": _authorization(),
        "calls": calls,
    }


async def _create_skill(env, **overrides) -> Skill:
    """Create a persisted Skill owned by the environment's tenant."""
    values = {
        "id": "unassigned",
        "tenant_id": "placeholder",
        "name": _unique("skill"),
        "purpose": "Recover a degraded service",
        "allowed_tools": ["check_service_health", "echo_tool"],
    }
    values.update(overrides)
    return await env["skill_service"].create_skill(env["context"], Skill(**values))


def _call(tool_name, **input_fields):
    """Build one proposed tool call."""
    return {"tool_name": tool_name, "input": input_fields}


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


async def test_successful_execution_returns_structured_result(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert result.error_kind is None
    assert result.tenant_id == env["tenant"].id
    assert result.principal_id == "user-1"
    assert result.skill_id == skill.id
    assert [step.tool_name for step in result.steps] == ["check_service_health"]
    assert result.steps[0].status is ToolExecutionStatus.SUCCESS
    assert result.steps[0].tool_version == "1"
    assert result.steps[0].output["tenant_id"] == env["tenant"].id


async def test_successful_execution_produces_real_tool_audit_record(repositories, db):
    """Prove delegation: the audit row comes from ToolExecutionService."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", marker="m1")],
        [],
        env["authorization"],
    )

    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].tool_name == "echo_tool"
    assert records[0].user_id == "user-1"
    assert records[0].status is ToolExecutionStatus.SUCCESS


async def test_multi_step_execution_runs_in_declared_order(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", marker="first"), _call("echo_tool", marker="second")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert [step.output["echo"]["marker"] for step in result.steps] == ["first", "second"]
    assert [step.sequence for step in result.steps] == [0, 1]
    assert [(name, payload["marker"]) for name, payload, _ in env["calls"]] == [
        ("echo_tool", "first"),
        ("echo_tool", "second"),
    ]


# ---------------------------------------------------------------------------
# Resolution and executability gates
# ---------------------------------------------------------------------------


async def test_unknown_skill_raises_not_found(repositories, db):
    env = await _build_environment(repositories, db)

    with pytest.raises(NotFoundError):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            "missing-skill-id",
            [_call("check_service_health")],
            [],
            env["authorization"],
        )


async def test_cross_tenant_skill_is_indistinguishable_from_missing(repositories, db):
    env = await _build_environment(repositories, db)
    tenant_repo, _, _ = repositories
    other_tenant = await tenant_repo.create(Tenant(id=_unique("other-tenant"), name="Other"))
    other_context = _context(other_tenant.id, user_id="user-2")
    foreign = await env["skill_service"].create_skill(
        other_context,
        Skill(id="unassigned", tenant_id="placeholder", name=_unique("skill"), purpose="p"),
    )

    with pytest.raises(NotFoundError):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            foreign.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
        )
    assert env["calls"] == []


async def test_inactive_skill_fails_closed_without_execution(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, status=SkillStatus.INACTIVE)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "inactive_skill"
    assert result.steps == []
    assert env["calls"] == []
    assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


# ---------------------------------------------------------------------------
# Preconditions (deterministic label containment)
# ---------------------------------------------------------------------------


async def test_unmet_precondition_blocks_before_any_tool_call(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, preconditions=["service_health_degraded"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.PRECONDITION_FAILED
    assert result.error_kind == "precondition_failed"
    assert result.steps == []
    assert env["calls"] == []
    assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


async def test_satisfied_preconditions_allow_execution(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, preconditions=["service_health_degraded"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        ["service_health_degraded", "extra_unrelated_condition"],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Approval requirements (fail closed, structured escalation state)
# ---------------------------------------------------------------------------


async def test_approval_required_skill_never_executes_anything(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, approval_required=True)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert result.error_kind == "approval_required"
    assert result.steps == []
    assert env["calls"] == []
    assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


async def test_human_approval_policy_tool_fails_closed_inside_skill(repositories, db):
    """A gated tool inside an approval-free Skill still fails closed."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "gated_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "tool_denied"
    assert result.steps[-1].error_kind == "tool_denied"
    assert "gated_tool" not in [name for name, _, _ in env["calls"]]


# ---------------------------------------------------------------------------
# Tool boundary enforcement (allowed_tools AND RBAC AND policy)
# ---------------------------------------------------------------------------


async def test_disallowed_registered_tool_denied_before_tool_service(repositories, db):
    """allowed_tools is enforced BEFORE the platform registry is consulted."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health"), _call("echo_tool", marker="never")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.DENIED
    assert result.error_kind == "disallowed_tool"
    assert len(result.steps) == 2
    assert result.steps[0].status is ToolExecutionStatus.SUCCESS
    assert result.steps[1].error_kind == "disallowed_tool"
    # The disallowed proposal never reached any handler...
    assert env["calls"] == []
    # ...and exactly one delegated (audited) attempt was made.
    assert len(await env["record_repo"].list_for_tenant(env["tenant"].id)) == 1


async def test_arbitrary_proposal_names_are_denied(repositories, db):
    """Untrusted proposals can only ever select declared tools."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    for malicious in ("eval", "exec", "__import__", "os.system", "../../etc/passwd"):
        result = await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call(malicious)],
            [],
            env["authorization"],
        )
        assert result.status is SkillExecutionStatus.DENIED
        assert result.steps[-1].error_kind == "disallowed_tool"
    assert env["calls"] == []


async def test_empty_allowed_tools_allows_nothing(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=[])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.DENIED
    assert result.steps[-1].error_kind == "disallowed_tool"


async def test_tool_permission_requirement_still_applies_inside_skill(repositories, db):
    """allowed_tools NEVER replaces centralized per-tool RBAC."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "restricted_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("restricted_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "tool_denied"
    assert env["calls"] == []  # the restricted handler never ran

    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].authorization_outcome.value == "denied"


async def test_deny_policy_tool_is_refused_inside_skill(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "denied_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("denied_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "tool_denied"
    assert "denied_tool" not in [name for name, _, _ in env["calls"]]


async def test_unknown_but_declared_tool_stops_workflow(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "ghost_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("ghost_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.steps[-1].error_kind == "unknown_tool"
    # The unknown-tool refusal produced a controlled audit record.
    assert len(await env["record_repo"].list_for_tenant(env["tenant"].id)) == 1


async def test_invalid_tool_input_stops_workflow(repositories, db):
    """check_service_health accepts no parameters; extra input fails."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health", unexpected="value")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.steps[-1].error_kind == "invalid_input"
    assert env["calls"] == []


async def test_handler_failure_stops_workflow(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(
        env,
        allowed_tools=[
            "check_service_health",
            "failing_tool",
            "echo_tool",
        ],
    )

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [
            _call("check_service_health"),
            _call("failing_tool"),
            _call("echo_tool", marker="must-never-run"),
        ],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "execution_error"
    assert [step.status for step in result.steps] == [
        ToolExecutionStatus.SUCCESS,
        ToolExecutionStatus.FAILED,
    ]
    assert result.steps[-1].error_kind == "execution_error"
    assert "echo_tool" not in [name for name, _, _ in env["calls"]]


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_trusted_tenant_context_cannot_be_overridden(repositories, db):
    """Payload tenant hints never override the trusted context tenant."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", tenant_id="tenant-B")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    step_output = result.steps[0].output
    assert step_output["tenant_id"] == env["tenant"].id
    assert step_output["echo"]["tenant_id"] == "tenant-B"  # inert request data


async def test_invalid_tenant_context_fails_closed(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    with pytest.raises(ValueError, match="Invalid tenant context"):
        await env["engine"].execute(
            None,
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
        )


# ---------------------------------------------------------------------------
# Malformed proposals fail closed (ValueError), before any execution
# ---------------------------------------------------------------------------


async def test_malformed_proposals_raise_value_error(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)
    engine = env["engine"]

    malformed_calls = [
        ([], "proposed tool call is required"),
        ("not-a-list", "proposed tool call is required"),
        ([_call("check_service_health")] * (MAX_TOOL_CALLS + 1), "at most"),
        (["not-an-object"], "must be an object"),
        ([{"input": {}}], "tool_name"),
        ([{"tool_name": ""}], "tool_name"),
        ([{"tool_name": "echo_tool", "input": "not-an-object"}], "input"),
    ]
    for tool_calls, fragment in malformed_calls:
        with pytest.raises(ValueError, match=fragment):
            await engine.execute(
                env["context"],
                env["principal"],
                skill.id,
                tool_calls,
                [],
                env["authorization"],
            )
    assert env["calls"] == []


async def test_non_string_precondition_labels_rejected(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    with pytest.raises(ValueError, match="list of strings"):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            ["ok", 42],
            env["authorization"],
        )
    assert env["calls"] == []
