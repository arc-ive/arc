"""Agent HTTP API tests (tenant-scoped, agent:execute RBAC, bounded runs).

Covers POST /agent/runs: authentication, dedicated Agent RBAC, tenant
isolation, malformed-request rejection, structured success/controlled
failure responses, and proof that the model can never set the tenant
boundary or bypass Skill execution.
"""

import uuid

import pytest

from arc.api.controllers import app_context
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole
from arc.services.agent import AgentExecutionService
from arc.services.llm import DeterministicLlmProvider


def _unique(prefix: str) -> str:
    return f"agent-api-{prefix}-{uuid.uuid4().hex[:10]}"


def _run_body(**overrides) -> dict:
    values = {"tenant_id": "placeholder", "goal": "check the payment service"}
    values.update(overrides)
    return values


async def _seed_tenant(repositories, name="Agent API Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="agent-user")
    )


async def _seed_membership(repositories, user_id, tenant_id):
    _, _, membership_repo = repositories
    return await membership_repo.create(
        Membership(
            id=_unique("membership"), user_id=user_id, tenant_id=tenant_id, role=UserRole.MEMBER
        )
    )


def _run(client, tenant_id, token, body=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload = body if body is not None else _run_body(tenant_id=tenant_id)
    if isinstance(payload, dict):
        payload = {**payload, "tenant_id": tenant_id}
    return client.post("/agent/runs", headers=headers, json=payload)


async def _create_skill_via_api(client, tenant_id, token, **payload_overrides) -> str:
    response = client.post(
        f"/skills?tenant_id={tenant_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": _unique("skill"),
            "purpose": "Recover a degraded service",
            "allowed_tools": ["check_service_health", "echo_tool"],
            **payload_overrides,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _install_agent_service(provider):
    """Swap the application agent service for one with an armed provider."""
    previous = app_context.services._services.get("agent_service")
    app_context.services.register(
        "agent_service",
        AgentExecutionService(
            skill_service=app_context.skill_service,
            skill_execution_service=app_context.skill_execution_service,
            llm_provider=provider,
        ),
    )
    return previous


class TestAgentSecurity:
    async def test_unauthenticated_request_is_rejected_401(self, client, repositories):
        tenant = await _seed_tenant(repositories)
        response = _run(client, tenant.id, None)
        assert response.status_code == 401

    async def test_employee_can_execute_agent(
        self, client, repositories, make_token, authorization_override
    ):
        """EMPLOYEE holds agent:execute per V2-ADR-005; run proceeds."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = _run(client, tenant.id, token)

        # The default provider is unarmed: the capability gate fails the
        # run closed without executing anything, but the authorized caller
        # reaches it.
        assert response.status_code == 200

    async def test_agent_execute_permission_enforced_for_operations_user(
        self, client, repositories, make_token, authorization_override
    ):
        """OPERATIONS_USER holds agent:execute; run proceeds (fail-closed default)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = _run(client, tenant.id, token)

        # The default provider is unarmed: the capability gate fails the
        # run closed without executing anything, but the authorized caller
        # reaches it.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_kind"] == "agent_decision_unavailable"
        assert body["steps"] == []

    async def test_tenant_mismatch_is_rejected_403(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a = await _seed_tenant(repositories, name="Context Tenant")
        tenant_b = await _seed_tenant(repositories, name="Request Tenant")
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant_a.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})

        async def _foreign_context():
            return TenantContext(
                tenant_id=tenant_a.id,
                tenant_name="Context Tenant",
                user_id=user.id,
                role=UserRole.MEMBER,
            )

        app.dependency_overrides[get_trusted_tenant_context] = _foreign_context
        token = make_token(user.id)

        response = _run(client, tenant_b.id, token)

        assert response.status_code == 403


class TestAgentValidation:
    async def test_non_object_body_is_400(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            "/agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            json=["not", "an", "object"],
        )

        assert response.status_code == 400

    async def test_missing_goal_is_400(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = _run(client, tenant.id, token, {})

        assert response.status_code == 400

    @pytest.mark.parametrize("goal", ["", "   ", 42, None])
    async def test_invalid_goals_are_400(
        self, client, repositories, make_token, authorization_override, goal
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = _run(client, tenant.id, token, {"goal": goal})

        assert response.status_code == 400


class TestAgentRuns:
    async def _setup(
        self, client, repositories, make_token, authorization_override, **skill_overrides
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        skill_id = await _create_skill_via_api(client, tenant.id, token, **skill_overrides)
        return tenant, token, skill_id

    async def test_successful_run_returns_structured_response(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override
        )
        decisions = iter(
            [
                {
                    "skill_id": skill_id,
                    "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                    "satisfied_preconditions": [],
                },
                None,
            ]
        )
        previous = _install_agent_service(
            DeterministicLlmProvider(skill_decision_script=lambda goal, catalog: next(decisions))
        )
        try:
            response = _run(client, tenant.id, token)
        finally:
            if previous is None:
                app_context.services._services.pop("agent_service", None)
            else:
                app_context.services.register("agent_service", previous)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["error_kind"] is None
        assert body["tenant_id"] == tenant.id
        assert len(body["steps"]) == 1
        step = body["steps"][0]
        assert step["status"] == "succeeded"
        assert step["skill_id"] == skill_id
        # Agent steps deliberately do not re-expose raw tool output.
        assert set(step.keys()) == {
            "sequence",
            "skill_id",
            "skill_name",
            "status",
            "error_kind",
        }

    async def test_approval_required_run_returns_structured_state(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override, approval_required=True
        )
        decisions = iter(
            [
                {
                    "skill_id": skill_id,
                    "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                    "satisfied_preconditions": [],
                }
            ]
        )
        previous = _install_agent_service(
            DeterministicLlmProvider(skill_decision_script=lambda goal, catalog: next(decisions))
        )
        try:
            response = _run(client, tenant.id, token)
        finally:
            if previous is None:
                app_context.services._services.pop("agent_service", None)
            else:
                app_context.services.register("agent_service", previous)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approval_required"
        assert body["error_kind"] == "approval_required"
        assert body["steps"][-1]["status"] == "approval_required"

    async def test_model_cannot_set_the_tenant_boundary(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override
        )
        decisions = iter(
            [
                {
                    "skill_id": skill_id,
                    "tool_calls": [
                        {
                            "tool_name": "check_service_health",
                            "input": {"tenant_id": "tenant-B"},
                        }
                    ],
                    "satisfied_preconditions": [],
                },
                None,
            ]
        )
        previous = _install_agent_service(
            DeterministicLlmProvider(skill_decision_script=lambda goal, catalog: next(decisions))
        )
        try:
            response = _run(client, tenant.id, token)
        finally:
            if previous is None:
                app_context.services._services.pop("agent_service", None)
            else:
                app_context.services.register("agent_service", previous)

        assert response.status_code == 200
        body = response.json()
        # The tool schema (extra="forbid") rejects the injected tenant
        # argument: the run fails closed and the tenant boundary in the
        # result remains the authenticated one.
        assert body["status"] == "failed"
        assert body["tenant_id"] == tenant.id
        assert body["steps"][-1]["error_kind"] == "invalid_input"


class TestAgentResumeApprovalVerification:
    """Issue #206: agent resume gets the same approval verification."""

    async def _setup(
        self, client, repositories, make_token, authorization_override, **skill_overrides
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        skill_id = await _create_skill_via_api(client, tenant.id, token, **skill_overrides)
        return tenant, token, skill_id

    async def _approved_approval(self, db, tenant_id, user_id, tool_name="check_service_health"):
        from arc.domain.models import ApprovalStatus, TenantContext, UserRole
        from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
        from arc.services.approvals import HumanApprovalService
        from arc.services.tools import approval_arguments_digest

        # Own service instance over the test-loop pool: awaiting the
        # app-owned service here would bind to a different event loop.
        approval_service = HumanApprovalService(PostgreSQLApprovalRequestRepository(db))
        tool = app_context.services.get("tool_service").registry.get(tool_name)
        approval_id = await approval_service.record_required_approval(
            tenant_id=tenant_id,
            requester_user_id=user_id,
            tool_name=tool.name,
            tool_version=tool.version,
            risk_level="low",
            input_summary="test",
            arguments_digest=approval_arguments_digest(tool, {}),
        )
        await approval_service.decide_request(
            TenantContext(
                tenant_id=tenant_id,
                tenant_name="t",
                user_id=user_id,
                role=UserRole.MEMBER,
            ),
            "approver-1",
            approval_id,
            ApprovalStatus.APPROVED,
        )
        return approval_id

    def _resume(self, client, tenant_id, token, skill_id, approval_id):
        return client.post(
            "/agent/runs/resume",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "tenant_id": tenant_id,
                "approval_id": approval_id,
                "skill_id": skill_id,
                "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                "resume_from_step": 0,
                "previous_steps": [],
                "satisfied_preconditions": [],
            },
        )

    async def test_fabricated_approval_refused(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override, approval_required=True
        )

        response = self._resume(client, tenant.id, token, skill_id, "fabricated-nope")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_kind"] == "invalid_approval"

    async def test_cross_tenant_approval_refused(
        self, client, repositories, db, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override, approval_required=True
        )
        other = await _seed_tenant(repositories, name="Other Tenant")
        approval_id = await self._approved_approval(db, other.id, "user-1")

        response = self._resume(client, tenant.id, token, skill_id, approval_id)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_kind"] == "invalid_approval"

    async def test_valid_approval_succeeds_then_replay_refused(
        self, client, repositories, db, make_token, authorization_override
    ):
        tenant, token, skill_id = await self._setup(
            client, repositories, make_token, authorization_override, approval_required=True
        )
        approval_id = await self._approved_approval(db, tenant.id, "user-1")

        first = self._resume(client, tenant.id, token, skill_id, approval_id)
        assert first.status_code == 200
        assert first.json()["status"] == "succeeded"

        replay = self._resume(client, tenant.id, token, skill_id, approval_id)
        assert replay.status_code == 200
        assert replay.json()["status"] == "failed"
        assert replay.json()["error_kind"] == "invalid_approval"
