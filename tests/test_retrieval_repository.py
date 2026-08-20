"""Integration tests for the PostgreSQL KnowledgeChunkRepository.

These tests exercise the concrete PostgreSQL chunk repository and the
Secure RAG retrieval path against a real PostgreSQL database (with the
pgvector extension). They verify:

- chunks are persisted atomically with their embedding vectors
- retrieval is tenant isolated at the SQL boundary
- results are ordered by similarity and bounded by the limit
- chunks disappear with their owning document (FK cascade)
- the end-to-end RetrievalService path over real storage
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.services.embeddings import DeterministicEmbeddingProvider
from arc.services.retrieval import RetrievalService

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc")
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"cr-{prefix}-{uuid.uuid4().hex[:10]}"


def _chunks(document: KnowledgeDocument, count: int = 2):
    return [
        KnowledgeChunk(
            id=_unique(f"chunk-{index}"),
            document_id=document.id,
            tenant_id=document.tenant_id,
            content=f"chunk content number {index}",
            sequence=index,
            created_at=datetime.now(),
        )
        for index in range(count)
    ]


def _embeddings(count: int, dimension: int = 64):
    """Non-zero collinear embeddings: safe for presence tests."""
    return [[float(index) + 1.0] * dimension for index in range(count)]


def _axis_embedding(index: int, sign: float = 1.0, dimension: int = 64):
    """Embedding along a single distinct axis (different directions).

    Cosine similarity is direction-sensitive: axis vectors are mutually
    orthogonal, so ranking assertions are deterministic. Zero vectors are
    avoided: pgvector cosine distance is undefined (NULL) for them.
    """
    vector = [0.0] * dimension
    vector[index] = sign
    return vector


def _document(tenant_id: str, **overrides):
    values = dict(
        id=_unique("doc"),
        tenant_id=tenant_id,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook 2026 edition",
        version=1,
        status=KnowledgeStatus.ACTIVE,
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
async def chunk_repo(db):
    """Create a PostgreSQLKnowledgeChunkRepository."""
    return PostgreSQLKnowledgeChunkRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant for test data and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Chunk Test Tenant"))
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


@pytest.fixture
async def seeded_document(db, seeded_tenant):
    """Create a tenant with one persisted knowledge document."""
    knowledge_repo = PostgreSQLKnowledgeRepository(db)
    document = _document(seeded_tenant.id)
    return await knowledge_repo.create(document)


class TestKnowledgeChunkRepositoryContract:
    async def test_create_many_persists_chunks(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document)
        created = await chunk_repo.create_many(chunks, _embeddings(len(chunks)))

        assert [chunk.id for chunk in created] == [chunk.id for chunk in chunks]
        persisted = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=10)
        assert {match.chunk_id for match in persisted} == {chunk.id for chunk in chunks}
        assert all(match.tenant_id == seeded_document.tenant_id for match in persisted)
        assert all(match.document_id == seeded_document.id for match in persisted)

    async def test_mismatched_chunks_and_embeddings_are_rejected_atomically(
        self, chunk_repo, seeded_document
    ):
        chunks = _chunks(seeded_document)
        with pytest.raises(ValueError):
            await chunk_repo.create_many(chunks, _embeddings(len(chunks) - 1))

        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=10) == []

    async def test_search_with_invalid_limit_is_rejected(self, chunk_repo, seeded_tenant):
        with pytest.raises(ValueError):
            await chunk_repo.search(seeded_tenant.id, [1.0] * 64, limit=0)

    async def test_search_without_chunks_returns_empty(self, chunk_repo, seeded_tenant):
        assert await chunk_repo.search(seeded_tenant.id, [1.0] * 64, limit=5) == []

    async def test_search_returns_document_context(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=5)
        assert len(matches) == 1
        match = matches[0]
        assert match.source == KnowledgeSource.POLICY
        assert match.provenance == "Policy handbook 2026 edition"
        assert match.document_version == 1
        assert match.similarity >= 0.0

    async def test_chunks_are_removed_with_their_document(self, db, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))
        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=5)

        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM knowledge_documents WHERE id = $1", seeded_document.id)
        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=5) == []


class TestKnowledgeChunkTenantIsolation:
    """Prove that the SQL WHERE clause enforces chunk isolation."""

    async def test_search_is_tenant_isolated(self, db, chunk_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_a = await knowledge_repo.create(_document(tenant_a.id))
        doc_b = await knowledge_repo.create(_document(tenant_b.id))

        chunks_a = _chunks(doc_a)
        chunks_b = _chunks(doc_b)
        await chunk_repo.create_many(chunks_a, _embeddings(len(chunks_a)))
        await chunk_repo.create_many(chunks_b, _embeddings(len(chunks_b)))

        search_a = await chunk_repo.search(tenant_a.id, [1.0] * 64, limit=10)
        search_b = await chunk_repo.search(tenant_b.id, [1.0] * 64, limit=10)

        assert {match.chunk_id for match in search_a} == {chunk.id for chunk in chunks_a}
        assert {match.chunk_id for match in search_b} == {chunk.id for chunk in chunks_b}
        assert all(match.tenant_id == tenant_a.id for match in search_a)
        assert all(match.tenant_id == tenant_b.id for match in search_b)


class TestKnowledgeChunkRanking:
    """Results must be ordered by similarity and bounded by the limit."""

    async def test_results_are_ordered_by_similarity(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=3)
        # Distinct directions: axis(0), axis(1), and -axis(0). The query
        # axis(0) has cosine similarity 1.0, 0.0, and -1.0 with them, so
        # the ranking is strict and deterministic (zero vectors would make
        # pgvector cosine distance undefined).
        await chunk_repo.create_many(
            chunks,
            [
                _axis_embedding(0),
                _axis_embedding(1),
                _axis_embedding(0, sign=-1.0),
            ],
        )

        matches = await chunk_repo.search(seeded_document.tenant_id, _axis_embedding(0), limit=10)
        assert [match.chunk_id for match in matches] == [chunk.id for chunk in chunks]
        assert matches[0].similarity >= matches[1].similarity >= matches[2].similarity

    async def test_limit_bounds_results(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=4)
        await chunk_repo.create_many(chunks, _embeddings(4))

        assert len(await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=2)) == 2
        assert len(await chunk_repo.search(seeded_document.tenant_id, [1.0] * 64, limit=10)) == 4


class TestRetrievalServiceEndToEnd:
    """RetrievalService + real chunk storage + deterministic embeddings."""

    async def test_prepare_persist_search_round_trip(self, db, seeded_document):
        service = RetrievalService(
            chunk_repo=PostgreSQLKnowledgeChunkRepository(db),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        context = TenantContext(
            tenant_id=seeded_document.tenant_id,
            tenant_name="Chunk Test Tenant",
            user_id=_unique("user"),
            role=UserRole.MEMBER,
        )

        prepared = await service.prepare_index(context, seeded_document)
        assert prepared is not None
        await service.persist_index(prepared)

        matches = await service.search(context, "remote work", limit=5)
        assert len(matches) == 1
        assert matches[0].document_id == seeded_document.id
        assert matches[0].tenant_id == seeded_document.tenant_id
        assert matches[0].content == "Approved remote work policy."

    async def test_search_is_tenant_isolated_end_to_end(self, db, seeded_tenants):
        service = RetrievalService(
            chunk_repo=PostgreSQLKnowledgeChunkRepository(db),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_a = await knowledge_repo.create(
            _document(seeded_tenants[0].id, content="top secret strategy alpha")
        )
        context_a = TenantContext(
            tenant_id=seeded_tenants[0].id,
            tenant_name="A",
            user_id="u-a",
            role=UserRole.MEMBER,
        )
        context_b = TenantContext(
            tenant_id=seeded_tenants[1].id,
            tenant_name="B",
            user_id="u-b",
            role=UserRole.MEMBER,
        )

        prepared = await service.prepare_index(context_a, doc_a)
        await service.persist_index(prepared)

        matches_a = await service.search(context_a, "secret strategy", limit=5)
        matches_b = await service.search(context_b, "secret strategy", limit=5)
        assert len(matches_a) == 1
        assert matches_b == []
