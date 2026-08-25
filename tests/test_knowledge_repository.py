"""Integration tests for the PostgreSQL KnowledgeRepository.

These tests exercise the concrete PostgreSQL knowledge repository against
a real PostgreSQL database. They verify the repository contract and,
critically, tenant isolation: a document created by tenant A must never
be retrievable or listable by tenant B.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
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


def _chunks(document: KnowledgeDocument, count: int = 2, **overrides):
    return [
        KnowledgeChunk(
            id=overrides.get("id", _unique(f"chunk-{index}")),
            document_id=document.id,
            tenant_id=document.tenant_id,
            content=f"chunk content number {index}",
            sequence=index,
            created_at=datetime.now(),
        )
        for index in range(count)
    ]


def _embeddings(count: int, dimension: int = 64):
    """Non-zero collinear embeddings: safe for presence assertions."""
    return [[float(index) + 1.0] * dimension for index in range(count)]


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


class TestKnowledgeDocumentWithChunks:
    """Atomicity of create_document_with_chunks (one transaction).

    The document row and every chunk row are inserted in ONE PostgreSQL
    transaction: a failure while inserting a chunk rolls back the
    document insert too. There must never be a knowledge document without
    its complete retrieval index, nor a partial chunk set.
    """

    async def test_document_and_all_chunks_persist_atomically(
        self, db, knowledge_repo, seeded_tenant
    ):
        chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=3)

        created = await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(3))

        assert created.id == document.id
        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.id == document.id

        matches = await chunk_repo.search(seeded_tenant.id, [1.0] * 64, limit=10)
        assert {match.chunk_id for match in matches} == {chunk.id for chunk in chunks}
        assert all(match.document_id == document.id for match in matches)

    async def test_chunk_insertion_failure_rolls_back_document_and_chunks(
        self, db, knowledge_repo, seeded_tenant
    ):
        chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
        document = _document(seeded_tenant.id)
        # Both chunks share one ID: the first chunk insert succeeds, the
        # second violates the primary key INSIDE the transaction.
        chunks = _chunks(document, count=2, id=_unique("duplicate-chunk"))

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(2))

        # The document insert was rolled back: no row, no chunks.
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert await chunk_repo.search(seeded_tenant.id, [1.0] * 64, limit=10) == []

    async def test_length_mismatch_is_rejected_before_any_write(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=2)

        with pytest.raises(ValueError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(1))

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)

    async def test_tenant_mismatch_between_document_and_chunks_is_rejected(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=2)
        chunks[0].tenant_id = f"{seeded_tenant.id}-other"

        with pytest.raises(ValueError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(2))

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)

    async def test_document_duplicate_is_rejected(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        await knowledge_repo.create(document)

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create_document_with_chunks(
                document, _chunks(document, count=1), _embeddings(1)
            )


class TestKnowledgeDocumentIdentity:
    """ADR-003: logical identity (tenant_id, source, external_id)."""

    async def test_identity_uniqueness_enforced_by_database(self, knowledge_repo, seeded_tenant):
        first = _document(seeded_tenant.id, external_id="ext-shared")
        await knowledge_repo.create(first)

        duplicate = _document(seeded_tenant.id, external_id="ext-shared")
        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create(duplicate)

    async def test_null_external_id_is_excluded_from_identity(self, knowledge_repo, seeded_tenant):
        await knowledge_repo.create(_document(seeded_tenant.id))
        await knowledge_repo.create(_document(seeded_tenant.id))

        rows = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(rows) == 2
        assert all(row.external_id is None for row in rows)

    async def test_same_identity_across_tenants_is_allowed(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants

        doc_a = await knowledge_repo.create(_document(tenant_a.id, external_id="shared-ext"))
        doc_b = await knowledge_repo.create(_document(tenant_b.id, external_id="shared-ext"))

        assert doc_a.tenant_id != doc_b.tenant_id

    async def test_get_by_external_id_round_trip_and_scoping(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        created = await knowledge_repo.create(
            _document(tenant_a.id, external_id="lookup-1", provenance="connector:github:42")
        )

        found = await knowledge_repo.get_by_external_id(
            "lookup-1", KnowledgeSource.POLICY, tenant_a.id
        )
        assert found.id == created.id
        assert found.external_id == "lookup-1"

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id("lookup-1", KnowledgeSource.POLICY, tenant_b.id)
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id(
                "lookup-1", KnowledgeSource.SOLUTION, tenant_a.id
            )
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id("missing", KnowledgeSource.POLICY, tenant_a.id)

    async def test_update_replaces_document_and_chunks_atomically(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id, external_id="upd-1", content="old content")
        old_chunks = _chunks(document, count=2)
        await knowledge_repo.create_document_with_chunks(
            document, old_chunks, _embeddings(len(old_chunks))
        )

        updated = KnowledgeDocument(
            id=document.id,
            tenant_id=document.tenant_id,
            source=document.source,
            provenance=document.provenance,
            version=document.version + 1,
            status=document.status,
            content="new content",
            external_id=document.external_id,
            created_at=document.created_at,
            updated_at=datetime.now(),
        )
        new_chunks = _chunks(document, count=1)
        result = await knowledge_repo.update_document_with_chunks(
            updated, new_chunks, _embeddings(len(new_chunks))
        )

        assert result.version == 2
        assert result.content == "new content"
        stored = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert stored.version == 2
        assert stored.content == "new content"

        async with knowledge_repo.db._connection_pool.acquire() as conn:
            chunk_ids = await conn.fetch(
                "SELECT id FROM knowledge_chunks WHERE document_id = $1",
                document.id,
            )
        assert {row["id"] for row in chunk_ids} == {new_chunks[0].id}

    async def test_update_failure_rolls_back_to_prior_version_and_chunks(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id, external_id="rb-1", content="old content")
        old_chunks = _chunks(document, count=2)
        await knowledge_repo.create_document_with_chunks(
            document, old_chunks, _embeddings(len(old_chunks))
        )

        # Two chunks share one id: the second insert violates the chunk PK
        # INSIDE the transaction (after the UPDATE and DELETE), so the whole
        # operation must roll back to the prior version and prior chunks.
        broken_new_chunks = [
            KnowledgeChunk(
                id="duplicate-chunk-id",
                document_id=document.id,
                tenant_id=document.tenant_id,
                content="new chunk a",
                sequence=0,
                created_at=datetime.now(),
            ),
            KnowledgeChunk(
                id="duplicate-chunk-id",
                document_id=document.id,
                tenant_id=document.tenant_id,
                content="new chunk b",
                sequence=1,
                created_at=datetime.now(),
            ),
        ]
        bumped = KnowledgeDocument(
            id=document.id,
            tenant_id=document.tenant_id,
            source=document.source,
            provenance=document.provenance,
            version=document.version + 1,
            status=document.status,
            content="doomed new content",
            external_id=document.external_id,
            created_at=document.created_at,
            updated_at=datetime.now(),
        )
        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.update_document_with_chunks(
                bumped, broken_new_chunks, _embeddings(len(broken_new_chunks))
            )

        stored = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert stored.version == 1
        assert stored.content == "old content"

        async with knowledge_repo.db._connection_pool.acquire() as conn:
            remaining = await conn.fetch(
                "SELECT id FROM knowledge_chunks WHERE document_id = $1 ORDER BY sequence",
                document.id,
            )
        assert [row["id"] for row in remaining] == [chunk.id for chunk in old_chunks]


class TestConcurrentIdentityIngestion:
    """ADR-003 concurrency: races are resolved by the database invariant."""

    class _PassthroughGuard:
        def sanitize(self, text: str):
            from types import SimpleNamespace

            return SimpleNamespace(sanitized_text=text)

    async def test_concurrent_first_delivery_creates_exactly_one_row(self, db, seeded_tenant):
        import asyncio

        from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
        from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
        from arc.services.knowledge import KnowledgeService
        from arc.services.retrieval import RetrievalService

        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        indexer = RetrievalService(PostgreSQLKnowledgeChunkRepository(db))
        service = KnowledgeService(
            knowledge_repo, pii_guard=self._PassthroughGuard(), indexer=indexer
        )
        context = TenantContext(
            tenant_id=seeded_tenant.id,
            tenant_name="Concurrent",
            user_id="user-1",
            role=UserRole.MEMBER,
        )

        results = await asyncio.gather(
            service.ingest_document(
                context,
                source=KnowledgeSource.INTERNAL_KNOWLEDGE,
                provenance="connector:github:race",
                content="identical concurrent content",
                external_id="github:race",
            ),
            service.ingest_document(
                context,
                source=KnowledgeSource.INTERNAL_KNOWLEDGE,
                provenance="connector:github:race",
                content="identical concurrent content",
                external_id="github:race",
            ),
        )

        assert results[0].id == results[1].id
        assert results[0].version == 1

        async with db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM knowledge_documents
                WHERE tenant_id = $1 AND external_id = $2
                """,
                seeded_tenant.id,
                "github:race",
            )
        assert len(rows) == 1
