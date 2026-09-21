"""AI Tools HTTP API tests (tenant-scoped, X-11 RBAC, PRD 15 / TRD 14).

Endpoints under test:

- GET  /tenants/{tenant_id}/tools              (requires ``tool:read``)
- POST /tenants/{tenant_id}/tools/{name}/execute (requires ``tool:execute``)

The client-supplied ``tenant_id`` is request input only: the X-10 trusted
tenant context verifies the authenticated principal's persisted
membership, and the tool service derives tenant ownership exclusively
from that context. The path ``tenant_id`` is explicitly validated against
the trusted context (403 on mismatch). Per-tool authorization requires
``tool:execute`` AND every permission declared by the tool (403
otherwise, audited). The catalog is platform-owned and read-only: no
registration, modification, or upload surface exists.
"""

import uuid
from dataclasses import replace

import pytest

from arc.api.controllers import get_tool_service
from arc.app import app as arc_app
from arc.domain.models import (
    Membership,
    Tenant,
    ToolAuthorizationOutcome,
    ToolExecutionStatus,
    User,
    UserRole,
)
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import TENANT_CREATE, TOOL_EXECUTE
from arc.security.models import ApplicationRole
from arc.services.tools import (
    SERVICE_HEALTH_TOOL,
    ToolExecutionService,
    ToolRegistry,
)


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
        tools = response.json()["items"]
        assert [tool["name"] for tool in tools] == ["check_service_health"]
        tool = tools[0]
        assert tool["version"] == "1"
        assert tool["description"]
        assert tool["risk_level"] == "low"
        assert tool["required_permissions"] == ["tool:execute"]
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
        assert all("handler" not in tool for tool in response.json()["items"])

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

    async def test_catalog_requires_membership_fail_closed(
        self, client, repositories, make_token, authorization_override
    ):
        """A user with tool:read but NO membership in the tenant is denied
        (missing trusted tenant context fails closed)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.get(f"/tenants/{tenant.id}/tools", headers=_auth_headers(token))

        assert response.status_code == 403

    async def test_catalog_is_platform_owned_and_read_only(
        self, client, repositories, make_token, authorization_override
    ):
        """The catalog exposes NO registration/mutation surface: tenants
        cannot register, upload, modify, or delete tools."""
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        headers = _auth_headers(token)
        catalog_url = f"/tenants/{tenant.id}/tools"
        tool_url = f"{catalog_url}/check_service_health"

        assert client.get(catalog_url, headers=headers).status_code == 200
        assert client.post(catalog_url, headers=headers, json={}).status_code == 405
        assert client.delete(catalog_url, headers=headers).status_code == 405
        for method in (client.post, client.put, client.patch):
            assert method(tool_url, headers=headers, json={}).status_code == 404
        assert client.delete(tool_url, headers=headers).status_code == 404

    async def test_no_registration_endpoint_exists_in_app_routes(self, client):
        """Security guard: no tool registration/upload/management route
        exists anywhere in the application."""
        registration_paths = [
            "/tenants/{tenant_id}/tools/register",
            "/tools/register",
            "/tenants/{tenant_id}/tools/upload",
            "/tenants/{tenant_id}/tools/{name}",
        ]
        app_routes = {getattr(route, "path", None) for route in client.app.routes}
        for path in registration_paths:
            assert path not in app_routes, f"unexpected tool management route: {path}"


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

    async def test_unknown_envelope_field_is_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        """Issue #236: a wrong key must fail, not silently execute empty."""
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
            headers=_auth_headers(token),
            json={"parameters": "notanobject"},
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail
        assert "loc" in detail[0]

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

    async def test_audit_record_identifies_who_and_authorization_decision(
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
        assert records[0].user_id == user.id
        assert records[0].authorization_outcome == ToolAuthorizationOutcome.GRANTED

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

    async def test_execution_requires_membership_fail_closed(
        self, client, repositories, make_token, authorization_override
    ):
        """A user with tool:execute but NO membership in the tenant is
        denied (missing trusted tenant context fails closed, 403)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/tools/check_service_health/execute",
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

    async def test_tenant_mismatch_causes_no_execution_and_no_records(
        self, client, db, repositories, make_token, authorization_override
    ):
        """A path/context mismatch is refused BEFORE any execution and
        produces NO audit records in either tenant (no side effects)."""
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

        repo = PostgreSQLToolExecutionRepository(db)
        assert await repo.list_for_tenant(tenant.id) == []
        assert await repo.list_for_tenant(other_tenant.id) == []

    async def test_user_without_tool_execute_never_invokes_service_or_handler(
        self, client, db, repositories, make_token, authorization_override
    ):
        """Audit ownership boundary: a caller WITHOUT tool:execute is
        refused by the central RBAC dependency (403) BEFORE the tool
        service runs; no handler executes and no tool_execution_records
        row is written. Central security failures are owned by the
        central security/audit boundary, not by ToolExecutionService."""
        calls = []

        def spy(input_data, tenant_id):
            calls.append((input_data, tenant_id))
            return {"tenant_id": tenant_id, "services": []}

        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        spy_service = ToolExecutionService(
            ToolRegistry({SERVICE_HEALTH_TOOL.name: replace(SERVICE_HEALTH_TOOL, handler=spy)}),
            PostgreSQLToolExecutionRepository(arc_app.db),
        )
        app = client.app
        app.dependency_overrides[get_tool_service] = lambda: spy_service
        try:
            response = client.post(
                f"/tenants/{tenant.id}/tools/check_service_health/execute",
                headers=_auth_headers(token),
                json={"input": {}},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403
        assert calls == []

        repo = PostgreSQLToolExecutionRepository(db)
        assert await repo.list_for_tenant(tenant.id) == []

    async def test_handler_crash_leaks_nothing_to_audit_or_response(
        self, client, db, repositories, make_token, authorization_override
    ):
        """Error safety: a handler exception carrying sensitive material
        never reaches the API response or the audit record; error_kind
        stays a safe classification and the raw message is never stored."""
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        def boom(input_data, tenant_id):
            raise RuntimeError("Authorization token is SUPER_SECRET-9f8e7d6c5b")

        crashing_service = ToolExecutionService(
            ToolRegistry({SERVICE_HEALTH_TOOL.name: replace(SERVICE_HEALTH_TOOL, handler=boom)}),
            PostgreSQLToolExecutionRepository(arc_app.db),
        )
        app = client.app
        app.dependency_overrides[get_tool_service] = lambda: crashing_service
        try:
            response = client.post(
                f"/tenants/{tenant.id}/tools/check_service_health/execute",
                headers=_auth_headers(token),
                json={"input": {}},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 500
        assert response.json()["detail"] == "Tool execution failed"
        assert "SUPER_SECRET-9f8e7d6c5b" not in response.text
        assert "Traceback" not in response.text

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.FAILED
        assert records[0].error_kind == "execution_error"
        assert "SUPER_SECRET-9f8e7d6c5b" not in records[0].input_summary
        assert "SUPER_SECRET-9f8e7d6c5b" not in (records[0].output_summary or "")
        assert "SUPER_SECRET-9f8e7d6c5b" not in (records[0].error_kind or "")

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


class TestPerToolAuthorization:
    """Execution requires tool:execute AND every tool-declared permission."""

    async def test_user_with_tool_execute_but_missing_tool_permission_is_denied(
        self, client, db, repositories, make_token, authorization_override
    ):
        """tool:execute is not a universal master key: a caller holding it
        but missing the tool-declared permission is refused (403) and the
        denial is audited."""
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        elevated_tool = replace(
            SERVICE_HEALTH_TOOL,
            name="provisioning_tool",
            required_permissions=frozenset({TOOL_EXECUTE, TENANT_CREATE}),
        )
        custom_service = ToolExecutionService(
            ToolRegistry({elevated_tool.name: elevated_tool}),
            PostgreSQLToolExecutionRepository(arc_app.db),
        )
        app = client.app
        app.dependency_overrides[get_tool_service] = lambda: custom_service
        try:
            response = client.post(
                f"/tenants/{tenant.id}/tools/provisioning_tool/execute",
                headers=_auth_headers(token),
                json={"input": {}},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403
        assert response.json()["detail"] == "Tool execution is not permitted"

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.FAILED
        assert records[0].authorization_outcome == ToolAuthorizationOutcome.DENIED
        assert records[0].error_kind == "authorization_denied"
        assert records[0].user_id == user.id

    async def test_user_with_all_required_permissions_can_execute(
        self, client, db, repositories, make_token, authorization_override
    ):
        tenant, user = await _seed_member(repositories)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        elevated_tool = replace(
            SERVICE_HEALTH_TOOL,
            name="provisioning_tool",
            required_permissions=frozenset({TOOL_EXECUTE, TENANT_CREATE}),
        )
        custom_service = ToolExecutionService(
            ToolRegistry({elevated_tool.name: elevated_tool}),
            PostgreSQLToolExecutionRepository(arc_app.db),
        )
        app = client.app
        app.dependency_overrides[get_tool_service] = lambda: custom_service
        try:
            response = client.post(
                f"/tenants/{tenant.id}/tools/provisioning_tool/execute",
                headers=_auth_headers(token),
                json={"input": {}},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200

        repo = PostgreSQLToolExecutionRepository(db)
        records = await repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status == ToolExecutionStatus.SUCCESS
        assert records[0].authorization_outcome == ToolAuthorizationOutcome.GRANTED
