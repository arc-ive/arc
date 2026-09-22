"""Skill execution HTTP API tests (tenant-scoped, X-11 RBAC).

Covers the Skills Engine execution endpoint:

- POST /tenants/{tenant_id}/skills/{skill_id}/execute   (requires ``skill:execute``)

Every executed tool call is delegated to ``ToolExecutionService`` behind
the scenes; these tests pin the HTTP contract: authentication, RBAC,
tenant isolation, validation errors, structured success/controlled-failure
responses.
"""

import uuid

import pytest

from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"skill-exec-api-{prefix}-{uuid.uuid4().hex[:10]}"


def _skill_payload(**overrides) -> dict:
    """Return a valid Skill creation payload with overridable fields."""
    values = {
        "name": _unique("skill"),
        "purpose": "Recover a degraded service",
        "allowed_tools": ["check_service_health"],
    }
    values.update(overrides)
    return values


def _execute_body(**overrides) -> dict:
    """Return a valid execution request body with overridable fields."""
    values = {
        "satisfied_preconditions": [],
        "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
    }
    values.update(overrides)
    return values


async def _seed_tenant(repositories, name="Skill Execution Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="skills-user")
    )


async def _seed_membership(repositories, user_id, tenant_id):
    _, _, membership_repo = repositories
    return await membership_repo.create(
        Membership(
            id=_unique("membership"), user_id=user_id, tenant_id=tenant_id, role=UserRole.MEMBER
        )
    )


def _execute(client, tenant_id, token, skill_id, body=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        f"/tenants/{tenant_id}/skills/{skill_id}/execute",
        headers=headers,
        json=body if body is not None else _execute_body(),
    )


async def _create_skill_via_api(client, tenant_id, token, **payload_overrides) -> str:
    response = client.post(
        f"/tenants/{tenant_id}/skills",
        headers={"Authorization": f"Bearer {token}"},
        json=_skill_payload(**payload_overrides),
    )
    assert response.status_code == 200
    return response.json()["id"]


class TestSkillExecutionSecurity:
    """Authentication and RBAC boundary of the execution endpoint."""

    async def test_unauthenticated_request_is_rejected_401(self, client, repositories):
        tenant = await _seed_tenant(repositories)
        response = _execute(client, tenant.id, None, "any-skill")
        assert response.status_code == 401

    async def test_role_without_skill_execute_is_rejected_403(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = _execute(client, tenant.id, token, "any-skill")

        assert response.status_code == 403

    async def test_operations_user_can_execute(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        skill_id = await _create_skill_via_api(client, tenant.id, token)
        response = _execute(client, tenant.id, token, skill_id)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "succeeded"
        assert body["error_kind"] is None
        assert body["tenant_id"] == tenant.id
        assert body["principal_id"] == user.id
        assert len(body["steps"]) == 1
        step = body["steps"][0]
        assert step["status"] == "success"
        assert step["tool_name"] == "check_service_health"
        assert step["output"]["tenant_id"] == tenant.id


class TestSkillExecutionTenantIsolation:
    """Cross-tenant execution is impossible; mismatched input fails closed."""

    async def test_cross_tenant_skill_execution_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a = await _seed_tenant(repositories, name="Tenant A")
        tenant_b = await _seed_tenant(repositories, name="Tenant B")
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant_a.id)
        await _seed_membership(repositories, user.id, tenant_b.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        # Skill belongs to tenant A...
        skill_id = await _create_skill_via_api(client, tenant_a.id, token)
        # ...execution through tenant B cannot resolve it (404, no leakage).
        response = _execute(client, tenant_b.id, token, skill_id)
        assert response.status_code == 404

        # And executing through the owning tenant works normally.
        ok = _execute(client, tenant_a.id, token, skill_id)
        assert ok.status_code == 200
        assert ok.json()["status"] == "succeeded"

    async def test_mismatched_query_tenant_is_rejected_403(
        self, client, repositories, make_token, authorization_override
    ):
        """Defense in depth: divergent trusted context vs request tenant."""
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

        response = _execute(client, tenant_b.id, token, "any-skill")

        assert response.status_code == 403


class TestSkillExecutionOutcomes:
    """Structured controlled outcomes over HTTP."""

    async def _setup(self, client, repositories, make_token, authorization_override):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        return tenant, token

    async def test_unmet_precondition_returns_structured_status(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(
            client, tenant.id, token, preconditions=["service_health_degraded"]
        )

        response = _execute(client, tenant.id, token, skill_id)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "precondition_failed"
        assert body["error_kind"] == "precondition_failed"
        assert body["steps"] == []

    async def test_approval_required_skill_returns_structured_state(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(client, tenant.id, token, approval_required=True)

        response = _execute(client, tenant.id, token, skill_id)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approval_required"
        assert body["steps"] == []

    async def test_disallowed_tool_returns_denied_outcome(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(client, tenant.id, token)

        response = _execute(
            client,
            tenant.id,
            token,
            skill_id,
            _execute_body(tool_calls=[{"tool_name": "restart_service", "input": {}}]),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "denied"
        assert body["steps"][-1]["error_kind"] == "disallowed_tool"

    async def test_unknown_skill_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        response = _execute(client, tenant.id, token, "missing-skill-id")
        assert response.status_code == 404


class TestSkillExecutionValidation:
    """Malformed requests are rejected with 400 and never executed."""

    async def _setup(self, client, repositories, make_token, authorization_override):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        return tenant, make_token(user.id)

    async def test_missing_tool_calls_is_400(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(client, tenant.id, token)

        response = _execute(client, tenant.id, token, skill_id, {})

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "payload",
        [
            {"tool_calls": []},
            {"tool_calls": "not-a-list"},
            {"tool_calls": [{"input": {}}]},
            {"tool_calls": [{"tool_name": "check_service_health", "input": "bad"}]},
            {
                "tool_calls": [{"tool_name": "check_service_health"}],
                "satisfied_preconditions": [42],
            },
        ],
    )
    async def test_malformed_bodies_are_400(
        self, client, repositories, make_token, authorization_override, payload
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(client, tenant.id, token)

        response = _execute(client, tenant.id, token, skill_id, payload)

        assert response.status_code == 400

    async def test_non_object_body_is_422(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, token = await self._setup(client, repositories, make_token, authorization_override)
        skill_id = await _create_skill_via_api(client, tenant.id, token)

        response = client.post(
            f"/tenants/{tenant.id}/skills/{skill_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json=["not", "an", "object"],
        )

        assert response.status_code == 422


class TestSkillInputsApi:
    """Issue #241: declared inputs supplied through the API reach execution."""

    async def test_declared_inputs_accepted(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        skill_id = await _create_skill_via_api(
            client, tenant.id, token, inputs=["incident_description"]
        )

        response = client.post(
            f"/tenants/{tenant.id}/skills/{skill_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                "satisfied_preconditions": [],
                "skill_inputs": {"incident_description": "outage"},
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "succeeded"

    async def test_missing_declared_inputs_refused(
        self, client, repositories, make_token, authorization_override
    ):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        skill_id = await _create_skill_via_api(
            client, tenant.id, token, inputs=["incident_description"]
        )

        response = client.post(
            f"/tenants/{tenant.id}/skills/{skill_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                "satisfied_preconditions": [],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_kind"] == "invalid_skill_inputs"


class TestSkillResumeApprovalVerification:
    """Issue #206: resume verifies the approval instead of trusting the ID."""

    async def _setup(self, client, repositories, make_token, authorization_override):
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        skill_id = await _create_skill_via_api(client, tenant.id, token, approval_required=True)
        return tenant, token, skill_id

    async def _approved_approval(self, db, tenant_id, user_id, tool_name="check_service_health"):
        from arc.api.controllers import app_context
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
            f"/tenants/{tenant_id}/skills/{skill_id}/resume",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "approval_id": approval_id,
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
            client, repositories, make_token, authorization_override
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
            client, repositories, make_token, authorization_override
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
            client, repositories, make_token, authorization_override
        )
        approval_id = await self._approved_approval(db, tenant.id, "user-1")

        first = self._resume(client, tenant.id, token, skill_id, approval_id)
        assert first.status_code == 200
        assert first.json()["status"] == "succeeded"

        replay = self._resume(client, tenant.id, token, skill_id, approval_id)
        assert replay.status_code == 200
        assert replay.json()["status"] == "failed"
        assert replay.json()["error_kind"] == "invalid_approval"
