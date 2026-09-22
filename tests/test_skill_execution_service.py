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
        "tool_service": tool_service,
        "registry": registry,
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


# ---------------------------------------------------------------------------
# Per-tool-call approval flow (REQUIRE_HUMAN_APPROVAL inside non-approval Skill)
# ---------------------------------------------------------------------------


class _RecordingApprovalService:
    """In-memory approval service for testing the per-tool-call approval flow."""

    def __init__(self):
        self.approvals = {}
        self.consumed = []

    async def record_required_approval(self, **kwargs):
        from datetime import datetime, timedelta, timezone

        from arc.domain.models import ApprovalRequest, ApprovalStatus

        now = datetime.now(timezone.utc)
        req = ApprovalRequest(
            id=f"appr-{len(self.approvals)}",
            tenant_id=kwargs["tenant_id"],
            requester_user_id=kwargs["requester_user_id"],
            tool_name=kwargs["tool_name"],
            tool_version=kwargs["tool_version"],
            risk_level=kwargs["risk_level"],
            input_summary=kwargs["input_summary"],
            arguments_digest=kwargs["arguments_digest"],
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        self.approvals[req.id] = req
        return req.id

    async def consume_approval(
        self, context, approval_id, tool_name, tool_version, arguments_digest
    ):
        from arc.domain.models import ApprovalStatus
        from arc.services.approvals import (
            ApprovalBindingError,
            ApprovalNotFoundError,
            ApprovalStateError,
        )

        req = self.approvals.get(approval_id)
        if req is None or req.tenant_id != context.tenant_id:
            raise ApprovalNotFoundError(f"Approval {approval_id} not found")
        if req.status != ApprovalStatus.APPROVED:
            raise ApprovalStateError(f"Approval {approval_id} is '{req.status.value}'")
        if (
            req.tool_name != tool_name
            or req.tool_version != tool_version
            or req.arguments_digest != arguments_digest
        ):
            raise ApprovalBindingError(f"Approval {approval_id} binding mismatch")
        self.approvals[approval_id].status = ApprovalStatus.CONSUMED
        self.consumed.append(approval_id)
        return self.approvals[approval_id]

    async def decide_request(self, context, principal_user_id, approval_id, decision):
        from datetime import datetime, timezone

        from arc.services.approvals import ApprovalSelfDecisionError

        req = self.approvals.get(approval_id)
        if req is None:
            raise Exception("not found")
        if req.requester_user_id == principal_user_id:
            raise ApprovalSelfDecisionError("self-approval")
        req.status = decision
        req.decided_by_user_id = principal_user_id
        req.decided_at = datetime.now(timezone.utc)
        return req


async def _build_environment_with_approval(repositories, db):
    """Wire the real service stack with an approval service for gated tools."""
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Skill Execution"))

    calls = []

    def _echo_handler(input_data, tenant_id):
        calls.append(("echo_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "echo": input_data}

    def _gated_handler(input_data, tenant_id):
        calls.append(("gated_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id}

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
            "gated_tool": _tool(
                "gated_tool",
                policy=ToolExecutionPolicy(ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL),
                handler=_gated_handler,
            ),
        }
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    record_repo = PostgreSQLToolExecutionRepository(db)
    approval_service = _RecordingApprovalService()
    tool_service = ToolExecutionService(registry, record_repo, approval_service=approval_service)
    engine = SkillExecutionService(skill_service=skill_service, tool_service=tool_service)

    context = _context(tenant.id)
    return {
        "engine": engine,
        "skill_service": skill_service,
        "record_repo": record_repo,
        "approval_service": approval_service,
        "tenant": tenant,
        "context": context,
        "principal": _principal(),
        "authorization": _authorization(),
        "calls": calls,
    }


async def test_gated_tool_creates_approval_and_returns_id(repositories, db):
    """A gated tool inside a non-approval-required Skill creates an approval
    and returns the approval_id in the result."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "gated_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert result.error_kind == "approval_required"
    assert result.approval_id is not None
    assert result.approval_id.startswith("appr-")
    assert len(result.steps) == 1
    assert result.steps[0].error_kind == "approval_required"
    # Handler must NOT have run.
    assert env["calls"] == []
    # Exactly one pending approval was created.
    assert len(env["approval_service"].approvals) == 1


async def test_resume_from_approval_gate_executes_handler(repositories, db):
    """After approval is granted, passing approval_id resumes execution."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health", "gated_tool"])

    # 1. First execution: creates approval.
    initial = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
    )
    assert initial.status is SkillExecutionStatus.APPROVAL_REQUIRED
    approval_id = initial.approval_id

    # 2. Approve it.
    from arc.domain.models import ApprovalStatus

    await env["approval_service"].decide_request(
        env["context"], "approver-1", approval_id, ApprovalStatus.APPROVED
    )

    # 3. Resume: handler should run.
    resumed = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
        approval_id=approval_id,
        resume_from_step=0,
        previous_steps=[],
    )
    assert resumed.status is SkillExecutionStatus.SUCCEEDED
    assert len(env["calls"]) == 1
    assert env["calls"][0][0] == "gated_tool"
    assert approval_id in env["approval_service"].consumed


async def test_resume_preserves_completed_steps(repositories, db):
    """When resuming, previous_steps are included without re-execution."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(
        env, allowed_tools=["check_service_health", "echo_tool", "gated_tool"]
    )

    from arc.domain.models import SkillExecutionStepOutcome

    # Simulate: echo_tool succeeded, gated_tool needs approval.
    previous_steps = [
        SkillExecutionStepOutcome(
            sequence=0,
            tool_name="echo_tool",
            status=ToolExecutionStatus.SUCCESS,
            tool_version="1",
            output={"tenant_id": env["tenant"].id, "echo": {}},
        )
    ]

    # Create approval for gated_tool at step 1.
    initial = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool"), _call("gated_tool")],
        [],
        env["authorization"],
    )
    # Step 0 (echo_tool) succeeds, step 1 (gated_tool) creates approval.
    assert initial.status is SkillExecutionStatus.APPROVAL_REQUIRED
    approval_id = initial.approval_id

    # Approve.
    from arc.domain.models import ApprovalStatus

    await env["approval_service"].decide_request(
        env["context"], "approver-1", approval_id, ApprovalStatus.APPROVED
    )

    # Resume from step 1 with previous_steps.
    resumed = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool"), _call("gated_tool")],
        [],
        env["authorization"],
        approval_id=approval_id,
        resume_from_step=1,
        previous_steps=previous_steps,
    )
    assert resumed.status is SkillExecutionStatus.SUCCEEDED
    assert len(resumed.steps) == 2
    # Step 0 is from previous_steps (not re-executed).
    assert resumed.steps[0].tool_name == "echo_tool"
    assert resumed.steps[0].status is ToolExecutionStatus.SUCCESS
    # Step 1 was executed.
    assert resumed.steps[1].tool_name == "gated_tool"
    assert resumed.steps[1].status is ToolExecutionStatus.SUCCESS
    # echo_tool handler was called once during the initial run (step 0
    # succeeded before step 1 blocked).  gated_tool was called once during
    # resume (step 1).  No other handlers should have run.
    assert len(env["calls"]) == 2
    assert env["calls"][0][0] == "echo_tool"
    assert env["calls"][1][0] == "gated_tool"


async def test_resume_without_approval_id_raises_value_error(repositories, db):
    """approval_id and resume_from_step must be provided together."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env)

    with pytest.raises(ValueError, match="approval_id and resume_from_step"):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
            approval_id="appr-0",
        )

    with pytest.raises(ValueError, match="approval_id and resume_from_step"):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
            resume_from_step=0,
        )


async def test_resume_from_step_out_of_range_raises_value_error(repositories, db):
    """resume_from_step must be within the tool_calls list."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env)

    with pytest.raises(ValueError, match="resume_from_step out of range"):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
            approval_id="appr-0",
            resume_from_step=5,
        )


async def test_consumed_approval_cannot_be_replayed(repositories, db):
    """Replaying a consumed approval_id fails at the ToolExecutionService level."""
    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env, allowed_tools=["gated_tool"])

    # Create and approve.
    initial = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
    )
    approval_id = initial.approval_id
    from arc.domain.models import ApprovalStatus

    await env["approval_service"].decide_request(
        env["context"], "approver-1", approval_id, ApprovalStatus.APPROVED
    )

    # First resume succeeds.
    await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
        approval_id=approval_id,
        resume_from_step=0,
        previous_steps=[],
    )
    assert len(env["calls"]) == 1

    # Replay fails (approval already consumed).
    replay = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
        approval_id=approval_id,
        resume_from_step=0,
        previous_steps=[],
    )
    assert replay.status is SkillExecutionStatus.FAILED
    assert replay.error_kind == "tool_denied"
    assert len(env["calls"]) == 1  # Handler must not have run again.


async def test_agent_propagates_approval_id(repositories, db):
    """Approval_id is propagated from SkillExecutionResult to AgentExecutionResult."""
    from unittest.mock import MagicMock

    from arc.services.agent import AgentExecutionService
    from arc.services.llm import SkillSelectingLlm

    env = await _build_environment_with_approval(repositories, db)
    skill = await _create_skill(env, allowed_tools=["gated_tool"])

    # Create a mock LLM provider that returns a decision for the gated tool.
    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("gated_tool")],
        "satisfied_preconditions": [],
    }

    agent_service = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )

    result = await agent_service.run(
        env["context"],
        env["principal"],
        "test goal",
        env["authorization"],
    )

    assert result.status.value == "approval_required"
    assert result.approval_id is not None
    assert result.approval_id.startswith("appr-")
    assert len(result.steps) == 1
    assert result.steps[0].status.value == "approval_required"


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


# ---------------------------------------------------------------------------
# Declared skill inputs (Issue #241)
# ---------------------------------------------------------------------------


async def test_missing_declared_inputs_refused(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, inputs=["incident_description"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_skill_inputs"
    assert env["calls"] == []


async def test_unexpected_inputs_refused(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
        skill_inputs={"surprise": "x"},
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_skill_inputs"
    assert env["calls"] == []


async def test_declared_inputs_accepted(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, inputs=["incident_description", "severity_level"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
        skill_inputs={"incident_description": "outage", "severity_level": "high"},
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert [step.tool_name for step in result.steps] == ["check_service_health"]


async def test_malformed_skill_inputs_raise_value_error(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, inputs=["incident_description"])

    with pytest.raises(ValueError, match="skill_inputs must be an object"):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
            skill_inputs=["not-a-dict"],
        )
    assert env["calls"] == []


# ---------------------------------------------------------------------------
# Skill-level approval verification on resume (Issue #206)
# ---------------------------------------------------------------------------


async def _build_verified_environment(repositories, db):
    """Environment with the REAL approval service wired into both layers."""
    from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
    from arc.services.approvals import HumanApprovalService

    env = await _build_environment(repositories, db)
    approval_service = HumanApprovalService(PostgreSQLApprovalRequestRepository(db))
    env["tool_service"].approval_service = approval_service
    env["engine"] = SkillExecutionService(
        skill_service=env["skill_service"],
        tool_service=env["tool_service"],
        approval_service=approval_service,
    )
    env["approval_service"] = approval_service
    return env


async def _mint_approved(env, context, tool_name="gated_tool", **input_fields):
    """Create and approve a real approval bound to the exact tool call."""
    from arc.domain.models import ApprovalStatus
    from arc.services.tools import approval_arguments_digest

    tool = env["registry"].get(tool_name)
    digest = approval_arguments_digest(tool, input_fields)
    approval_id = await env["approval_service"].record_required_approval(
        tenant_id=context.tenant_id,
        requester_user_id="user-1",
        tool_name=tool.name,
        tool_version=tool.version,
        risk_level="low",
        input_summary="test",
        arguments_digest=digest,
    )
    await env["approval_service"].decide_request(
        context, "approver-1", approval_id, ApprovalStatus.APPROVED
    )
    return approval_id


async def _resume(env, skill, approval_id, calls, step=0):
    return await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        calls,
        [],
        env["authorization"],
        approval_id=approval_id,
        resume_from_step=step,
        previous_steps=[],
    )


async def test_fabricated_approval_refused_with_zero_tool_calls(repositories, db):
    """Issue #206: a fabricated approval_id must not bypass the skill gate."""
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    before = await env["approval_service"].list_requests(env["context"])
    result = await _resume(env, skill, "fabricated-approval-does-not-exist", [_call("echo_tool")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []
    # Resume must never mint an approval for an invalid ID.
    after = await env["approval_service"].list_requests(env["context"])
    assert len(after) == len(before)


async def test_pending_approval_refused(repositories, db):
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    from arc.services.tools import approval_arguments_digest

    tool = env["registry"].get("echo_tool")
    approval_id = await env["approval_service"].record_required_approval(
        tenant_id=env["context"].tenant_id,
        requester_user_id="user-1",
        tool_name=tool.name,
        tool_version=tool.version,
        risk_level="low",
        input_summary="test",
        arguments_digest=approval_arguments_digest(tool, {}),
    )

    result = await _resume(env, skill, approval_id, [_call("echo_tool")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []


async def test_rejected_approval_refused(repositories, db):
    from arc.domain.models import ApprovalStatus

    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    from arc.services.tools import approval_arguments_digest

    tool = env["registry"].get("echo_tool")
    approval_id = await env["approval_service"].record_required_approval(
        tenant_id=env["context"].tenant_id,
        requester_user_id="user-1",
        tool_name=tool.name,
        tool_version=tool.version,
        risk_level="low",
        input_summary="test",
        arguments_digest=approval_arguments_digest(tool, {}),
    )
    await env["approval_service"].decide_request(
        env["context"], "approver-1", approval_id, ApprovalStatus.REJECTED
    )

    result = await _resume(env, skill, approval_id, [_call("echo_tool")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []


async def test_expired_approval_refused(repositories, db):
    from datetime import datetime, timedelta, timezone

    from arc.domain.models import ApprovalRequest, ApprovalStatus

    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    from arc.services.tools import approval_arguments_digest

    tool = env["registry"].get("echo_tool")
    now = datetime.now(timezone.utc)
    expired_id = f"appr-exp-{uuid.uuid4().hex[:8]}"
    await env["approval_service"].repository.create(
        ApprovalRequest(
            id=expired_id,
            tenant_id=env["context"].tenant_id,
            requester_user_id="user-1",
            tool_name=tool.name,
            tool_version=tool.version,
            risk_level="low",
            input_summary="test",
            arguments_digest=approval_arguments_digest(tool, {}),
            status=ApprovalStatus.PENDING,
            created_at=now - timedelta(hours=25),
            expires_at=now - timedelta(hours=1),
        )
    )
    try:
        result = await _resume(env, skill, expired_id, [_call("echo_tool")])

        assert result.status is SkillExecutionStatus.FAILED
        assert result.error_kind == "invalid_approval"
        assert env["calls"] == []
    finally:
        # The row must not leak into other tests (e.g. bulk-expiry counts).
        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM approval_requests WHERE id = $1", expired_id)


async def test_consumed_approval_replay_refused(repositories, db):
    """A consumed approval cannot authorize a second resume (ALLOW tool path)."""
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )
    approval_id = await _mint_approved(env, env["context"], "echo_tool")

    first = await _resume(env, skill, approval_id, [_call("echo_tool")])
    assert first.status is SkillExecutionStatus.SUCCEEDED
    assert len(env["calls"]) == 1

    replay = await _resume(env, skill, approval_id, [_call("echo_tool")])
    assert replay.status is SkillExecutionStatus.FAILED
    assert replay.error_kind == "invalid_approval"
    assert len(env["calls"]) == 1


async def test_cross_tenant_approval_refused(repositories, db):
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    tenant_repo, _, _ = repositories
    other = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Other"))
    other_context = _context(other.id)
    approval_id = await _mint_approved(env, other_context, "echo_tool")

    result = await _resume(env, skill, approval_id, [_call("echo_tool")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []


async def test_wrong_tool_approval_refused(repositories, db):
    """An approval for another tool call cannot authorize this resume."""
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env,
        approval_required=True,
        allowed_tools=["check_service_health", "echo_tool", "gated_tool"],
    )
    approval_id = await _mint_approved(env, env["context"], "gated_tool")

    result = await _resume(env, skill, approval_id, [_call("echo_tool")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []


async def test_wrong_step_arguments_refused(repositories, db):
    """An approval for different arguments cannot authorize this step."""
    env = await _build_verified_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )
    approval_id = await _mint_approved(env, env["context"], "echo_tool", marker="other")

    result = await _resume(env, skill, approval_id, [_call("echo_tool", marker="mine")])

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []


async def test_valid_approval_succeeds_and_consumes(repositories, db):
    """End-to-end: tool-created approval authorizes the gated skill resume."""
    from arc.domain.models import ApprovalStatus

    env = await _build_verified_environment(repositories, db)
    plain_skill = await _create_skill(env, allowed_tools=["gated_tool"])
    gated_skill = await _create_skill(env, approval_required=True, allowed_tools=["gated_tool"])

    initial = await env["engine"].execute(
        env["context"],
        env["principal"],
        plain_skill.id,
        [_call("gated_tool")],
        [],
        env["authorization"],
    )
    assert initial.status is SkillExecutionStatus.APPROVAL_REQUIRED
    await env["approval_service"].decide_request(
        env["context"], "approver-1", initial.approval_id, ApprovalStatus.APPROVED
    )

    resumed = await _resume(env, gated_skill, initial.approval_id, [_call("gated_tool")])
    assert resumed.status is SkillExecutionStatus.SUCCEEDED
    assert len(env["calls"]) == 1

    # The tool layer consumed it: replay is refused with zero new calls.
    replay = await _resume(env, gated_skill, initial.approval_id, [_call("gated_tool")])
    assert replay.status is SkillExecutionStatus.FAILED
    assert replay.error_kind == "invalid_approval"
    assert len(env["calls"]) == 1


async def test_resume_without_verification_service_fails_closed(repositories, db):
    """An unwired approval service cannot silently skip resume verification."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(
        env, approval_required=True, allowed_tools=["check_service_health", "echo_tool"]
    )

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool")],
        [],
        env["authorization"],
        approval_id="any-approval-id",
        resume_from_step=0,
        previous_steps=[],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "invalid_approval"
    assert env["calls"] == []
