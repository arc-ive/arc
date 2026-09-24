"""Unified Skill execution: Manual (Play) and Agent-invoked paths must converge.

Issue #322: Both User → Play → SkillExecutionService and
User → Agent → SkillExecutionService must use the SAME governed path:
SkillExecutionService → ToolExecutionService with identical authorization,
tenant isolation, approval, secrets handling and audit.

These tests prove the convergence explicitly. They exercise the same
Skill and the same tool through both entry points and assert identical
governance. They are not duplicates of the separate manual/agent suites;
they are the product-level acceptance criteria for unification.

Security invariants remain with ToolExecutionService: preconditions are
caller-asserted (SKILLS.md §9) and never widen tool capability.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ConfigDict

from arc.api.controllers import app_context
from arc.db.connection import NotFoundError
from arc.domain.models import (
    Membership,
    Skill,
    SkillExecutionStatus,
    SkillStatus,
    Tenant,
    TenantContext,
    ToolExecutionStatus,
    User,
    UserRole,
)
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.skill_execution import PostgreSQLSkillExecutionRecordRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import TOOL_EXECUTE, AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal, Permission
from arc.services.agent import AgentExecutionService
from arc.services.approvals import HumanApprovalService
from arc.services.llm import SkillSelectingLlm
from arc.services.skill_execution import SkillExecutionService
from arc.services.skills import SkillService
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolAuditPolicy,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolExecutionService,
    ToolRegistry,
    ToolRiskLevel,
    build_platform_tool_registry,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    return f"unified-{prefix}-{uuid.uuid4().hex[:8]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id, tenant_name="Unified Tenant", user_id=user_id, role=UserRole.MEMBER
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id: str = "user-1") -> AuthorizationService:
    return AuthorizationService({user_id: ApplicationRole.OPERATIONS_USER})


async def _build_env(repositories, db):
    """Build a governed stack with the real grant_temporary_access gate wired.

    Uses the real platform ``grant_temporary_access`` tool from
    ``build_platform_tool_registry()`` wrapped only to observe whether the
    handler was invoked. The real ``HumanApprovalService`` is wired so the
    ``REQUIRE_HUMAN_APPROVAL`` policy creates a pending approval with a
    non-null ``approval_id`` instead of failing with ``approval_id=None``.
    """
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Unified"))

    calls: list = []

    def _echo(input_data, tenant_id):
        calls.append(("echo_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "echo": input_data}

    real_grant = build_platform_tool_registry().get("grant_temporary_access")
    assert real_grant is not None

    def _tracked_grant(input_data, tenant_id):
        calls.append(("grant_temporary_access", dict(input_data), tenant_id))
        return real_grant.handler(input_data, tenant_id)

    tracked_grant = ToolDefinition(
        name=real_grant.name,
        version=real_grant.version,
        description=real_grant.description,
        input_model=real_grant.input_model,
        output_model=real_grant.output_model,
        required_permissions=real_grant.required_permissions,
        risk_level=real_grant.risk_level,
        execution_policy=real_grant.execution_policy,
        audit_policy=real_grant.audit_policy,
        handler=_tracked_grant,
    )

    def _tool(name, handler):
        return ToolDefinition(
            name=name,
            version="1",
            description=f"Deterministic {name}",
            input_model=EchoInput,
            output_model=EchoInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(record_summary_only=True),
            handler=handler,
        )

    registry = ToolRegistry(
        {
            "check_service_health": SERVICE_HEALTH_TOOL,
            "echo_tool": _tool("echo_tool", handler=_echo),
            "grant_temporary_access": tracked_grant,
        }
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    record_repo = PostgreSQLToolExecutionRepository(db)
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    approval_service = HumanApprovalService(PostgreSQLApprovalRequestRepository(db))
    tool_service = ToolExecutionService(registry, record_repo, approval_service=approval_service)
    engine = SkillExecutionService(
        skill_service=skill_service,
        tool_service=tool_service,
        record_repo=skill_record_repo,
        approval_service=approval_service,
    )

    return {
        "tenant": tenant,
        "context": _context(tenant.id),
        "principal": _principal(),
        "authorization": _authorization(),
        "skill_service": skill_service,
        "engine": engine,
        "record_repo": record_repo,
        "skill_record_repo": skill_record_repo,
        "calls": calls,
    }


async def _create_skill(env, **overrides) -> Skill:
    values = {
        "id": "unassigned",
        "tenant_id": "placeholder",
        "name": _unique("skill"),
        "purpose": "Test skill",
        "allowed_tools": ["echo_tool", "check_service_health"],
    }
    values.update(overrides)
    return await env["skill_service"].create_skill(env["context"], Skill(**values))


def _call(tool_name, **fields):
    return {"tool_name": tool_name, "input": fields}


# ---------------------------------------------------------------------------
# Manual vs Agent convergence (service-level)
# ---------------------------------------------------------------------------


async def test_manual_skill_execution_goes_through_governed_path(repositories, db):
    """Manual Play → SkillExecutionService → ToolExecutionService."""
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["echo_tool"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", x="1")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert len(result.steps) == 1
    assert result.steps[0].status is ToolExecutionStatus.SUCCESS
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert any(r.tool_name == "echo_tool" for r in records)
    assert ("echo_tool", {"x": "1"}, env["tenant"].id) in [
        (n, p, tid) for n, p, tid in env["calls"]
    ]


async def test_agent_invoked_skill_uses_same_governed_path(repositories, db):
    """Agent → Skill → same SkillExecutionService → same ToolExecutionService."""
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["echo_tool"])

    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.side_effect = [
        {
            "skill_id": skill.id,
            "tool_calls": [_call("echo_tool", x="1")],
            "satisfied_preconditions": [],
        },
        None,
    ]

    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    result = await agent.run(env["context"], env["principal"], "do echo", env["authorization"])

    assert result.status.value == "succeeded"
    assert len(result.steps) == 1
    assert result.steps[0].status is SkillExecutionStatus.SUCCEEDED
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert any(r.tool_name == "echo_tool" for r in records)


async def test_both_paths_reject_disallowed_tool_governance_equivalent(repositories, db):
    """Disallowed tool is denied on both paths; Agent wraps DENIED as FAILED."""

    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["echo_tool"])

    # Manual denied — allowed_tools gate fires before ToolExecutionService
    r1 = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )
    assert r1.status is SkillExecutionStatus.DENIED
    assert r1.error_kind == "disallowed_tool"
    assert len(r1.steps) == 1
    assert r1.steps[0].error_kind == "disallowed_tool"
    assert r1.steps[0].status is ToolExecutionStatus.FAILED
    assert env["calls"] == []

    # Agent denied (same skill, same disallowed tool via LLM decision)
    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("check_service_health")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    r2 = await agent.run(env["context"], env["principal"], "try disallowed", env["authorization"])
    assert r2.status.value == "failed"
    assert r2.error_kind == "disallowed_tool"
    assert len(r2.steps) == 1
    assert r2.steps[0].status is SkillExecutionStatus.DENIED
    assert r2.steps[0].error_kind == "disallowed_tool"
    # No handler invoked on either path
    assert env["calls"] == []


async def test_tenant_isolation_manual_and_agent(repositories, db):
    env = await _build_env(repositories, db)
    tenant_repo, _, _ = repositories
    other_tenant = await tenant_repo.create(Tenant(id=_unique("other"), name="Other"))
    other_ctx = _context(other_tenant.id, user_id="user-2")
    foreign = await env["skill_service"].create_skill(
        other_ctx,
        Skill(id="unassigned", tenant_id="placeholder", name=_unique("skill"), purpose="p"),
    )

    with pytest.raises(NotFoundError):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            foreign.id,
            [_call("echo_tool")],
            [],
            env["authorization"],
        )

    # Agent cross-tenant also fails
    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": foreign.id,
        "tool_calls": [_call("echo_tool")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    result = await agent.run(env["context"], env["principal"], "cross tenant", env["authorization"])
    assert result.status.value == "failed"
    assert result.error_kind == "skill_not_available"
    assert result.steps == []
    assert env["calls"] == []


async def test_approval_required_tool_level_blocks_both_paths(repositories, db):
    """Tool-level REQUIRE_HUMAN_APPROVAL blocks both manual and Agent.

    Uses the real ``grant_temporary_access`` tool (HIGH, REQUIRE_HUMAN_APPROVAL)
    from ``build_platform_tool_registry()`` and the real
    ``HumanApprovalService``. Skill-level ``approval_required`` is False so
    the Skill gate passes and the Tool gate is the one exercised. Both paths
    must return APPROVAL_REQUIRED with a non-null approval_id and must NOT
    invoke the handler.
    """
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["grant_temporary_access"])

    # Manual path — hits tool policy before handler
    manual = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("grant_temporary_access", justification="need elevated access")],
        [],
        env["authorization"],
    )
    assert manual.status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert manual.error_kind == "approval_required"
    assert manual.approval_id is not None
    assert isinstance(manual.approval_id, str) and manual.approval_id
    # Handler was not invoked
    assert not any(name == "grant_temporary_access" for name, _, _ in env["calls"])
    # Audit shows the gate, not a success
    tool_records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert any(
        r.tool_name == "grant_temporary_access" and r.error_kind == "requires_human_approval"
        for r in tool_records
    )

    # Agent path — same skill and same tool via LLM decision
    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("grant_temporary_access", justification="need elevated access")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    agent_result = await agent.run(
        env["context"], env["principal"], "grant me access", env["authorization"]
    )
    assert agent_result.status.value == "approval_required"
    assert agent_result.approval_id is not None
    assert isinstance(agent_result.approval_id, str) and agent_result.approval_id
    assert agent_result.error_kind == "approval_required"
    assert len(agent_result.steps) == 1
    assert agent_result.steps[0].status is SkillExecutionStatus.APPROVAL_REQUIRED
    # Still no handler invocation on the Agent path
    assert not any(name == "grant_temporary_access" for name, _, _ in env["calls"])


async def test_agent_grant_temporary_access_requires_human_approval(repositories, db):
    """Explicit Agent regression: Agent → grant_temporary_access → APPROVAL_REQUIRED.

    No skill-level approval is set; the tool's own
    REQUIRE_HUMAN_APPROVAL policy is the gate. The approval_id must be
    returned and the handler must not have run. This is the coverage hole
    noted in the review: previously only skill-level approval was exercised
    for the Agent.
    """
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["grant_temporary_access"])

    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("grant_temporary_access", justification="agent needs access")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    result = await agent.run(env["context"], env["principal"], "agent grant", env["authorization"])

    assert result.status.value == "approval_required"
    assert result.approval_id is not None
    assert result.error_kind == "approval_required"
    assert len(result.steps) == 1
    assert result.steps[0].status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert not any(name == "grant_temporary_access" for name, _, _ in env["calls"])
    # No successful tool audit was written
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert not any(r.status is ToolExecutionStatus.SUCCESS for r in records)
    assert any(
        r.tool_name == "grant_temporary_access" and r.error_kind == "requires_human_approval"
        for r in records
    )


async def test_production_wiring_converges_on_same_governed_services(client):
    """Prove Agent and manual share the real application service instances.

    Rewiring Agent to its own SkillExecutionService/ToolExecutionService must
    fail this test. The assertion is against the live ``app_context`` wired
    at startup, not the test-created environment object.
    """
    assert app_context.agent_service.skill_execution_service is app_context.skill_execution_service
    assert app_context.skill_execution_service.tool_service is app_context.services.get(
        "tool_service"
    )
    assert app_context.agent_service.skill_service is app_context.skill_service
    assert app_context.skill_execution_service.skill_service is app_context.skill_service


# ---------------------------------------------------------------------------
# Real HTTP path — manual POST /tenants/{tenant_id}/skills/{skill_id}/execute
# ---------------------------------------------------------------------------


def _http_unique(prefix: str) -> str:
    return f"unified-http-{prefix}-{uuid.uuid4().hex[:8]}"


async def _seed_http_tenant(repositories, name="Unified HTTP Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_http_unique("tenant"), name=name))


async def _seed_http_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_http_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="http-user")
    )


async def _seed_http_membership(repositories, user_id, tenant_id):
    _, _, membership_repo = repositories
    return await membership_repo.create(
        Membership(
            id=_http_unique("membership"),
            user_id=user_id,
            tenant_id=tenant_id,
            role=UserRole.MEMBER,
        )
    )


def _http_create_skill(client, tenant_id, token, **overrides):
    payload = {
        "name": _http_unique("skill"),
        "purpose": "HTTP unified skill",
        "allowed_tools": ["check_service_health"],
    }
    payload.update(overrides)
    resp = client.post(
        f"/tenants/{tenant_id}/skills",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_manual_http_happy_path_exercises_controller(
    client, repositories, make_token, authorization_override
):
    """Real manual path via POST /tenants/{id}/skills/{id}/execute (happy)."""
    tenant = await _seed_http_tenant(repositories)
    user = await _seed_http_user(repositories)
    await _seed_http_membership(repositories, user.id, tenant.id)
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    skill_id = _http_create_skill(client, tenant.id, token)

    resp = client.post(
        f"/tenants/{tenant.id}/skills/{skill_id}/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
            "satisfied_preconditions": [],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["error_kind"] is None
    assert body["tenant_id"] == tenant.id
    assert body["principal_id"] == user.id
    assert len(body["steps"]) == 1
    assert body["steps"][0]["status"] == "success"
    assert body["steps"][0]["tool_name"] == "check_service_health"


async def test_manual_http_refusal_covers_governance_and_tenant_validation(
    client, repositories, make_token, authorization_override
):
    """Real manual path refusal via HTTP: disallowed tool and tenant mismatch."""
    tenant = await _seed_http_tenant(repositories, name="HTTP Tenant A")
    tenant_b = await _seed_http_tenant(repositories, name="HTTP Tenant B")
    user = await _seed_http_user(repositories)
    await _seed_http_membership(repositories, user.id, tenant.id)
    await _seed_http_membership(repositories, user.id, tenant_b.id)
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    skill_id = _http_create_skill(client, tenant.id, token, allowed_tools=["check_service_health"])

    # Governance refusal: disallowed tool is DENIED, not a 500
    denied = client.post(
        f"/tenants/{tenant.id}/skills/{skill_id}/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tool_calls": [
                {"tool_name": "grant_temporary_access", "input": {"justification": "x"}}
            ],
            "satisfied_preconditions": [],
        },
    )
    assert denied.status_code == 200
    body = denied.json()
    assert body["status"] == "denied"
    assert body["steps"][-1]["error_kind"] == "disallowed_tool"

    # Tenant-path validation: executing through another tenant is 404 (no leakage)
    cross = client.post(
        f"/tenants/{tenant_b.id}/skills/{skill_id}/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
            "satisfied_preconditions": [],
        },
    )
    assert cross.status_code == 404

    # skill:execute RBAC is enforced at the controller — a tenant user
    # without the permission gets 403 before any execution
    authorization_override({user.id: ApplicationRole.EMPLOYEE})
    token_employee = make_token(user.id)
    forbidden = client.post(
        f"/tenants/{tenant.id}/skills/{skill_id}/execute",
        headers={"Authorization": f"Bearer {token_employee}"},
        json={
            "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
            "satisfied_preconditions": [],
        },
    )
    assert forbidden.status_code == 403


async def test_audit_records_present_for_both_paths(repositories, db):
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["echo_tool"])
    await env["engine"].execute(
        env["context"], env["principal"], skill.id, [_call("echo_tool")], [], env["authorization"]
    )
    records1 = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records1) >= 1

    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.side_effect = [
        {
            "skill_id": skill.id,
            "tool_calls": [_call("echo_tool")],
            "satisfied_preconditions": [],
        },
        None,
    ]
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    await agent.run(env["context"], env["principal"], "audit test", env["authorization"])
    records2 = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records2) > len(records1)


async def test_unauthorized_tool_is_denied_on_both_paths(repositories, db):
    """Restricted tool requiring RESTART is denied identically via both paths.

    The ToolRegistry is built as a closed whitelist containing the restricted
    tool; the registry private dict is never mutated.
    """
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Unified"))

    calls: list = []

    def _restricted_handler(input_data, tenant_id):
        calls.append(("restricted_tool", dict(input_data), tenant_id))
        return {"ok": True}

    RESTART = Permission(resource="tool", action="restart")
    restricted = ToolDefinition(
        name="restricted_tool",
        version="1",
        description="restricted",
        input_model=EchoInput,
        output_model=EchoInput,
        required_permissions=frozenset({TOOL_EXECUTE, RESTART}),
        risk_level=ToolRiskLevel.LOW,
        execution_policy=ToolExecutionPolicy(),
        audit_policy=ToolAuditPolicy(record_summary_only=True),
        handler=_restricted_handler,
    )

    def _echo_handler(input_data, tenant_id):
        calls.append(("echo_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "echo": input_data}

    def _echo_tool():
        return ToolDefinition(
            name="echo_tool",
            version="1",
            description="echo",
            input_model=EchoInput,
            output_model=EchoInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(record_summary_only=True),
            handler=_echo_handler,
        )

    # Closed whitelist containing the restricted tool — no mutation of _tools.
    registry = ToolRegistry(
        {
            "check_service_health": SERVICE_HEALTH_TOOL,
            "echo_tool": _echo_tool(),
            "restricted_tool": restricted,
        }
    )
    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    record_repo = PostgreSQLToolExecutionRepository(db)
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    approval_service = HumanApprovalService(PostgreSQLApprovalRequestRepository(db))
    tool_service = ToolExecutionService(registry, record_repo, approval_service=approval_service)
    engine = SkillExecutionService(
        skill_service=skill_service,
        tool_service=tool_service,
        record_repo=skill_record_repo,
        approval_service=approval_service,
    )
    context = _context(tenant.id)
    principal = _principal()
    authorization = _authorization()
    skill = await skill_service.create_skill(
        context,
        Skill(
            id="unassigned",
            tenant_id="placeholder",
            name=_unique("skill"),
            purpose="p",
            allowed_tools=["restricted_tool"],
        ),
    )

    r = await engine.execute(
        context,
        principal,
        skill.id,
        [_call("restricted_tool")],
        [],
        authorization,
    )
    assert r.status is SkillExecutionStatus.FAILED
    assert r.error_kind == "tool_denied"
    assert len(r.steps) == 1
    assert r.steps[0].error_kind == "tool_denied"
    assert calls == []
    denied_records = await record_repo.list_for_tenant(tenant.id)
    assert any(rr.error_kind == "authorization_denied" for rr in denied_records)

    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("restricted_tool")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=skill_service,
        skill_execution_service=engine,
        llm_provider=mock_llm,
    )
    r2 = await agent.run(context, principal, "restricted", authorization)
    assert r2.status.value == "failed"
    assert r2.error_kind == "tool_denied"
    assert len(r2.steps) == 1
    assert r2.steps[0].status is SkillExecutionStatus.FAILED
    assert r2.steps[0].error_kind == "tool_denied"
    assert calls == []


async def test_inactive_skill_rejected_on_both_paths(repositories, db):
    """Inactive skill is rejected before any tool call on both paths."""
    env = await _build_env(repositories, db)
    skill = await _create_skill(
        env,
        status=SkillStatus.INACTIVE,
        allowed_tools=["echo_tool"],
    )
    r = await env["engine"].execute(
        env["context"], env["principal"], skill.id, [_call("echo_tool")], [], env["authorization"]
    )
    assert r.status is SkillExecutionStatus.FAILED
    assert r.error_kind == "inactive_skill"
    assert r.steps == []
    assert env["calls"] == []

    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.return_value = {
        "skill_id": skill.id,
        "tool_calls": [_call("echo_tool")],
        "satisfied_preconditions": [],
    }
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    r2 = await agent.run(env["context"], env["principal"], "inactive", env["authorization"])
    assert r2.status.value == "failed"
    assert r2.error_kind == "inactive_skill"
    assert len(r2.steps) == 1
    assert r2.steps[0].error_kind == "inactive_skill"
    # Agent path also never reached the handler
    assert env["calls"] == []
    assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


async def test_tool_output_not_exposing_secrets_via_persisted_records(repositories, db):
    """Persisted audit summaries must not contain the raw secret; they show [REDACTED]."""
    env = await _build_env(repositories, db)
    skill = await _create_skill(env, allowed_tools=["echo_tool"])
    secret_value = "should_not_persist_raw_98765"
    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", secret=secret_value, x="1")],
        [],
        env["authorization"],
    )
    assert result.status is SkillExecutionStatus.SUCCEEDED

    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) >= 1
    blob = " ".join(f"{r.input_summary} {r.output_summary or ''}" for r in records)
    assert secret_value not in blob
    assert "[REDACTED]" in blob

    # SkillExecutionRecord currently stores only a safe result_summary
    # (status/steps), not raw tool input. This assertion is a
    # format-regression guard: if a future change starts embedding input
    # into result_summary, it must not leak the raw secret.
    skill_records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    skill_blob = " ".join(f"{r.result_summary or ''} {r.failure_code or ''}" for r in skill_records)
    assert secret_value not in skill_blob

    # Agent path must also redact when the same secret travels through it
    secret_agent = "should_not_persist_raw_agent_11223"
    skill2 = await _create_skill(env, allowed_tools=["echo_tool"])
    records_before_agent = await env["record_repo"].list_for_tenant(env["tenant"].id)
    mock_llm = MagicMock(spec=SkillSelectingLlm)
    mock_llm.skill_decision_capable = True
    mock_llm.propose_skill.side_effect = [
        {
            "skill_id": skill2.id,
            "tool_calls": [_call("echo_tool", secret=secret_agent)],
            "satisfied_preconditions": [],
        },
        None,
    ]
    agent = AgentExecutionService(
        skill_service=env["skill_service"],
        skill_execution_service=env["engine"],
        llm_provider=mock_llm,
    )
    await agent.run(env["context"], env["principal"], "secret agent", env["authorization"])
    records_after_agent = await env["record_repo"].list_for_tenant(env["tenant"].id)
    ids_before = {r.id for r in records_before_agent}
    agent_records = [r for r in records_after_agent if r.id not in ids_before]
    assert len(agent_records) >= 1
    blob_agent = " ".join(f"{r.input_summary} {r.output_summary or ''}" for r in agent_records)
    assert secret_agent not in blob_agent
    assert "[REDACTED]" in blob_agent
