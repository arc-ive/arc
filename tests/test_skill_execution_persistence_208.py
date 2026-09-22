"""Regression tests for Issue #208: skill execution records persistence.

The ``PostgreSQLSkillExecutionRecordRepository`` existed but was never
wired into ``SkillExecutionService`` (``record_repo=None``), so terminal
skill outcomes disappeared from audit/observability. These tests prove:

- every terminal outcome persists exactly one record (succeeded, denied,
  failed, approval_required, precondition_failed, capability-disabled);
- a denied execution persists;
- persistence failure is logged and never breaks the business response;
- one execution never creates duplicate records;
- an unexpected mid-execution failure still leaves a terminal FAILED row;
- the API execute path persists a readable record visible in usage-summary
  (including the denied case).
"""

import logging
import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from arc.domain.models import (
    Membership,
    Skill,
    SkillExecutionRecord,
    SkillExecutionStatus,
    Tenant,
    TenantContext,
    ToolExecutionStatus,
    User,
    UserRole,
)
from arc.repositories.skill_execution import PostgreSQLSkillExecutionRecordRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import TOOL_EXECUTE, AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
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
)


class EchoInput(BaseModel):
    """Permissive input model for deterministic test tools."""

    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    return f"skill-exec-208-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Issue 208 Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id: str = "user-1") -> AuthorizationService:
    return AuthorizationService({user_id: ApplicationRole.OPERATIONS_USER})


class _InMemoryRecordRepo:
    """In-memory SkillExecutionRecordRepository for unit tests."""

    def __init__(self, fail_on_create=False, fail_on_update=False):
        self.records = {}
        self.create_calls = 0
        self.update_calls = 0
        self.fail_on_create = fail_on_create
        self.fail_on_update = fail_on_update

    async def create_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        self.create_calls += 1
        if self.fail_on_create:
            raise RuntimeError("simulated record persistence failure")
        self.records[record.id] = record
        return record

    async def update_record(self, record: SkillExecutionRecord) -> SkillExecutionRecord:
        self.update_calls += 1
        if self.fail_on_update:
            raise RuntimeError("simulated record update failure")
        self.records[record.id] = record
        return record

    async def get_record(self, record_id: str, tenant_id: str):
        record = self.records.get(record_id)
        if record is None or record.tenant_id != tenant_id:
            return None
        return record

    async def list_for_tenant(self, tenant_id: str, limit: int = 50):
        return [r for r in self.records.values() if r.tenant_id == tenant_id][:limit]

    async def list_for_skill(self, tenant_id: str, skill_id: str, limit: int = 50):
        return [
            r for r in self.records.values() if r.tenant_id == tenant_id and r.skill_id == skill_id
        ][:limit]

    async def list_for_agent_run(self, agent_run_id: str, tenant_id: str, limit: int = 1000):
        return [
            r
            for r in self.records.values()
            if r.agent_run_id == agent_run_id and r.tenant_id == tenant_id
        ][:limit]


class _DisabledCapabilityService:
    """Capability service stub reporting skill_execution as disabled."""

    async def is_enabled(self, tenant_id: str, capability_id: str) -> bool:
        return False


async def _build_environment(repositories, db, record_repo=None, capability_service=None):
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Issue 208"))

    def _echo_handler(input_data, tenant_id):
        return {"tenant_id": tenant_id, "echo": dict(input_data)}

    def _failing_handler(input_data, tenant_id):
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
            "failing_tool": _tool("failing_tool", handler=_failing_handler),
        }
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    tool_service = ToolExecutionService(registry, PostgreSQLToolExecutionRepository(db))
    engine = SkillExecutionService(
        skill_service=skill_service,
        tool_service=tool_service,
        record_repo=record_repo if record_repo is not None else _InMemoryRecordRepo(),
        capability_service=capability_service,
    )
    return {
        "engine": engine,
        "skill_service": skill_service,
        "tenant": tenant,
        "context": _context(tenant.id),
        "principal": _principal(),
        "authorization": _authorization(),
        "record_repo": engine.record_repo,
    }


async def _create_skill(env, **overrides) -> Skill:
    values = {
        "id": "unassigned",
        "tenant_id": "placeholder",
        "name": _unique("skill"),
        "purpose": "Issue 208 regression skill",
        "allowed_tools": ["check_service_health", "echo_tool"],
    }
    values.update(overrides)
    return await env["skill_service"].create_skill(env["context"], Skill(**values))


def _call(tool_name, **input_fields):
    return {"tool_name": tool_name, "input": input_fields}


# ---------------------------------------------------------------------------
# Terminal outcome persistence (unit, in-memory record repo)
# ---------------------------------------------------------------------------


async def test_succeeded_persists_record(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool", marker="m1")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    rec = records[0]
    assert rec.tenant_id == env["tenant"].id
    assert rec.skill_id == skill.id
    assert rec.status is SkillExecutionStatus.SUCCEEDED
    assert rec.completed_at is not None
    assert rec.failure_code is None


async def test_denied_persists_record(repositories, db):
    """A denied skill execution (disallowed tool) MUST leave an audit row."""
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env, allowed_tools=["check_service_health"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.DENIED
    assert result.error_kind == "disallowed_tool"
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    rec = records[0]
    assert rec.tenant_id == env["tenant"].id
    assert rec.skill_id == skill.id
    assert rec.status is SkillExecutionStatus.DENIED
    assert rec.failure_code == "disallowed_tool"
    assert rec.completed_at is not None


async def test_failed_persists_record(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(
        env, allowed_tools=["check_service_health", "echo_tool", "failing_tool"]
    )

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("failing_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.FAILED
    assert records[0].failure_code == "execution_error"
    assert records[0].completed_at is not None


async def test_approval_required_persists_record(repositories, db):
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
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert records[0].failure_code == "approval_required"


async def test_precondition_failed_persists_record(repositories, db):
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
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.PRECONDITION_FAILED
    assert records[0].failure_code == "precondition_failed"


async def test_capability_disabled_persists_failed_record(repositories, db):
    env = await _build_environment(
        repositories, db, capability_service=_DisabledCapabilityService()
    )
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.FAILED
    assert result.error_kind == "capability_disabled"
    records = await env["record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.FAILED
    assert records[0].failure_code == "capability_disabled"


# ---------------------------------------------------------------------------
# Persistence failure isolation + no-duplicate guarantee
# ---------------------------------------------------------------------------


async def test_persistence_failure_preserves_business_response_and_logs(repositories, db, caplog):
    repo = _InMemoryRecordRepo(fail_on_create=True, fail_on_update=True)
    env = await _build_environment(repositories, db, record_repo=repo)
    skill = await _create_skill(env)

    with caplog.at_level(logging.WARNING, logger="arc.skill_execution"):
        result = await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("echo_tool")],
            [],
            env["authorization"],
        )

    # Business outcome is authoritative: success stays success.
    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert result.steps[0].status is ToolExecutionStatus.SUCCESS
    # The failure was logged with structured context, not swallowed silently.
    assert "skill_execution_record_create_failed" in caplog.text
    assert skill.id in caplog.text


async def test_one_execution_produces_exactly_one_record(repositories, db):
    repo = _InMemoryRecordRepo()
    env = await _build_environment(repositories, db, record_repo=repo)
    skill = await _create_skill(env)

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("echo_tool"), _call("echo_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.SUCCEEDED
    assert repo.create_calls == 1
    assert repo.update_calls == 1
    records = await repo.list_for_tenant(env["tenant"].id)
    assert len(records) == 1


async def test_denied_execution_produces_exactly_one_record(repositories, db):
    repo = _InMemoryRecordRepo()
    env = await _build_environment(repositories, db, record_repo=repo)
    skill = await _create_skill(env, allowed_tools=["check_service_health"])

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health"), _call("echo_tool")],
        [],
        env["authorization"],
    )

    assert result.status is SkillExecutionStatus.DENIED
    assert repo.create_calls == 1
    assert repo.update_calls == 1
    records = await repo.list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.DENIED


async def test_unexpected_tool_failure_still_persists_failed_record(repositories, db):
    """An unexpected exception mid-execution leaves a FAILED row, then re-raises."""

    class _ExplodingToolService:
        async def execute_tool(self, *args, **kwargs):
            raise RuntimeError("simulated unexpected tool service crash")

    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Issue 208"))
    skill_service = SkillService(PostgreSQLSkillRepository(db))
    context = _context(tenant.id)
    skill = await skill_service.create_skill(
        context,
        Skill(
            id="unassigned",
            tenant_id="placeholder",
            name=_unique("skill"),
            purpose="Issue 208 regression skill",
            allowed_tools=["echo_tool"],
        ),
    )
    repo = _InMemoryRecordRepo()
    engine = SkillExecutionService(
        skill_service=skill_service,
        tool_service=_ExplodingToolService(),
        record_repo=repo,
    )

    with pytest.raises(RuntimeError, match="unexpected tool service crash"):
        await engine.execute(
            context, _principal(), skill.id, [_call("echo_tool")], [], _authorization()
        )

    records = await repo.list_for_tenant(tenant.id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.FAILED
    assert records[0].failure_code == "execution_error"
    assert records[0].completed_at is not None


# ---------------------------------------------------------------------------
# API regression: execute -> readable record -> usage-summary
# ---------------------------------------------------------------------------


def _api_unique(prefix: str) -> str:
    return f"skill-208-api-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_api_actor(repositories):
    tenant_repo, user_repo, membership_repo = repositories
    tenant = await tenant_repo.create(Tenant(id=_api_unique("tenant"), name="Issue 208 API"))
    user = await user_repo.create(
        User(
            id=_api_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="issue-208-user",
        )
    )
    await membership_repo.create(
        Membership(
            id=_api_unique("membership"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )
    return tenant, user


def _execute_via_api(client, tenant_id, token, skill_id, body):
    return client.post(
        f"/skills/{skill_id}/execute?tenant_id={tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def test_api_execute_persists_record_visible_in_usage_summary(
    client, repositories, db, make_token, authorization_override
):
    tenant, user = await _seed_api_actor(repositories)
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    create = client.post(
        f"/skills?tenant_id={tenant.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": _api_unique("skill"),
            "purpose": "Issue 208 API regression",
            "allowed_tools": ["check_service_health"],
        },
    )
    assert create.status_code == 200
    skill_id = create.json()["id"]

    response = _execute_via_api(
        client,
        tenant.id,
        token,
        skill_id,
        {"tool_calls": [{"tool_name": "check_service_health", "input": {}}]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"

    record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    records = await record_repo.list_for_skill(tenant.id, skill_id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.SUCCEEDED
    assert records[0].tenant_id == tenant.id

    summary = client.get(
        f"/tenants/{tenant.id}/observability/usage-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200
    skills = summary.json()["skills"]
    assert skills["total_executions"] >= 1
    assert skills["succeeded"] >= 1


async def test_api_denied_execution_persisted_and_visible_in_usage_summary(
    client, repositories, db, make_token, authorization_override
):
    tenant, user = await _seed_api_actor(repositories)
    authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
    token = make_token(user.id)

    create = client.post(
        f"/skills?tenant_id={tenant.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": _api_unique("skill"),
            "purpose": "Issue 208 API denied regression",
            "allowed_tools": ["check_service_health"],
        },
    )
    assert create.status_code == 200
    skill_id = create.json()["id"]

    response = _execute_via_api(
        client,
        tenant.id,
        token,
        skill_id,
        {"tool_calls": [{"tool_name": "restart_service", "input": {}}]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "denied"

    record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    records = await record_repo.list_for_skill(tenant.id, skill_id)
    assert len(records) == 1
    assert records[0].status is SkillExecutionStatus.DENIED

    summary = client.get(
        f"/tenants/{tenant.id}/observability/usage-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary.status_code == 200
    skills = summary.json()["skills"]
    assert skills["total_executions"] >= 1
    assert skills["denied"] >= 1
