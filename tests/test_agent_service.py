"""Agent orchestration tests (real PostgreSQL, real SkillExecutionService).

The Agent is security-sensitive: these tests prove it can ONLY act by
delegating to ``SkillExecutionService`` (which alone enforces
``Skill.allowed_tools``, tool RBAC/policy/validation and tenant-scoped
audit), that its decisions are strictly bounded and fail closed, and that
the trusted ``TenantContext`` can never be influenced by model output.
"""

import uuid
from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, ConfigDict

from arc.domain.models import (
    AgentRunStatus,
    Skill,
    SkillExecutionStatus,
    SkillStatus,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories.observability import PostgreSQLObservabilityRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import TOOL_EXECUTE, AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.agent import MAX_AGENT_STEPS, AgentExecutionService
from arc.services.llm import DeterministicLlmProvider
from arc.services.observability import ObservabilityService
from arc.services.pii import PiiGuardConfig, PiiGuardService
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
    """Permissive input model for the deterministic echo test tool."""

    model_config = ConfigDict(extra="allow")


def _unique(prefix: str) -> str:
    return f"agent-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str, user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Agent Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id)


def _authorization(user_id: str = "user-1") -> AuthorizationService:
    return AuthorizationService({user_id: ApplicationRole.OPERATIONS_USER})


async def _build_environment(repositories, db, decisions=None, observability_service=None):
    """Wire the real stack plus a scripted decision provider.

    Returns the agent under test together with everything needed to prove
    delegation (real tool audit repository) and decision-boundary behavior
    (recorded provider calls). ``decisions`` is a mutable list the test
    fills with raw decision payloads / None before running.
    """
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Agent Tenant"))

    decisions = decisions if decisions is not None else []
    queue = deque(decisions)
    provider_calls: list = []

    def _script(goal, catalog):
        provider_calls.append(
            {
                "goal": goal,
                "catalog": [dict(item) for item in catalog],
            }
        )
        return queue.popleft() if queue else None

    def _echo_handler(input_data, tenant_id):
        return {"tenant_id": tenant_id, "echo": input_data}

    def _tool(name, *, handler=None):
        return ToolDefinition(
            name=name,
            version="1",
            description=f"Deterministic {name} test tool",
            input_model=EchoInput,
            output_model=EchoInput,
            required_permissions=frozenset({TOOL_EXECUTE}),
            risk_level=ToolRiskLevel.LOW,
            execution_policy=ToolExecutionPolicy(),
            audit_policy=ToolAuditPolicy(record_summary_only=True),
            handler=handler or _echo_handler,
        )

    registry = ToolRegistry(
        {"check_service_health": SERVICE_HEALTH_TOOL, "echo_tool": _tool("echo_tool")}
    )

    skill_repo = PostgreSQLSkillRepository(db)
    skill_service = SkillService(skill_repo)
    record_repo = PostgreSQLToolExecutionRepository(db)
    tool_service = ToolExecutionService(registry, record_repo)
    engine = SkillExecutionService(skill_service=skill_service, tool_service=tool_service)
    agent = AgentExecutionService(
        skill_service=skill_service,
        skill_execution_service=engine,
        llm_provider=DeterministicLlmProvider(skill_decision_script=_script),
        observability_service=observability_service,
    )

    return {
        "agent": agent,
        "skill_service": skill_service,
        "record_repo": record_repo,
        "provider_calls": provider_calls,
        "queue": queue,
        "tenant": tenant,
        "context": _context(tenant.id),
        "principal": _principal(),
        "authorization": _authorization(),
    }


async def _create_skill(env, **overrides) -> Skill:
    values = {
        "id": "unassigned",
        "tenant_id": "placeholder",
        "name": _unique("skill"),
        "purpose": "Recover a degraded service",
        "allowed_tools": ["check_service_health", "echo_tool"],
    }
    values.update(overrides)
    return await env["skill_service"].create_skill(env["context"], Skill(**values))


def _decision(skill_id, tool_name="check_service_health", **call_input):
    return {
        "skill_id": skill_id,
        "tool_calls": [{"tool_name": tool_name, "input": dict(call_input)}],
        "satisfied_preconditions": [],
    }


class TestCapabilityGate:
    async def test_unarmed_default_provider_fails_closed(self, repositories, db):
        env = await _build_environment(repositories, db)
        env["agent"].llm_provider = DeterministicLlmProvider()  # unarmed default

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "agent_capability_unavailable"
        assert result.steps == []
        assert env["provider_calls"] == []
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []

    async def test_non_skill_selecting_provider_fails_closed(self, repositories, db):
        env = await _build_environment(repositories, db)

        class CompletionOnlyProvider:
            def complete(self, prompt: str) -> str:
                return "text"

        env["agent"].llm_provider = CompletionOnlyProvider()

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "agent_capability_unavailable"
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


class TestBoundedOrchestration:
    async def test_success_then_provider_decline_is_succeeded(self, repositories, db):
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.SUCCEEDED
        assert result.error_kind is None
        assert len(result.steps) == 1
        assert result.steps[0].skill_id == skill.id
        assert result.steps[0].status is SkillExecutionStatus.SUCCEEDED
        assert len(env["provider_calls"]) == 2  # one decision + one decline
        records = await env["record_repo"].list_for_tenant(env["tenant"].id)
        assert len(records) == 1  # real delegated tool execution audited

    async def test_three_successful_decisions_reach_hard_bound(self, repositories, db):
        env = await _build_environment(repositories, db)
        skills = [await _create_skill(env) for _ in range(3)]
        for skill in skills:
            env["queue"].append(_decision(skill.id, "echo_tool", marker=skill.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.MAX_STEPS_REACHED
        assert result.error_kind == "max_steps_reached"
        assert len(result.steps) == MAX_AGENT_STEPS
        assert [step.sequence for step in result.steps] == [0, 1, 2]
        assert len(env["provider_calls"]) == MAX_AGENT_STEPS  # never a fourth ask
        assert len(await env["record_repo"].list_for_tenant(env["tenant"].id)) == 3

    async def test_skill_failure_stops_immediately_without_retry(self, repositories, db):
        env = await _build_environment(repositories, db)
        bad = await _create_skill(env, allowed_tools=["check_service_health", "ghost_tool"])
        good = await _create_skill(env)
        env["queue"].extend(
            [_decision(bad.id, "ghost_tool"), _decision(good.id), _decision(good.id)]
        )

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "unknown_tool"
        assert len(result.steps) == 1
        assert result.steps[-1].error_kind == "unknown_tool"
        assert len(env["provider_calls"]) == 1  # no second decision, no retry

    async def test_approval_required_propagates_and_stops(self, repositories, db):
        env = await _build_environment(repositories, db)
        gated = await _create_skill(env, approval_required=True)
        env["queue"].append(_decision(gated.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.APPROVAL_REQUIRED
        assert result.error_kind == "approval_required"
        assert result.steps[-1].status is SkillExecutionStatus.APPROVAL_REQUIRED
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []


class TestDecisionBoundaryFailures:
    async def test_invalid_decisions_execute_nothing(self, repositories, db):
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)

        malformed = [
            {},
            {"skill_id": skill.id},
            {"skill_id": skill.id, "tool_calls": [], "satisfied_preconditions": []},
            {"skill_id": 42, "tool_calls": [{"tool_name": "t"}], "satisfied_preconditions": []},
            {"skill_id": skill.id, "tool_calls": ["x"], "satisfied_preconditions": []},
            {
                "skill_id": skill.id,
                "tool_calls": [{"tool_name": "t"}],
                "satisfied_preconditions": [7],
            },
        ]
        for payload in malformed:
            env["queue"].clear()
            env["queue"].append(payload)
            result = await env["agent"].run(
                env["context"], env["principal"], "goal", env["authorization"]
            )
            assert result.status is AgentRunStatus.FAILED
            assert result.error_kind == "invalid_decision"
            assert result.steps == []

        # A provider decline (None) with no executed step is no_decision,
        # not an invalid decision (contract: None means "stop proposing").
        env["queue"].clear()
        env["queue"].append(None)
        declined = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert declined.status is AgentRunStatus.FAILED
        assert declined.error_kind == "no_decision"

        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []

    async def test_out_of_catalog_skill_executes_nothing(self, repositories, db):
        env = await _build_environment(repositories, db)
        await _create_skill(env)
        env["queue"].append(_decision(f"foreign-{uuid.uuid4().hex}"))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "skill_not_available"
        assert result.steps == []
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []

    async def test_cross_tenant_skill_cannot_execute(self, repositories, db):
        env = await _build_environment(repositories, db)
        await _create_skill(env)

        other_tenant = await repositories[0].create(Tenant(id=_unique("other"), name="Other"))
        foreign_context = _context(other_tenant.id, user_id="user-2")
        foreign = await env["skill_service"].create_skill(
            foreign_context,
            Skill(
                id="unassigned",
                tenant_id="placeholder",
                name=_unique("foreign-skill"),
                purpose="p",
                allowed_tools=["check_service_health"],
            ),
        )
        env["queue"].append(_decision(foreign.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "skill_not_available"
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []

    async def test_inactive_skill_failure_propagates(self, repositories, db):
        env = await _build_environment(repositories, db)
        inactive = await _create_skill(env, status=SkillStatus.INACTIVE)
        env["queue"].append(_decision(inactive.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "inactive_skill"
        assert result.steps[-1].error_kind == "inactive_skill"

    async def test_deep_malformed_proposal_becomes_invalid_decision(self, repositories, db):
        """Engine owns deep validation; its rejection stops the run safely."""
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)
        env["queue"].append(
            {
                "skill_id": skill.id,
                "tool_calls": [{"input": "not-a-dict"}],  # missing tool_name
                "satisfied_preconditions": [],
            }
        )
        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "invalid_decision"
        assert await env["record_repo"].list_for_tenant(env["tenant"].id) == []

    async def test_oversized_tool_call_list_becomes_invalid_decision(self, repositories, db):
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)
        env["queue"].append(
            {
                "skill_id": skill.id,
                "tool_calls": [{"tool_name": "echo_tool", "input": {}} for _ in range(11)],
                "satisfied_preconditions": [],
            }
        )
        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "invalid_decision"


class TestTrustBoundaries:
    async def test_catalog_snapshot_is_tenant_scoped_and_has_no_tenant_ids(self, repositories, db):
        env = await _build_environment(repositories, db)
        own = await _create_skill(env)

        other_tenant = await repositories[0].create(Tenant(id=_unique("other"), name="Other"))
        await env["skill_service"].create_skill(
            _context(other_tenant.id, user_id="user-2"),
            Skill(
                id="unassigned",
                tenant_id="placeholder",
                name=_unique("foreign"),
                purpose="p",
            ),
        )

        env["queue"].append(None)  # immediate decline after first catalog ask
        await env["agent"].run(env["context"], env["principal"], "goal", env["authorization"])

        snapshot = env["provider_calls"][0]["catalog"]
        ids = {item["id"] for item in snapshot}
        assert ids == {own.id}
        for item in snapshot:
            assert set(item.keys()) == {"id", "name", "status"}
            assert "tenant_id" not in item

    async def test_model_supplied_tenant_hint_never_overrides_context(self, repositories, db):
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id, "echo_tool", tenant_id="tenant-B"), None])

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        assert result.status is AgentRunStatus.SUCCEEDED
        assert result.steps[0].status is SkillExecutionStatus.SUCCEEDED
        assert result.tenant_id == env["tenant"].id
        records = await env["record_repo"].list_for_tenant(env["tenant"].id)
        assert len(records) == 1
        assert records[0].tenant_id == env["tenant"].id

    async def test_agent_holds_no_tool_registry_or_audit_collaborators(self, repositories, db):
        env = await _build_environment(repositories, db)
        attrs = vars(env["agent"])
        expected = {
            "skill_service",
            "skill_execution_service",
            "llm_provider",
            "observability_service",
            "capability_service",
            "pii_guard",
        }
        assert set(attrs) == expected
        forbidden = ("tool", "registry", "handler", "audit", "record")
        assert not any(name in attrs for name in forbidden)


class TestRequestValidation:
    async def test_empty_goal_rejected(self, repositories, db):
        env = await _build_environment(repositories, db)
        with pytest.raises(ValueError, match="Goal cannot be empty"):
            await env["agent"].run(env["context"], env["principal"], "   ", env["authorization"])

    async def test_invalid_context_rejected(self, repositories, db):
        env = await _build_environment(repositories, db)
        with pytest.raises(ValueError, match="Invalid tenant context"):
            await env["agent"].run(None, env["principal"], "goal", env["authorization"])


# ------------------------------------------------------------------
# Issue #143: Service-layer trace persistence
# ------------------------------------------------------------------


async def _build_environment_with_observability(repositories, db, decisions=None):
    """Build the full stack with a real ObservabilityService wired."""
    tenant_repo, _, _ = repositories
    observability_repo = PostgreSQLObservabilityRepository(db)
    observability_svc = ObservabilityService(repository=observability_repo)
    env = await _build_environment(
        repositories,
        db,
        decisions=decisions,
        observability_service=observability_svc,
    )
    env["observability_service"] = observability_svc
    return env


class TestTracePersistence:
    """Prove every terminal outcome persists an AgentRunRecord from the service."""

    async def test_success_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        # Trace persisted by the service layer
        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == result.id
        assert trace.tenant_id == env["tenant"].id
        assert trace.status == "succeeded"
        assert trace.error_kind is None
        assert len(trace.steps) == 1
        assert trace.steps[0].skill_id == skill.id

    async def test_failure_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        bad = await _create_skill(env, allowed_tools=["check_service_health", "ghost_tool"])
        env["queue"].extend([_decision(bad.id, "ghost_tool")])

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].status == "failed"
        assert traces[0].error_kind == "unknown_tool"

    async def test_approval_required_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        gated = await _create_skill(env, approval_required=True)
        env["queue"].append(_decision(gated.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.APPROVAL_REQUIRED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].status == "approval_required"

    async def test_max_steps_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skills = [await _create_skill(env) for _ in range(3)]
        for skill in skills:
            env["queue"].append(_decision(skill.id, "echo_tool", marker=skill.id))

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.MAX_STEPS_REACHED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].status == "max_steps_reached"
        assert len(traces[0].steps) == 3

    async def test_no_decision_persists_trace(self, repositories, db):
        """Provider declines with no executed steps — trace still persists."""
        env = await _build_environment_with_observability(repositories, db)
        await _create_skill(env)
        env["queue"].append(None)

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "no_decision"

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].status == "failed"
        assert traces[0].error_kind == "no_decision"
        assert traces[0].steps == []

    async def test_invalid_decision_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        await _create_skill(env)
        env["queue"].append({})

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "invalid_decision"

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].error_kind == "invalid_decision"

    async def test_capability_unavailable_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        env["agent"].llm_provider = DeterministicLlmProvider()  # unarmed

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED
        assert result.error_kind == "agent_capability_unavailable"

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].error_kind == "agent_capability_unavailable"


class TestTraceDuration:
    """Verify started_at and completed_at are populated and ordered."""

    async def test_timestamps_present_and_ordered(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        before = datetime.now(timezone.utc)
        await env["agent"].run(env["context"], env["principal"], "goal", env["authorization"])
        after = datetime.now(timezone.utc)

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        trace = traces[0]

        assert trace.started_at is not None
        assert trace.completed_at is not None
        assert trace.started_at >= before
        assert trace.completed_at <= after
        assert trace.completed_at >= trace.started_at

    async def test_timestamps_present_on_failure(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        bad = await _create_skill(env, allowed_tools=["check_service_health", "ghost_tool"])
        env["queue"].append(_decision(bad.id, "ghost_tool"))

        await env["agent"].run(env["context"], env["principal"], "goal", env["authorization"])

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        trace = traces[0]
        assert trace.started_at is not None
        assert trace.completed_at is not None
        assert trace.completed_at >= trace.started_at


class TestTraceMetadata:
    """Verify trace captures the full TRD §19 metadata."""

    async def test_trace_captures_tenant_principal_goal_steps(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        await env["agent"].run(
            env["context"], env["principal"], "check the payment service", env["authorization"]
        )

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        trace = traces[0]
        assert trace.tenant_id == env["tenant"].id
        assert trace.principal_id == env["principal"].user_id
        assert trace.goal == "check the payment service"
        assert len(trace.steps) == 1
        assert trace.steps[0].skill_id == skill.id
        assert trace.steps[0].skill_name == skill.name


class TestBestEffortPersistence:
    """Trace persistence failures must never fail the business response."""

    async def test_persistence_failure_does_not_fail_business_response(self, repositories, db):
        env = await _build_environment(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        # Inject a broken observability service that always raises
        broken_obs = AsyncMock()
        broken_obs.record_agent_run = AsyncMock(side_effect=RuntimeError("db down"))
        env["agent"].observability_service = broken_obs

        # Business response must still succeed
        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        # The persistence was attempted
        broken_obs.record_agent_run.assert_called_once()


class TestNoDuplicatePersistence:
    """Controller-mediated execution must produce exactly one trace record."""

    async def test_single_persistence_per_run(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        # No duplicate: the controller no longer persists
        assert traces[0].id == result.id


class TestServiceIndependence:
    """Trace persists when invoking the service directly (no controller)."""

    async def test_service_direct_invocation_persists_trace(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        # Direct service call — no API controller involved
        result = await env["agent"].run(
            env["context"], env["principal"], "goal", env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        # Trace still persisted by the service
        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].id == result.id


class TestAgentGoalPiiSanitization:
    """V2-ADR-025: PII in agent goals must be sanitized before persistence.

    The user-supplied goal flows through:
      request → agent.run() → AgentExecutionResult → _persist_trace → AgentRunRecord
    PII must not survive into the persisted trace.

    Default PiiGuardService detects: PERSON, EMAIL_ADDRESS, PHONE_NUMBER,
    CREDIT_CARD, IBAN_CODE, IP_ADDRESS.  US_SSN requires explicit config
    (see Issue #167 / PR #173).
    """

    async def test_email_in_goal_sanitized_before_persistence(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        goal_with_email = "Send report to john@example.com"
        result = await env["agent"].run(
            env["context"], env["principal"], goal_with_email, env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert "john@example.com" not in traces[0].goal

    async def test_phone_in_goal_sanitized_before_persistence(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        goal_with_phone = "Call 555-123-4567 about the incident"
        result = await env["agent"].run(
            env["context"], env["principal"], goal_with_phone, env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert "555-123-4567" not in traces[0].goal

    async def test_multiple_pii_types_in_goal_sanitized(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        goal_multi_pii = "Contact alice@corp.com or 555-987-6543 about the server"
        result = await env["agent"].run(
            env["context"], env["principal"], goal_multi_pii, env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert "alice@corp.com" not in traces[0].goal
        assert "555-987-6543" not in traces[0].goal

    async def test_non_pii_goal_unchanged(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        clean_goal = "Check the production deployment status"
        result = await env["agent"].run(
            env["context"], env["principal"], clean_goal, env["authorization"]
        )
        assert result.status is AgentRunStatus.SUCCEEDED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert traces[0].goal == clean_goal

    async def test_pii_sanitization_does_not_break_agent_execution(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        skill = await _create_skill(env)
        env["queue"].extend([_decision(skill.id), None])

        goal_with_pii = "Process user john@example.com for the audit"
        result = await env["agent"].run(
            env["context"], env["principal"], goal_with_pii, env["authorization"]
        )
        # Agent execution must complete successfully despite PII in goal
        assert result.status is AgentRunStatus.SUCCEEDED
        assert len(result.steps) == 1

    async def test_failed_agent_still_sanitizes_goal(self, repositories, db):
        env = await _build_environment_with_observability(repositories, db)
        bad = await _create_skill(env, allowed_tools=["check_service_health", "ghost_tool"])
        env["queue"].extend([_decision(bad.id, "ghost_tool")])

        goal_with_pii = "Fix user john@example.com in the broken system"
        result = await env["agent"].run(
            env["context"], env["principal"], goal_with_pii, env["authorization"]
        )
        assert result.status is AgentRunStatus.FAILED

        traces = await env["observability_service"].list_agent_run_traces(env["tenant"].id, hours=1)
        assert len(traces) == 1
        assert "john@example.com" not in traces[0].goal

    async def test_custom_pii_guard_includes_ssn(self, repositories, db):
        """Verify PiiGuardService can be injected with custom config."""
        from collections import deque as _dq

        custom_guard = PiiGuardService(
            config=PiiGuardConfig(enabled_categories={"US_SSN", "EMAIL_ADDRESS"})
        )
        tenant_repo, _, _ = repositories
        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="PII Tenant"))
        observability_repo = PostgreSQLObservabilityRepository(db)
        observability_svc = ObservabilityService(repository=observability_repo)
        skill_repo = PostgreSQLSkillRepository(db)
        skill_svc = SkillService(skill_repo)
        record_repo = PostgreSQLToolExecutionRepository(db)
        tool_svc = ToolExecutionService(
            ToolRegistry({"check_service_health": SERVICE_HEALTH_TOOL}), record_repo
        )
        engine = SkillExecutionService(skill_service=skill_svc, tool_service=tool_svc)

        skill = await skill_svc.create_skill(
            _context(tenant.id),
            Skill(
                id=_unique("skill"),
                tenant_id=tenant.id,
                name="pii_skill",
                purpose="Test",
                allowed_tools=["check_service_health"],
            ),
        )
        decisions = _dq([_decision(skill.id), None])
        agent = AgentExecutionService(
            skill_service=skill_svc,
            skill_execution_service=engine,
            llm_provider=DeterministicLlmProvider(
                skill_decision_script=lambda g, c: decisions.popleft() if decisions else None
            ),
            observability_service=observability_svc,
            pii_guard=custom_guard,
        )
        ctx = _context(tenant.id)

        result = await agent.run(ctx, _principal(), "SSN 111-22-3333", _authorization())
        assert result.status is AgentRunStatus.SUCCEEDED

        traces = await observability_svc.list_agent_run_traces(tenant.id, hours=1)
        assert len(traces) == 1
        assert "111-22-3333" not in traces[0].goal
