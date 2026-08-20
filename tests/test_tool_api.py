"""AI Tools HTTP API tests (tenant-scoped, X-11 RBAC, PRD 15 / TRD 14).

Endpoints under test:

- GET  /tenants/{tenant_id}/tools              (requires ``tool:read``)
- POST /tenants/{tenant_id}/tools/{name}/execute (requires ``tool:execute``)

The client-supplied ``tenant_id`` is request input only: the X-10 trusted
tenant context verifies the authenticated principal's persisted
membership, and the tool service derives tenant ownership exclusively
from that context. The path ``tenant_id`` is explicitly validated against
the trusted context (403 on mismatch).
"""

import uuid

import pytest

from arc.domain.models import (
    Membership,
    Tenant,
    ToolExecutionStatus,
    User,
    UserRole,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-api-{prefix}-{uuid.uuid4().hex[:10]}"


async def _seed_tenant(repositories, name="Tools Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="tools-user")
    )


async def _seed_membership(repositories, user_id, tenant_id):
    _, _, membership_repo = repositories
    return await membership_repo.create(
        Membership(
            id=_unique("membership"), user_id=user_id, tenant_id=tenant_id, role=UserRole.MEMBER
        )
    )


async def _seed_member(repositories):
    tenant = await _seed_tenant(repositories)
    user = await _seed_user(repositories)
    await _seed_membership(repositories, user.id, tenant.id)
    return tenant, user


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestToolCatalog:
    """GET /tenants/{tenant_id}/tools (tool:read)."""

    @pytest.mark.parametrize(
        "role",
        [
            ApplicationRole.PLATFORM_ADMINISTRATOR,
            ApplicationRole.COMPANY_ADMINISTRATOR,
            ApplicationRole.OPERATIONS_USER,
        ],
    )
    async def test_authorized_roles_can_list_tools(
        self, client, repositories, make_token, authorization_override, role
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: role})
        token = make_token(user.id)

        response = client.get(f"/tenants/{tenant.id}/tools", headers=_auth_headers(token))

        assert response.status_code == 200
        tools = response.json()
        assert [tool["name"] for tool in tools] == ["check_service_health"]
        tool = tools[0]
        assert tool["version"] == "1"
        assert tool["description"]
        assert tool["risk_level"] == "low"
        assert tool["required_permission"] == "tool:execute"
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["properties"] == {}
        assert tool["input_schema"]["additionalProperties"] is False
        assert "handler" not in tool

    async def test_catalog_does_not_expose_handlers(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.get(f"/tenants/{tenant.id}/tools", headers=_auth_headers(token))

        assert response.status_code == 200
        assert all("handler" not in tool for tool in response.json())

    async def test_employee_cannot_list_tools(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.get(f"/tenants/{tenant.id}/tools", headers=_auth_headers(token))

        assert response.status_code == 403

    async def test_unauthenticated_catalog_requests_are_rejected(
        self, client, repositories, wrong_secret_token
    ):
        tenant, _ = await _seed_member(repositories)

        assert client.get(f"/tenants/{tenant.id}/tools").status_code == 401
        assert (
            client.get(
                f"/tenants/{tenant.id}/tools",
                headers=_auth_headers("not-a-jwt"),
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"/tenants/{tenant.id}/tools",
                headers=_auth_headers(wrong_secret_token("user")),
            ).status_code
            == 401
        )

    async def test_catalog_path_tenant_mismatch_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        other_tenant = await _seed_tenant(repositories, name="Other Tenant")
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.get(f"/tenants/{other_tenant.id}/tools", headers=_auth_headers(token))

        assert response.status_code == 403


class TestToolExecution:
    """POST /tenants/{tenant_id}/tools/{name}/execute (tool:execute)."""

    @pytest.mark.parametrize(
        "role",
        [
            ApplicationRole.PLATFORM_ADMINISTRATOR,
            ApplicationRole.COMPANY_ADMINISTRATOR,
            ApplicationRole.OPERATIONS_USER,
        ],
    )
    async def test_authorized_roles_can_execute_tools(
        self, client, repositories, make_token, authorization_override, role
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: role})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["tool"] == "check_service_health"
        assert body["version"] == "1"
        assert body["output"]["tenant_id"] == tenant.id
        assert {entry["status"] for entry in body["output"]["services"]} == {"healthy"}

    async def test_check_service_health_is_deterministic(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        headers = _auth_headers(token)

        first = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=headers,
            json={"input": {}},
        )
        second = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=headers,
            json={"input": {}},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["output"] == second.json()["output"]

    async def test_successful_execution_persists_success_record(
        self, client, db, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )
        assert response.status_code == 200

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.SUCCESS
        assert records[0].tool_name == "check_service_health"
        assert records[0].error_kind is None

    async def test_invalid_input_rejected_with_controlled_error(
        self, client, db, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {"extra": 1}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid tool input"
        assert "Traceback" not in response.text

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.FAILED
        assert records[0].error_kind == "invalid_input"

    async def test_malformed_request_body_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        headers = {**_auth_headers(token), "Content-Type": "application/json"}
        url = f"/tenants/{tenant.id}/tools/check_service_health/execute"

        list_body = client.post(url, headers=headers, json=[1, 2, 3])
        malformed_json = client.post(url, headers=headers, content="not-json")

        assert list_body.status_code == 422
        assert malformed_json.status_code == 422
        assert "Traceback" not in malformed_json.text

    async def test_unknown_tool_fails_closed(
        self, client, db, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/restart_service/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Tool not found"
        assert "Traceback" not in response.text

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.FAILED
        assert records[0].error_kind == "unknown_tool"

    async def test_employee_cannot_execute_tools(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )

        assert response.status_code == 403

    async def test_unauthenticated_execution_rejected(
        self, client, repositories, wrong_secret_token
    ):
        tenant, _ = await _seed_member(repositories)
        url = f"/tenants/{tenant.id}/tools/check_service_health/execute"

        assert client.post(url, json={"input": {}}).status_code == 401
        assert (
            client.post(url, headers=_auth_headers("not-a-jwt"), json={"input": {}}).status_code
            == 401
        )
        assert (
            client.post(
                url,
                headers=_auth_headers(wrong_secret_token("user")),
                json={"input": {}},
            ).status_code
            == 401
        )

    async def test_execution_path_tenant_mismatch_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        other_tenant = await _seed_tenant(repositories, name="Other Tenant")
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{other_tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )

        assert response.status_code == 403

    async def test_execution_records_cannot_cross_tenant_boundaries(
        self, client, db, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        other_tenant = await _seed_tenant(repositories, name="Other Tenant")
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"input": {}},
        )
        assert response.status_code == 200

        repo = PostgreSQLToolExecutionRepository(db)
        tenant_records = await repo.list_for_tenant(tenant.id)
        other_records = await repo.list_for_tenant(other_tenant.id)
        assert len(tenant_records) == 1
        assert other_records == []
        assert all(record.tenant_id == tenant.id for record in tenant_records)

    async def test_safe_error_responses_contain_no_internal_details(
        self, client, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        responses = [
            client.post(
                f"/tenants/{tenant.id}/tools/does_not_exist/execute",
                headers=_auth_headers(token),
                json={"input": {}},
            ),
            client.post(
                f"/tenants/{tenant.id}/tools/check_service_health/execute",
                headers=_auth_headers(token),
                json={"input": {"x": 1}},
            ),
            client.get(f"/tenants/{tenant.id}/tools", headers=_auth_headers("bad")),
        ]

        for response in responses:
            assert "Traceback" not in response.text
            assert 'File "' not in response.text
            assert "arc.services" not in response.text
            assert "secret" not in response.text.lower()
