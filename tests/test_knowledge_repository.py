"""Integration tests for the PostgreSQL KnowledgeRepository.

These tests exercise the concrete PostgreSQL knowledge repository against
a real PostgreSQL database. They verify the repository contract and,
critically, tenant isolation: a document created by tenant A must never
be retrievable or listable by tenant B.
"""

import os
import uuid
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import KnowledgeDocument, KnowledgeSource, Tenant
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc")
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"kd-{prefix}-{uuid.uuid4().hex[:10]}"


def _document(tenant_id: str, **overrides):
    values = dict(
        id=_unique("doc"),
        tenant_id=tenant_id,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    values.update(overrides)
    return KnowledgeDocument(**values)


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
async def knowledge_repo(db):
    """Create a PostgreSQLKnowledgeRepository."""
    return PostgreSQLKnowledgeRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant for test data and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_id = _unique("tenant")
    tenant = await tenant_repo.create(Tenant(id=tenant_id, name="Knowledge Test Tenant"))
    yield tenant
    await tenant_repo.delete(tenant.id)


@pytest.fixture
async def seeded_tenants(db):
    """Create two tenants for cross-tenant isolation tests."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant-a"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="Tenant B"))
    yield tenant_a, tenant_b
    await tenant_repo.delete(tenant_a.id)
    await tenant_repo.delete(tenant_b.id)


class TestKnowledgeRepositoryContract:
    """Verify the KnowledgeRepository methods against PostgreSQL."""

    async def test_create_and_get(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        created = await knowledge_repo.create(document)

        assert created.id == document.id
        assert created.tenant_id == seeded_tenant.id
        assert created.source == KnowledgeSource.POLICY
        assert created.provenance == "Policy handbook 2026 edition"
        assert created.version == 1

        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.id == document.id
        assert fetched.tenant_id == seeded_tenant.id
        assert fetched.content == "Approved remote work policy."

    async def test_get_by_id_not_found(self, knowledge_repo, seeded_tenant):
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id("missing-id", seeded_tenant.id)

    async def test_list_for_tenant_empty(self, knowledge_repo, seeded_tenant):
        result = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert result == []

    async def test_list_for_tenant_multiple(self, knowledge_repo, seeded_tenant):
        ids = []
        for i in range(3):
            doc = _document(seeded_tenant.id, id=_unique(f"doc-{i}"), provenance=f"provenance-{i}")
            await knowledge_repo.create(doc)
            ids.append(doc.id)

        result = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(result) == 3
        returned_ids = {d.id for d in result}
        assert returned_ids == set(ids)

    async def test_duplicate_id_is_rejected(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        await knowledge_repo.create(document)

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create(document)

    async def test_source_and_provenance_are_round_tripped(self, knowledge_repo, seeded_tenant):
        document = _document(
            seeded_tenant.id,
            source=KnowledgeSource.INCIDENT_REPORT,
            provenance="Incident INC-2026-0042",
            version=3,
            content="Network outage resolved by restarting the gateway.",
        )
        await knowledge_repo.create(document)

        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.source == KnowledgeSource.INCIDENT_REPORT
        assert fetched.provenance == "Incident INC-2026-0042"
        assert fetched.version == 3


class TestKnowledgeTenantIsolation:
    """Prove that the SQL WHERE clause enforces tenant isolation."""

    async def test_get_by_id_isolation(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        document = _document(tenant_a.id)
        await knowledge_repo.create(document)

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, tenant_b.id)

    async def test_list_isolation(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        doc_a = _document(tenant_a.id)
        doc_b = _document(tenant_b.id)
        await knowledge_repo.create(doc_a)
        await knowledge_repo.create(doc_b)

        list_a = await knowledge_repo.list_for_tenant(tenant_a.id)
        assert len(list_a) == 1
        assert list_a[0].id == doc_a.id

        list_b = await knowledge_repo.list_for_tenant(tenant_b.id)
        assert len(list_b) == 1
        assert list_b[0].id == doc_b.id
