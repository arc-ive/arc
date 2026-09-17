"""Skill execution records persistence tests (V2-ADR-014).

Tests cover:
- Repository CRUD
- Successful skill execution persistence
- Failed skill execution persistence
- approval_required outcome persistence
- FK integrity
- Tenant scoping
- agent_run_id linkage when called from Agent
- Migration safety on an existing DB
"""

import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from arc.domain.models import (
    Skill,
    SkillExecutionRecord,
    SkillExecutionStatus,
    Tenant,
    TenantContext,
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
    ToolExecutionPolicyMode,
    ToolExecutionService,
    ToolRegistry,
    ToolRiskLevel,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    return f"skill-exec-rec-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Skill Execution Record Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id: str = "user-1") -> AuthorizationService:
    return AuthorizationService({user_id: ApplicationRole.OPERATIONS_USER})


async def _build_environment(repositories, db):
    """Wire the real service stack plus controlled test tools."""
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Skill Execution Record"))

    calls: list = []

    def _echo_handler(input_data, tenant_id):
        calls.append(("echo_tool", dict(input_data), tenant_id))
        return {"tenant_id": tenant_id, "echo": input_data}

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
            "failing_tool": _tool("failing_tool", handler=_failing_handler),
            "gated_tool": _tool(
                "gated_tool",
                policy=ToolExecutionPolicy(ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL),
                handler=_echo_handler,
            ),
        }
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    tool_record_repo = PostgreSQLToolExecutionRepository(db)
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    tool_service = ToolExecutionService(registry, tool_record_repo)
    engine = SkillExecutionService(
        skill_service=skill_service,
        tool_service=tool_service,
        record_repo=skill_record_repo,
    )

    context = _context(tenant.id)
    return {
        "engine": engine,
        "skill_service": skill_service,
        "skill_record_repo": skill_record_repo,
        "tool_record_repo": tool_record_repo,
        "tenant": tenant,
        "context": context,
        "principal": _principal(),
        "authorization": _authorization(),
        "calls": calls,
    }


async def _create_skill(env, **overrides) -> Skill:
    values = {
        "id": "unassigned",
        "tenant_id": "placeholder",
        "name": _unique("skill"),
        "purpose": "Test skill for execution records",
        "allowed_tools": ["check_service_health", "echo_tool"],
    }
    values.update(overrides)
    return await env["skill_service"].create_skill(env["context"], Skill(**values))


async def _insert_skill_row(db, skill_id: str, tenant_id: str) -> None:
    """Insert a minimal skill row directly to satisfy FK constraints."""
    async with db._connection_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO skills (id, tenant_id, name, version, purpose, status, definition)
            VALUES ($1, $2, $3, '1', 'test', 'active', '{}')
            """,
            skill_id,
            tenant_id,
            f"skill-{skill_id[:8]}",
        )


def _call(tool_name, **input_fields):
    return {"tool_name": tool_name, "input": input_fields}


# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------


async def test_repository_create_and_get(repositories, db):
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Repo Test"))

    await _insert_skill_row(db, "skill-123", tenant.id)

    record = SkillExecutionRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        skill_id="skill-123",
        skill_version="1",
        principal_id="user-1",
        status=SkillExecutionStatus.SUCCEEDED,
        started_at=None,
        completed_at=None,
    )
    await skill_record_repo.create_record(record)

    fetched = await skill_record_repo.get_record(record.id, tenant.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.tenant_id == tenant.id
    assert fetched.skill_id == "skill-123"
    assert fetched.status is SkillExecutionStatus.SUCCEEDED


async def test_repository_list_for_tenant(repositories, db):
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Repo List Test"))

    await _insert_skill_row(db, "skill-list", tenant.id)

    for i in range(3):
        await skill_record_repo.create_record(
            SkillExecutionRecord(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                skill_id="skill-list",
                skill_version="1",
                principal_id="user-1",
                status=SkillExecutionStatus.SUCCEEDED,
            )
        )

    records = await skill_record_repo.list_for_tenant(tenant.id)
    assert len(records) == 3
    assert all(r.tenant_id == tenant.id for r in records)


async def test_repository_update_record(repositories, db):
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Repo Update Test"))

    await _insert_skill_row(db, "skill-upd", tenant.id)

    record = SkillExecutionRecord(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        skill_id="skill-upd",
        skill_version="1",
        principal_id="user-1",
        status=SkillExecutionStatus.FAILED,
    )
    await skill_record_repo.create_record(record)

    record.status = SkillExecutionStatus.SUCCEEDED
    record.failure_code = None
    record.failure_message = None
    record.result_summary = "status=succeeded steps=1"
    await skill_record_repo.update_record(record)

    fetched = await skill_record_repo.get_record(record.id, tenant.id)
    assert fetched.status is SkillExecutionStatus.SUCCEEDED
    assert fetched.result_summary == "status=succeeded steps=1"


# ---------------------------------------------------------------------------
# Successful execution persistence
# ---------------------------------------------------------------------------


async def test_successful_execution_persists_record(repositories, db):
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

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    rec = records[0]
    assert rec.tenant_id == env["tenant"].id
    assert rec.skill_id == skill.id
    assert rec.skill_version == skill.version
    assert rec.principal_id == "user-1"
    assert rec.status is SkillExecutionStatus.SUCCEEDED
    assert rec.completed_at is not None
    assert rec.failure_code is None
    assert rec.result_summary is not None
    assert "succeeded" in rec.result_summary


# ---------------------------------------------------------------------------
# Failed execution persistence
# ---------------------------------------------------------------------------


async def test_failed_execution_persists_record(repositories, db):
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

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    rec = records[0]
    assert rec.status is SkillExecutionStatus.FAILED
    assert rec.failure_code == "execution_error"
    assert rec.completed_at is not None


# ---------------------------------------------------------------------------
# approval_required outcome persistence
# ---------------------------------------------------------------------------


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

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    rec = records[0]
    assert rec.status is SkillExecutionStatus.APPROVAL_REQUIRED
    assert rec.failure_code == "approval_required"
    assert rec.completed_at is not None


# ---------------------------------------------------------------------------
# FK integrity: invalid skill_id rejected
# ---------------------------------------------------------------------------


async def test_invalid_skill_id_raises_before_record_creation(repositories, db):
    """FK constraint prevents persisting a record with nonexistent skill_id."""
    env = await _build_environment(repositories, db)

    with pytest.raises(Exception):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            "nonexistent-skill-id",
            [_call("check_service_health")],
            [],
            env["authorization"],
        )

    # No record persisted — FK violation on INSERT prevents it.
    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 0


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


async def test_tenant_scoping_prevents_cross_tenant_access(repositories, db):
    skill_record_repo = PostgreSQLSkillExecutionRecordRepository(db)
    tenant_repo, _, _ = repositories

    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant-a"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="Tenant B"))

    await _insert_skill_row(db, "skill-a1", tenant_a.id)
    await _insert_skill_row(db, "skill-b1", tenant_b.id)

    await skill_record_repo.create_record(
        SkillExecutionRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a.id,
            skill_id="skill-a1",
            skill_version="1",
            principal_id="user-a",
            status=SkillExecutionStatus.SUCCEEDED,
        )
    )
    await skill_record_repo.create_record(
        SkillExecutionRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_b.id,
            skill_id="skill-b1",
            skill_version="1",
            principal_id="user-b",
            status=SkillExecutionStatus.FAILED,
        )
    )

    records_a = await skill_record_repo.list_for_tenant(tenant_a.id)
    records_b = await skill_record_repo.list_for_tenant(tenant_b.id)

    assert len(records_a) == 1
    assert records_a[0].tenant_id == tenant_a.id
    assert len(records_b) == 1
    assert records_b[0].tenant_id == tenant_b.id


# ---------------------------------------------------------------------------
# agent_run_id linkage
# ---------------------------------------------------------------------------


async def test_agent_run_id_persists_when_provided(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)
    agent_run_id = str(uuid.uuid4())

    result = await env["engine"].execute(
        env["context"],
        env["principal"],
        skill.id,
        [_call("check_service_health")],
        [],
        env["authorization"],
        agent_run_id=agent_run_id,
    )

    assert result.agent_run_id == agent_run_id

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].agent_run_id == agent_run_id


async def test_agent_run_id_null_for_direct_execution(repositories, db):
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

    assert result.agent_run_id is None

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 1
    assert records[0].agent_run_id is None


# ---------------------------------------------------------------------------
# Migration safety: DDL idempotence
# ---------------------------------------------------------------------------


async def test_ddl_is_idempotent(repositories, db):
    """Run schema creation twice — second run must not fail or duplicate."""
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"
    schema = schema_path.read_text()

    async with db._connection_pool.acquire() as conn:
        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)
        # Run again
        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)

    # Verify skill_execution_records still exists and is queryable
    async with db._connection_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT to_regclass('public.skill_execution_records') AS rel")
        assert row["rel"] is not None


# ---------------------------------------------------------------------------
# Skill execution records are append-oriented (multiple executions)
# ---------------------------------------------------------------------------


async def test_multiple_executions_produce_separate_records(repositories, db):
    env = await _build_environment(repositories, db)
    skill = await _create_skill(env)

    for _ in range(3):
        await env["engine"].execute(
            env["context"],
            env["principal"],
            skill.id,
            [_call("check_service_health")],
            [],
            env["authorization"],
        )

    records = await env["skill_record_repo"].list_for_tenant(env["tenant"].id)
    assert len(records) == 3
    assert len({r.id for r in records}) == 3  # all unique IDs
