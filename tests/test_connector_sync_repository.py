"""Integration tests for the PostgreSQL ConnectorSyncRepository.

Exercises the concrete repository against a real PostgreSQL database and
proves tenant isolation at the SQL level. Records only ever contain safe
summaries (item counts and generic error kinds) — never credentials or
raw external payloads.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import (
    ConnectorConfig,
    ConnectorProvider,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
    Tenant,
)
from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc")
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"csr-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def db():
    """Connect to PostgreSQL and ensure the schema exists."""
    database = ArcDatabase(DATABASE_URL)
    await database.connect()
    async with database._connection_pool.acquire() as conn:
        schema = SCHEMA_PATH.read_text()
        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)
    yield database
    await database.disconnect()


@pytest.fixture
async def sync_repo(db):
    """Create a PostgreSQLConnectorSyncRepository."""
    return PostgreSQLConnectorSyncRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant and a connector, and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    connector_repo = PostgreSQLConnectorRepository(db)

    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Sync Test Tenant"))
    connector = await connector_repo.create(
        ConnectorConfig(
            id=_unique("connector"),
            tenant_id=tenant.id,
            provider=ConnectorProvider.GITHUB,
            name="example/acme",
            target="acme/project",
        )
    )
    yield tenant, connector
    await connector_repo.delete(connector.id, tenant.id)
    await tenant_repo.delete(tenant.id)


@pytest.fixture
async def seeded_tenants(db):
    """Create two tenants (with connectors) for isolation tests."""
    tenant_repo = PostgreSQLTenantRepository(db)
    connector_repo = PostgreSQLConnectorRepository(db)

    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant-a"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="Tenant B"))
    connector_a = await connector_repo.create(
        ConnectorConfig(
            id=_unique("connector-a"),
            tenant_id=tenant_a.id,
            provider=ConnectorProvider.SLACK,
            name="general",
            target="#general",
        )
    )
    connector_b = await connector_repo.create(
        ConnectorConfig(
            id=_unique("connector-b"),
            tenant_id=tenant_b.id,
            provider=ConnectorProvider.LINEAR,
            name="abc",
            target="ENG",
        )
    )
    yield tenant_a, tenant_b, connector_a, connector_b
    await connector_repo.delete(connector_a.id, tenant_a.id)
    await connector_repo.delete(connector_b.id, tenant_b.id)
    await tenant_repo.delete(tenant_a.id)
    await tenant_repo.delete(tenant_b.id)


class TestConnectorSyncRepositoryContract:
    async def test_create_and_list_success_record(self, sync_repo, seeded_tenant):
        tenant, connector = seeded_tenant
        record = ConnectorSyncRecord(
            id=_unique("record"),
            tenant_id=tenant.id,
            connector_id=connector.id,
            provider=ConnectorProvider.GITHUB,
            status=ConnectorSyncStatus.SUCCESS,
            items_fetched=3,
            created_at=datetime.now(),
        )
        created = await sync_repo.create_record(record)
        assert created.id == record.id

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].id == record.id
        assert records[0].provider == ConnectorProvider.GITHUB
        assert records[0].status is ConnectorSyncStatus.SUCCESS
        assert records[0].items_fetched == 3
        assert records[0].error_kind is None

    async def test_create_and_list_failed_record(self, sync_repo, seeded_tenant):
        tenant, connector = seeded_tenant
        record = ConnectorSyncRecord(
            id=_unique("record"),
            tenant_id=tenant.id,
            connector_id=connector.id,
            provider=ConnectorProvider.GITHUB,
            status=ConnectorSyncStatus.FAILED,
            error_kind="auth_failed",
            created_at=datetime.now(),
        )
        await sync_repo.create_record(record)

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status is ConnectorSyncStatus.FAILED
        assert records[0].error_kind == "auth_failed"
        assert records[0].items_fetched == 0

    async def test_list_for_tenant_empty(self, sync_repo, seeded_tenant):
        tenant, _ = seeded_tenant
        assert await sync_repo.list_for_tenant(tenant.id) == []

    async def test_cascade_delete_removes_sync_records(self, sync_repo, seeded_tenant, db):
        tenant, connector = seeded_tenant
        await sync_repo.create_record(
            ConnectorSyncRecord(
                id=_unique("record"),
                tenant_id=tenant.id,
                connector_id=connector.id,
                provider=ConnectorProvider.GITHUB,
                status=ConnectorSyncStatus.SUCCESS,
                items_fetched=1,
            )
        )
        connector_repo = PostgreSQLConnectorRepository(db)
        await connector_repo.delete(connector.id, tenant.id)

        assert await sync_repo.list_for_tenant(tenant.id) == []


class TestConnectorSyncTenantIsolation:
    async def test_list_isolation(self, sync_repo, seeded_tenants):
        tenant_a, tenant_b, connector_a, connector_b = seeded_tenants

        await sync_repo.create_record(
            ConnectorSyncRecord(
                id=_unique("record-a"),
                tenant_id=tenant_a.id,
                connector_id=connector_a.id,
                provider=ConnectorProvider.SLACK,
                status=ConnectorSyncStatus.SUCCESS,
                items_fetched=2,
            )
        )
        await sync_repo.create_record(
            ConnectorSyncRecord(
                id=_unique("record-b"),
                tenant_id=tenant_b.id,
                connector_id=connector_b.id,
                provider=ConnectorProvider.LINEAR,
                status=ConnectorSyncStatus.FAILED,
                error_kind="rate_limited",
            )
        )

        records_a = await sync_repo.list_for_tenant(tenant_a.id)
        assert len(records_a) == 1
        assert records_a[0].tenant_id == tenant_a.id
        assert records_a[0].provider == ConnectorProvider.SLACK

        records_b = await sync_repo.list_for_tenant(tenant_b.id)
        assert len(records_b) == 1
        assert records_b[0].tenant_id == tenant_b.id
        assert records_b[0].error_kind == "rate_limited"
