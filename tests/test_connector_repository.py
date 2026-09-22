"""Integration tests for the PostgreSQL ConnectorRepository.

These tests exercise the concrete PostgreSQL connector repository through
the service-facing Protocol method names against a real PostgreSQL database.
They verify the repository contract and tenant isolation end-to-end.
"""

import os
import uuid
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import ConnectorConfig, ConnectorProvider, ConnectorStatus, Tenant
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"ct-{prefix}-{uuid.uuid4().hex[:10]}"


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
async def connector_repo(db):
    """Create a PostgreSQLConnectorRepository."""
    return PostgreSQLConnectorRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant for test data and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_id = _unique("tenant")
    tenant = await tenant_repo.create(Tenant(id=tenant_id, name="Connector Test Tenant"))
    yield tenant
    await tenant_repo.delete(tenant.id)


@pytest.fixture
async def seeded_tenants(db):
    """Create two tenants for cross-tenant isolation tests."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_a_id = _unique("tenant-a")
    tenant_b_id = _unique("tenant-b")
    tenant_a = await tenant_repo.create(Tenant(id=tenant_a_id, name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=tenant_b_id, name="Tenant B"))
    yield tenant_a, tenant_b
    await tenant_repo.delete(tenant_a.id)
    await tenant_repo.delete(tenant_b.id)


class TestConnectorRepositoryContract:
    """Verify the ConnectorRepository Protocol methods against PostgreSQL."""

    async def test_create_and_get(self, connector_repo, seeded_tenant):
        """Test creating a connector and retrieving it."""
        connector_id = _unique("conn")
        connector = ConnectorConfig(
            id=connector_id,
            tenant_id=seeded_tenant.id,
            provider=ConnectorProvider.SLACK,
            name="Test Slack",
            target="#general",
        )
        created = await connector_repo.create(connector)
        assert created.id == connector_id
        assert created.provider == ConnectorProvider.SLACK
        assert created.name == "Test Slack"
        assert created.target == "#general"
        assert created.status == ConnectorStatus.ACTIVE

        fetched = await connector_repo.get_by_id(connector_id, seeded_tenant.id)
        assert fetched.id == connector_id
        assert fetched.tenant_id == seeded_tenant.id
        assert fetched.provider == ConnectorProvider.SLACK
        assert fetched.name == "Test Slack"
        assert fetched.target == "#general"
        assert fetched.status == ConnectorStatus.ACTIVE

        await connector_repo.delete(connector_id, seeded_tenant.id)

    async def test_list_for_tenant_empty(self, connector_repo, seeded_tenant):
        """Test listing connectors for a tenant with none."""
        result = await connector_repo.list_for_tenant(seeded_tenant.id)
        assert result == []

    async def test_list_for_tenant_multiple(self, connector_repo, seeded_tenant):
        """Test listing multiple connectors for a tenant."""
        ids = []
        for i in range(3):
            cid = _unique(f"conn-{i}")
            await connector_repo.create(
                ConnectorConfig(
                    id=cid,
                    tenant_id=seeded_tenant.id,
                    provider=ConnectorProvider.SLACK,
                    name=f"Slack {i}",
                    target=f"#{i}-channel",
                )
            )
            ids.append(cid)

        result = await connector_repo.list_for_tenant(seeded_tenant.id)
        assert len(result) == 3
        returned_ids = {c.id for c in result}
        assert returned_ids == set(ids)

        for cid in ids:
            await connector_repo.delete(cid, seeded_tenant.id)

    async def test_exists_true(self, connector_repo, seeded_tenant):
        """Test exists returns True for existing connector."""
        connector_id = _unique("conn")
        await connector_repo.create(
            ConnectorConfig(
                id=connector_id,
                tenant_id=seeded_tenant.id,
                provider=ConnectorProvider.GITHUB,
                name="GitHub",
                target="org/repo",
            )
        )
        assert await connector_repo.exists(connector_id, seeded_tenant.id) is True
        await connector_repo.delete(connector_id, seeded_tenant.id)

    async def test_exists_false(self, connector_repo, seeded_tenant):
        """Test exists returns False for missing connector."""
        assert await connector_repo.exists("missing-id", seeded_tenant.id) is False

    async def test_delete(self, connector_repo, seeded_tenant):
        """Test deleting a connector."""
        connector_id = _unique("conn")
        await connector_repo.create(
            ConnectorConfig(
                id=connector_id,
                tenant_id=seeded_tenant.id,
                provider=ConnectorProvider.LINEAR,
                name="Linear",
                target="ENG",
            )
        )
        await connector_repo.delete(connector_id, seeded_tenant.id)
        assert await connector_repo.exists(connector_id, seeded_tenant.id) is False

    async def test_get_by_id_not_found(self, connector_repo, seeded_tenant):
        """Test get_by_id raises NotFoundError for missing connector."""
        with pytest.raises(NotFoundError):
            await connector_repo.get_by_id("missing-id", seeded_tenant.id)

    async def test_duplicate_name_same_provider(self, connector_repo, seeded_tenant):
        """Test creating two connectors with same tenant/provider/name fails."""
        await connector_repo.create(
            ConnectorConfig(
                id=_unique("conn-a"),
                tenant_id=seeded_tenant.id,
                provider=ConnectorProvider.SLACK,
                name="Duplicate Name",
                target="#general",
            )
        )
        with pytest.raises(DuplicateKeyError):
            await connector_repo.create(
                ConnectorConfig(
                    id=_unique("conn-b"),
                    tenant_id=seeded_tenant.id,
                    provider=ConnectorProvider.SLACK,
                    name="Duplicate Name",
                    target="#general",
                )
            )
        await connector_repo.delete(_unique("conn-a"), seeded_tenant.id)
        # Cleanup: find and delete the actual connector
        connectors = await connector_repo.list_for_tenant(seeded_tenant.id)
        for c in connectors:
            if c.name == "Duplicate Name":
                await connector_repo.delete(c.id, seeded_tenant.id)


class TestConnectorTenantIsolation:
    """Prove that the SQL WHERE clause enforces tenant isolation."""

    async def test_get_by_id_isolation(self, connector_repo, seeded_tenants):
        """Tenant A cannot read tenant B's connector by ID."""
        tenant_a, tenant_b = seeded_tenants
        conn_id = _unique("conn")
        await connector_repo.create(
            ConnectorConfig(
                id=conn_id,
                tenant_id=tenant_a.id,
                provider=ConnectorProvider.SLACK,
                name="Tenant A Slack",
                target="#a-channel",
            )
        )

        # Tenant B tries to read tenant A's connector
        with pytest.raises(NotFoundError):
            await connector_repo.get_by_id(conn_id, tenant_b.id)

        await connector_repo.delete(conn_id, tenant_a.id)

    async def test_list_isolation(self, connector_repo, seeded_tenants):
        """Tenant A cannot see tenant B's connectors through list."""
        tenant_a, tenant_b = seeded_tenants

        # Create connector for tenant A
        conn_a = _unique("conn-a")
        await connector_repo.create(
            ConnectorConfig(
                id=conn_a,
                tenant_id=tenant_a.id,
                provider=ConnectorProvider.SLACK,
                name="Tenant A Slack",
                target="#a-channel",
            )
        )

        # Create connector for tenant B
        conn_b = _unique("conn-b")
        await connector_repo.create(
            ConnectorConfig(
                id=conn_b,
                tenant_id=tenant_b.id,
                provider=ConnectorProvider.SLACK,
                name="Tenant B Slack",
                target="#b-channel",
            )
        )

        # Tenant A lists — should only see their own
        list_a = await connector_repo.list_for_tenant(tenant_a.id)
        assert len(list_a) == 1
        assert list_a[0].id == conn_a

        # Tenant B lists — should only see their own
        list_b = await connector_repo.list_for_tenant(tenant_b.id)
        assert len(list_b) == 1
        assert list_b[0].id == conn_b

        await connector_repo.delete(conn_a, tenant_a.id)
        await connector_repo.delete(conn_b, tenant_b.id)

    async def test_delete_isolation(self, connector_repo, seeded_tenants):
        """Tenant A cannot delete tenant B's connector."""
        tenant_a, tenant_b = seeded_tenants
        conn_b = _unique("conn-b")
        await connector_repo.create(
            ConnectorConfig(
                id=conn_b,
                tenant_id=tenant_b.id,
                provider=ConnectorProvider.GITHUB,
                name="Tenant B GitHub",
                target="org/repo",
            )
        )

        # Tenant A tries to delete tenant B's connector — no error raised
        # because DELETE WHERE id=$1 AND tenant_id=$2 affects 0 rows
        await connector_repo.delete(conn_b, tenant_a.id)

        # Tenant B's connector still exists
        assert await connector_repo.exists(conn_b, tenant_b.id) is True

        await connector_repo.delete(conn_b, tenant_b.id)

    async def test_exists_isolation(self, connector_repo, seeded_tenants):
        """Tenant A cannot confirm existence of tenant B's connector."""
        tenant_a, tenant_b = seeded_tenants
        conn_b = _unique("conn-b")
        await connector_repo.create(
            ConnectorConfig(
                id=conn_b,
                tenant_id=tenant_b.id,
                provider=ConnectorProvider.LINEAR,
                name="Tenant B Linear",
                target="ENG",
            )
        )

        # Tenant A checks existence — should return False
        assert await connector_repo.exists(conn_b, tenant_a.id) is False

        await connector_repo.delete(conn_b, tenant_b.id)
