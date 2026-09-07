"""Webhook downstream processing: API integration tests (Issue #102).

Tests the POST /tenants/{tenant_id}/webhooks/process endpoint against a
real database. Covers RBAC enforcement, path-vs-context validation,
event state transitions, and concurrent atomic claiming.
"""

import uuid

import pytest

from arc.domain.models import (
    Membership,
    Tenant,
    User,
    UserRole,
    WebhookEvent,
    WebhookEventStatus,
)
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository
from arc.security.models import ApplicationRole

ENDPOINT_ID = "wh-process-demo"
SECRET = "webhook-process-test-signing-secret-01234"


def _unique(prefix: str) -> str:
    return f"wpapi-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def webhook_tenant(db):
    """Create a tenant for processing tests."""
    tenants = PostgreSQLTenantRepository(db)
    created = await tenants.create(Tenant(id=_unique("tenant"), name="Process API Tenant"))
    yield created
    await tenants.delete(created.id)


@pytest.fixture
async def webhook_user(db, webhook_tenant):
    """Create a user and add to the webhook tenant as MEMBER."""
    users = PostgreSQLUserRepository(db)
    user = await users.create(
        User(
            id=_unique("user"),
            email=f"{_unique('user')}@test.example.com",
            username="process-test-user",
        )
    )
    memberships = PostgreSQLMembershipRepository(db)
    membership = await memberships.create(
        Membership(
            id=_unique("mem"),
            tenant_id=webhook_tenant.id,
            user_id=user.id,
            role=UserRole.MEMBER,
        )
    )
    yield user, membership
    await memberships.delete(membership.id)
    await users.delete(user.id)


@pytest.fixture
async def webhook_event(db, webhook_tenant):
    """Create a received webhook event for processing."""
    repo = PostgreSQLWebhookEventRepository(db)
    event = WebhookEvent(
        id=str(uuid.uuid4()),
        tenant_id=webhook_tenant.id,
        endpoint_id=ENDPOINT_ID,
        event_id=_unique("evt"),
        event_type="issue.opened",
        status=WebhookEventStatus.RECEIVED,
        payload_size_bytes=128,
    )
    await repo.create(event)
    return event


class TestWebhookProcessingRBAC:
    """RBAC enforcement on the webhook processing endpoint."""

    def test_process_without_auth_is_rejected(self, client, webhook_event):
        response = client.post(
            f"/tenants/{webhook_event.tenant_id}/webhooks/process?event_id={webhook_event.event_id}"
        )
        assert response.status_code in (401, 403)

    def test_process_with_wrong_permission_is_rejected(
        self,
        client,
        webhook_tenant,
        webhook_user,
        webhook_event,
        make_token,
        authorization_override,
    ):
        user, _ = webhook_user
        token = make_token(user.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})

        response = client.post(
            f"/tenants/{webhook_tenant.id}/webhooks/process?event_id={webhook_event.event_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_process_path_vs_context_mismatch_is_rejected(
        self,
        client,
        webhook_tenant,
        webhook_user,
        webhook_event,
        make_token,
        authorization_override,
    ):
        user, _ = webhook_user
        token = make_token(user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})

        response = client.post(
            f"/tenants/{_unique('wrong')}/webhooks/process?event_id={webhook_event.event_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403


class TestWebhookProcessingEndpoint:
    """Happy-path and error-path tests for webhook processing."""

    def test_event_not_found_returns_404(
        self,
        client,
        webhook_tenant,
        webhook_user,
        make_token,
        authorization_override,
    ):
        user, _ = webhook_user
        token = make_token(user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})

        response = client.post(
            f"/tenants/{webhook_tenant.id}/webhooks/process?event_id=nonexistent-event",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_missing_event_id_query_param_returns_422(
        self,
        client,
        webhook_tenant,
        webhook_user,
        make_token,
        authorization_override,
    ):
        user, _ = webhook_user
        token = make_token(user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})

        response = client.post(
            f"/tenants/{webhook_tenant.id}/webhooks/process",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422


class TestWebhookProcessingConcurrency:
    """Real-database concurrency test: only one processor wins."""

    @pytest.mark.asyncio
    async def test_only_one_processor_wins_claim(self, db):
        """Two concurrent claim_for_processing calls on the same event
        should result in exactly one success and one failure."""
        from arc.db.connection import NotFoundError

        tenants = PostgreSQLTenantRepository(db)
        tenant = await tenants.create(
            Tenant(id=_unique("concurrency"), name="Concurrency Test Tenant")
        )

        repo = PostgreSQLWebhookEventRepository(db)
        event = WebhookEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            endpoint_id=ENDPOINT_ID,
            event_id=_unique("concurrent-evt"),
            event_type="push",
            status=WebhookEventStatus.RECEIVED,
            payload_size_bytes=64,
        )
        await repo.create(event)

        results = []
        errors = []

        async def claim():
            try:
                result = await repo.claim_for_processing(event.event_id, tenant.id)
                results.append(result)
            except NotFoundError as exc:
                errors.append(exc)

        import asyncio

        await asyncio.gather(claim(), claim())

        assert len(results) == 1, f"Expected 1 successful claim, got {len(results)}"
        assert len(errors) == 1, f"Expected 1 NotFoundError, got {len(errors)}"
        assert results[0].status is WebhookEventStatus.PROCESSING

        await repo.mark_processed(event.event_id, tenant.id)
        await tenants.delete(tenant.id)
