"""Webhooks foundation: PostgreSQL repository tests.

Runs against the real PostgreSQL database (project convention): proves
SQL-level tenant isolation, duplicate detection via the uniqueness pair,
tenant cascade deletion, and metadata-only record storage.
"""

import uuid

import pytest

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import Tenant, WebhookEvent
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"wr-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def webhook_repos(db):
    """Concrete tenant and webhook event repositories over one database."""
    return PostgreSQLTenantRepository(db), PostgreSQLWebhookEventRepository(db)


@pytest.fixture
async def tenant(db):
    """Create a tenant and remove it afterwards (cascades its events)."""
    repo = PostgreSQLTenantRepository(db)
    created = await repo.create(Tenant(id=_unique("tenant"), name="Webhook Repo Tenant"))
    yield created
    await repo.delete(created.id)


def _make_event(tenant_id: str, event_id: str | None = None) -> WebhookEvent:
    return WebhookEvent(
        id=_unique("event"),
        tenant_id=tenant_id,
        endpoint_id="github-demo",
        event_id=event_id or _unique("sender-event"),
        event_type="issue.opened",
        payload_size_bytes=128,
    )


class TestWebhookEventRepositoryCreate:
    async def test_created_event_round_trips(self, webhook_repos, tenant):
        _, events = webhook_repos
        event = _make_event(tenant.id)

        stored = await events.create(event)
        fetched = await events.get_by_event_id(event.event_id, tenant.id)

        assert fetched.id == stored.id
        assert fetched.tenant_id == tenant.id
        assert fetched.endpoint_id == "github-demo"
        assert fetched.event_type == "issue.opened"
        assert fetched.payload_size_bytes == 128

    async def test_duplicate_tenant_event_pair_is_rejected(self, webhook_repos, tenant):
        _, events = webhook_repos
        shared_event_id = _unique("sender-event")

        await events.create(_make_event(tenant.id, shared_event_id))
        with pytest.raises(DuplicateKeyError):
            await events.create(_make_event(tenant.id, shared_event_id))

    async def test_same_event_id_in_different_tenants_is_allowed(self, webhook_repos, tenant, db):
        _, events = webhook_repos
        other_tenant_repo = PostgreSQLTenantRepository(db)
        other_tenant = await other_tenant_repo.create(
            Tenant(id=_unique("tenant-other"), name="Other")
        )
        try:
            shared_event_id = _unique("sender-event")
            await events.create(_make_event(tenant.id, shared_event_id))
            await events.create(_make_event(other_tenant.id, shared_event_id))

            first = await events.get_by_event_id(shared_event_id, tenant.id)
            second = await events.get_by_event_id(shared_event_id, other_tenant.id)
            assert first.tenant_id == tenant.id
            assert second.tenant_id == other_tenant.id
        finally:
            await other_tenant_repo.delete(other_tenant.id)


class TestWebhookEventRepositoryIsolation:
    async def test_foreign_tenant_event_is_not_found(self, webhook_repos, tenant):
        _, events = webhook_repos
        event = await events.create(_make_event(tenant.id))

        with pytest.raises(NotFoundError):
            await events.get_by_event_id(event.event_id, _unique("foreign-tenant"))

    async def test_listing_is_scoped_to_the_trusted_tenant(self, webhook_repos, tenant, db):
        _, events = webhook_repos
        other_tenant_repo = PostgreSQLTenantRepository(db)
        other_tenant = await other_tenant_repo.create(
            Tenant(id=_unique("tenant-other"), name="Other")
        )
        try:
            await events.create(_make_event(tenant.id))
            await events.create(_make_event(other_tenant.id))

            mine = await events.list_for_tenant(tenant.id)
            theirs = await events.list_for_tenant(other_tenant.id)

            assert len(mine) == 1
            assert all(item.tenant_id == tenant.id for item in mine)
            assert len(theirs) == 1
            assert all(item.tenant_id == other_tenant.id for item in theirs)
        finally:
            await other_tenant_repo.delete(other_tenant.id)

    async def test_records_never_contain_payload_content(self, webhook_repos, tenant):
        """Records are envelope-metadata-only by design."""
        _, events = webhook_repos
        event = await events.create(_make_event(tenant.id))
        fetched = await events.get_by_event_id(event.event_id, tenant.id)
        serialized = str(fetched)
        # No raw payload field exists anywhere on the persisted model.
        assert "payload" not in serialized.replace("payload_size_bytes", "")
        assert "data" not in vars(fetched)


class TestWebhookEventRepositoryCascade:
    async def test_deleting_the_tenant_cascades_its_events(self, webhook_repos, tenant):
        _, events = webhook_repos
        await events.create(_make_event(tenant.id))
        assert len(await events.list_for_tenant(tenant.id)) == 1

        await PostgreSQLTenantRepository(webhook_repos[0].db).delete(tenant.id)

        assert await events.list_for_tenant(tenant.id) == []
