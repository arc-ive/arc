"""API-level tests for the Observability foundation slice.

Covers authentication (401), centralized RBAC (403 matrix), trusted
tenant context + path-consistency (403), cross-tenant isolation,
strictly tenant-agnostic platform summaries, sensitive-material
absence, correlation-ID propagation on success AND handled errors,
success-gated tenant attribution, best-effort telemetry under storage
failure, and the protected component-health surface.
"""

import uuid

import pytest

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.security.models import ApplicationRole
from arc.services.llm import LlmConfigurationError


async def _fresh_db():
    """Standalone connection for direct SQL assertions.

    Avoids stacking a second async fixture behind the sync ``client``
    fixture (pytest-asyncio event-loop quirk).
    """
    import os

    from arc.db.connection import ArcDatabase

    database = ArcDatabase(
        os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc")
    )
    await database.connect()
    return database


def _authed_get(http_client, url, token):
    """GET with a bearer Authorization header (keeps assertions one-line)."""
    return http_client.get(url, headers={"Authorization": f"Bearer {token}"})


def _summary_url(tenant_id):
    return f"/tenants/{tenant_id}/observability/usage-summary"


@pytest.fixture
async def two_tenants(db):
    """Two fully provisioned tenants/users for isolation assertions."""
    tenants = PostgreSQLTenantRepository(db)
    users = PostgreSQLUserRepository(db)
    memberships = PostgreSQLMembershipRepository(db)

    created = []
    for label in ("A", "B"):
        tenant = await tenants.create(
            Tenant(id=f"obsapi-{label}-{uuid.uuid4().hex[:8]}", name=label)
        )
        user = await users.create(
            User(
                id=f"obsapi-u-{label}-{uuid.uuid4().hex[:8]}",
                email=f"{uuid.uuid4().hex}@example.com",
                username="obs",
            )
        )
        await memberships.create(
            Membership(
                id=f"obsapi-m-{uuid.uuid4().hex[:10]}",
                user_id=user.id,
                tenant_id=tenant.id,
                role=UserRole.MEMBER,
            )
        )
        created.append((tenant, user))
    yield created
    for tenant, user in created:
        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM memberships WHERE tenant_id = $1", tenant.id)
            await conn.execute("DELETE FROM users WHERE id = $1", user.id)
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant.id)


class TestAuthenticationAndRbac:
    async def test_tenant_summary_requires_authentication(self, client, two_tenants):
        tenant, _ = two_tenants[0]
        response = client.get(_summary_url(tenant.id))
        assert response.status_code == 401

    async def test_platform_surfaces_require_authentication(self, client):
        assert client.get("/platform/observability/summary").status_code == 401
        assert client.get("/observability/health").status_code == 401

    async def test_employee_denied_tenant_and_platform(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        assert _authed_get(client, _summary_url(tenant.id), token).status_code == 403
        assert _authed_get(client, "/platform/observability/summary", token).status_code == 403
        assert _authed_get(client, "/observability/health", token).status_code == 403

    async def test_unassigned_user_denied_everywhere(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({})
        token = make_token(user.id)
        assert _authed_get(client, _summary_url(tenant.id), token).status_code == 403
        assert _authed_get(client, "/platform/observability/summary", token).status_code == 403

    async def test_operations_user_allowed_tenant_summary_but_not_platform(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        assert _authed_get(client, _summary_url(tenant.id), token).status_code == 200
        assert _authed_get(client, "/platform/observability/summary", token).status_code == 403

    async def test_company_administrator_allowed_tenant_summary_but_not_platform(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        assert _authed_get(client, _summary_url(tenant.id), token).status_code == 200
        assert _authed_get(client, "/platform/observability/summary", token).status_code == 403

    async def test_platform_administrator_allowed_everywhere(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        assert _authed_get(client, _summary_url(tenant.id), token).status_code == 200
        assert _authed_get(client, "/platform/observability/summary", token).status_code == 200
        assert _authed_get(client, "/observability/health", token).status_code == 200


class TestTenantBoundary:
    async def test_path_tenant_mismatch_denied_403(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant_a, user_a = two_tenants[0]
        tenant_b, _ = two_tenants[1]
        authorization_override({user_a.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user_a.id)
        assert _authed_get(client, _summary_url(tenant_b.id), token).status_code == 403

    async def test_cross_tenant_aggregates_never_leak(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant_a, user_a = two_tenants[0]
        tenant_b, _ = two_tenants[1]
        # Give ONLY tenant B distinctive HTTP telemetry.
        database = await _fresh_db()
        try:
            async with database._connection_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO api_request_records
                        (id, tenant_id, request_id, method, route_template,
                         status_code, duration_ms)
                    VALUES ($1, $2, $3, 'GET', '/tenants/{tenant_id}/tools', 200, 777)
                    """,
                    f"leak-{uuid.uuid4().hex[:10]}",
                    tenant_b.id,
                    str(uuid.uuid4()),
                )
        finally:
            await database.disconnect()
        authorization_override({user_a.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user_a.id)
        body = _authed_get(client, _summary_url(tenant_a.id), token).json()
        assert body["http"]["total_requests"] == 0
        assert tenant_b.id not in str(body)

    async def test_hours_out_of_bounds_rejected(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        assert (
            client.get(
                _summary_url(tenant.id) + "?hours=0", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                _summary_url(tenant.id) + "?hours=999", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 422
        )


class TestResponseContentSafety:
    async def test_tenant_summary_shape_is_aggregates_only(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        body = _authed_get(client, _summary_url(tenant.id), token).json()
        assert set(body) == {"window_hours", "http", "tools", "connectors", "webhooks"}
        assert set(body["http"]) == {
            "total_requests",
            "error_count",
            "error_rate",
            "avg_duration_ms",
            "p95_duration_ms",
        }
        assert set(body["tools"]) == {"total_executions", "successful", "failed", "denied"}
        assert set(body["connectors"]) == {"total_syncs", "successful", "failed", "items_fetched"}
        assert set(body["webhooks"]) == {
            "available",
            "total_events",
            "distinct_event_types",
            "total_payload_bytes",
        }

    async def test_platform_summary_contains_no_tenant_identifiers_or_breakdowns(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant_a, user_a = two_tenants[0]
        authorization_override({user_a.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user_a.id)
        body = _authed_get(client, "/platform/observability/summary", token).json()
        serialized = str(body)
        assert tenant_a.id not in serialized
        # No per-tenant structures exist anywhere in the payload.
        for value in body.values():
            assert not isinstance(value, list)

    async def test_component_health_exposes_labels_only(
        self, client, two_tenants, make_token, authorization_override
    ):
        _, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        body = _authed_get(client, "/observability/health", token).json()
        assert body["overall"] in {"healthy", "degraded"}
        for component in ("database", "llm_provider", "embeddings"):
            assert set(body["components"][component]) == {"status"}
            assert body["components"][component]["status"] in {"healthy", "unhealthy"}

    async def test_component_health_failure_details_never_leak(
        self, client, two_tenants, make_token, authorization_override, monkeypatch
    ):
        from arc.services import observability as obs_module

        def boom(settings):
            raise LlmConfigurationError("jwt-secret-like-value-must-not-appear")

        monkeypatch.setattr(obs_module, "get_llm_settings", lambda: object())
        monkeypatch.setattr(obs_module, "build_llm_provider", boom)
        _, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        body = _authed_get(client, "/observability/health", token).json()
        assert "jwt-secret-like-value" not in str(body)


class TestCorrelationAndTelemetry:
    async def test_x_request_id_present_and_unique_on_public_route(self, client):
        first = client.get("/health")
        second = client.get("/health")
        assert first.status_code == 200 and second.status_code == 200
        id1 = first.headers.get("x-request-id")
        id2 = second.headers.get("x-request-id")
        assert id1 and id2 and id1 != id2

    async def test_health_body_remains_exactly_ok(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    async def test_correlation_id_present_on_handled_error_responses(self, client, two_tenants):
        tenant, _ = two_tenants[0]
        unauthenticated = client.get(_summary_url(tenant.id))
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers.get("x-request-id")
        not_found = client.get("/definitely-not-a-route")
        assert not_found.status_code == 404
        assert not_found.headers.get("x-request-id")

    async def test_successful_tenant_request_is_attributed(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        response = client.get(_summary_url(tenant.id), headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        request_id = response.headers["x-request-id"]
        database = await _fresh_db()
        try:
            async with database._connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT tenant_id, route_template, status_code, error_kind
                       FROM api_request_records WHERE request_id = $1""",
                    request_id,
                )
        finally:
            await database.disconnect()
        assert row is not None
        assert row["tenant_id"] == tenant.id
        assert row["route_template"] == "/tenants/{tenant_id}/observability/usage-summary"
        assert row["status_code"] == 200
        assert row["error_kind"] is None

    async def test_failed_tenant_request_is_never_attributed(
        self, client, two_tenants, make_token, authorization_override
    ):
        tenant, user = two_tenants[0]
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        response = client.get(_summary_url(tenant.id), headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        request_id = response.headers["x-request-id"]
        database = await _fresh_db()
        try:
            async with database._connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT tenant_id, error_kind FROM api_request_records WHERE request_id = $1",
                    request_id,
                )
        finally:
            await database.disconnect()
        assert row is not None
        assert row["tenant_id"] is None
        assert row["error_kind"] == "client_error"

    async def test_query_strings_are_never_persisted(self, client):
        marker = f"supersecret{uuid.uuid4().hex}"
        client.get(f"/health?token={marker}")
        database = await _fresh_db()
        try:
            async with database._connection_pool.acquire() as conn:
                leaked = await conn.fetchval(
                    "SELECT COUNT(*) FROM api_request_records "
                    "WHERE route_template LIKE '%supersecret%'"
                )
        finally:
            await database.disconnect()
        assert leaked == 0

    async def test_telemetry_storage_failure_does_not_break_business_response(
        self, client, two_tenants, make_token, authorization_override
    ):
        from arc.app import app as arc_application

        class ExplodingService:
            async def record_api_request(self, record):
                raise RuntimeError("telemetry backend down")

        original = arc_application.services.get("observability_service")
        arc_application.services["observability_service"] = ExplodingService()
        try:
            _, user = two_tenants[0]
            authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
            token = make_token(user.id)
            response = _authed_get(client, "/platform/observability/summary", token)
            assert response.status_code == 200
            assert response.headers.get("x-request-id")
        finally:
            arc_application.services["observability_service"] = original
