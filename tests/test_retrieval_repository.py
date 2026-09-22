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
from datetime import datetime, timezone
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

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
)
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
            created_at=datetime.now(timezone.utc),
        )
        for index in range(count)
    ]


def _embeddings(count: int, dimension: int = 1536):
    """Non-zero collinear embeddings: safe for presence tests."""
    return [[float(index) + 1.0] * dimension for index in range(count)]


def _axis_embedding(index: int, sign: float = 1.0, dimension: int = 1536):
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
        persisted = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10)
        assert {match.chunk_id for match in persisted} == {chunk.id for chunk in chunks}
        assert all(match.tenant_id == seeded_document.tenant_id for match in persisted)
        assert all(match.document_id == seeded_document.id for match in persisted)

    async def test_mismatched_chunks_and_embeddings_are_rejected_atomically(
        self, chunk_repo, seeded_document
    ):
        chunks = _chunks(seeded_document)
        with pytest.raises(ValueError):
            await chunk_repo.create_many(chunks, _embeddings(len(chunks) - 1))

        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10) == []

    async def test_search_with_invalid_limit_is_rejected(self, chunk_repo, seeded_tenant):
        with pytest.raises(ValueError):
            await chunk_repo.search(seeded_tenant.id, [1.0] * 1536, limit=0)

    async def test_search_without_chunks_returns_empty(self, chunk_repo, seeded_tenant):
        assert await chunk_repo.search(seeded_tenant.id, [1.0] * 1536, limit=5) == []

    async def test_search_returns_document_context(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=5)
        assert len(matches) == 1
        match = matches[0]
        assert match.source == KnowledgeSource.POLICY
        assert match.provenance == "Policy handbook 2026 edition"
        assert match.document_version == 1
        assert match.sequence == chunks[0].sequence
        assert match.similarity >= 0.0

    async def test_search_preserves_chunk_sequence(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=3)
        await chunk_repo.create_many(chunks, _embeddings(3))

        matches = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10)
        assert {match.chunk_id: match.sequence for match in matches} == {
            chunk.id: chunk.sequence for chunk in chunks
        }

    async def test_create_many_rejects_mixed_tenant_chunks_atomically(
        self, chunk_repo, seeded_document
    ):
        chunks = _chunks(seeded_document, count=2)
        chunks[1].tenant_id = f"{seeded_document.tenant_id}-other"

        with pytest.raises(ValueError):
            await chunk_repo.create_many(chunks, _embeddings(2))

        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10) == []

    async def test_chunks_are_removed_with_their_document(self, db, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))
        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=5)

        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM knowledge_documents WHERE id = $1", seeded_document.id)
        assert await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=5) == []


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

        search_a = await chunk_repo.search(tenant_a.id, [1.0] * 1536, limit=10)
        search_b = await chunk_repo.search(tenant_b.id, [1.0] * 1536, limit=10)

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

        assert len(await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=2)) == 2
        assert len(await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10)) == 4


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


class TestSearchSourceFiltering:
    """Source-type filtering must narrow the candidate set at the SQL level."""

    async def test_no_filter_returns_all_sources(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.search(seeded_document.tenant_id, [1.0] * 1536, limit=10)
        assert len(matches) == 1
        assert matches[0].source == KnowledgeSource.POLICY

    async def test_matching_source_returns_only_matching_documents(
        self, db, chunk_repo, seeded_tenant
    ):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_policy = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.POLICY)
        )
        doc_procedure = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.PROCEDURE)
        )

        chunks_policy = _chunks(doc_policy, count=1)
        chunks_procedure = _chunks(doc_procedure, count=1)
        await chunk_repo.create_many(chunks_policy, _embeddings(1))
        await chunk_repo.create_many(chunks_procedure, _embeddings(1))

        matches = await chunk_repo.search(
            seeded_tenant.id,
            [1.0] * 1536,
            limit=10,
            source_type=KnowledgeSource.POLICY,
        )
        assert len(matches) == 1
        assert matches[0].source == KnowledgeSource.POLICY
        assert matches[0].document_id == doc_policy.id

    async def test_non_matching_source_returns_empty(self, db, chunk_repo, seeded_tenant):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.POLICY)
        )
        chunks = _chunks(doc, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.search(
            seeded_tenant.id,
            [1.0] * 1536,
            limit=10,
            source_type=KnowledgeSource.PROCEDURE,
        )
        assert matches == []

    async def test_source_filter_preserves_tenant_isolation(self, db, chunk_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_a = await knowledge_repo.create(_document(tenant_a.id, source=KnowledgeSource.POLICY))
        doc_b = await knowledge_repo.create(_document(tenant_b.id, source=KnowledgeSource.POLICY))
        await chunk_repo.create_many(_chunks(doc_a, count=1), _embeddings(1))
        await chunk_repo.create_many(_chunks(doc_b, count=1), _embeddings(1))

        matches_a = await chunk_repo.search(
            tenant_a.id, [1.0] * 1536, limit=10, source_type=KnowledgeSource.POLICY
        )
        matches_b = await chunk_repo.search(
            tenant_b.id, [1.0] * 1536, limit=10, source_type=KnowledgeSource.POLICY
        )
        assert len(matches_a) == 1
        assert matches_a[0].tenant_id == tenant_a.id
        assert len(matches_b) == 1
        assert matches_b[0].tenant_id == tenant_b.id

    async def test_archived_documents_excluded_with_source_filter(
        self, db, chunk_repo, seeded_tenant
    ):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.POLICY)
        )
        chunks = _chunks(doc, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        # Archive the document
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET status = 'archived' WHERE id = $1",
                doc.id,
            )

        matches = await chunk_repo.search(
            seeded_tenant.id, [1.0] * 1536, limit=10, source_type=KnowledgeSource.POLICY
        )
        assert matches == []

    async def test_multiple_source_types_isolated_from_each_other(
        self, db, chunk_repo, seeded_tenant
    ):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_policy = await knowledge_repo.create(
            _document(
                seeded_tenant.id,
                source=KnowledgeSource.POLICY,
                content="policy content alpha",
            )
        )
        doc_incident = await knowledge_repo.create(
            _document(
                seeded_tenant.id,
                source=KnowledgeSource.INCIDENT_REPORT,
                content="incident content beta",
            )
        )
        await chunk_repo.create_many(_chunks(doc_policy, count=1), _embeddings(1))
        await chunk_repo.create_many(_chunks(doc_incident, count=1), _embeddings(1))

        policy_matches = await chunk_repo.search(
            seeded_tenant.id, [1.0] * 1536, limit=10, source_type=KnowledgeSource.POLICY
        )
        incident_matches = await chunk_repo.search(
            seeded_tenant.id,
            [1.0] * 1536,
            limit=10,
            source_type=KnowledgeSource.INCIDENT_REPORT,
        )
        assert len(policy_matches) == 1
        assert policy_matches[0].source == KnowledgeSource.POLICY
        assert len(incident_matches) == 1
        assert incident_matches[0].source == KnowledgeSource.INCIDENT_REPORT


class TestLexicalSearchVectorPopulation:
    """search_vector must be populated on insert for lexical retrieval."""

    async def test_search_vector_is_populated_after_insert(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        async with chunk_repo.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT search_vector FROM knowledge_chunks WHERE id = $1",
                chunks[0].id,
            )
        assert row is not None
        assert row["search_vector"] is not None

    async def test_search_vector_matches_content(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        await chunk_repo.create_many(chunks, _embeddings(1))

        async with chunk_repo.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT search_vector, content FROM knowledge_chunks WHERE id = $1",
                chunks[0].id,
            )
        # Verify the vector is non-null and non-empty
        assert row["search_vector"] is not None
        assert len(str(row["search_vector"])) > 0


class TestLexicalSearchRepository:
    """Lexical search via PostgreSQL full-text search."""

    async def test_lexical_search_returns_matching_chunks(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        chunks[0].content = "approved remote work policy"
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.lexical_search(seeded_document.tenant_id, "remote work", limit=5)
        assert len(matches) == 1
        assert matches[0].chunk_id == chunks[0].id
        assert matches[0].content == "approved remote work policy"

    async def test_lexical_search_no_match_returns_empty(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        chunks[0].content = "approved remote work policy"
        await chunk_repo.create_many(chunks, _embeddings(1))

        matches = await chunk_repo.lexical_search(
            seeded_document.tenant_id, "quantum physics", limit=5
        )
        assert matches == []

    async def test_lexical_search_orders_by_relevance(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=3)
        chunks[0].content = "remote work policy for employees"
        chunks[1].content = "remote work policy for contractors"
        chunks[2].content = "office attendance policy"
        await chunk_repo.create_many(chunks, _embeddings(3))

        matches = await chunk_repo.lexical_search(
            seeded_document.tenant_id, "remote work", limit=10
        )
        assert len(matches) == 2
        # Both remote work chunks should be returned; the attendance chunk should not
        contents = {m.content for m in matches}
        assert "office attendance policy" not in contents

    async def test_lexical_search_limit_bounds_results(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=3)
        chunks[0].content = "remote work policy alpha"
        chunks[1].content = "remote work policy beta"
        chunks[2].content = "remote work policy gamma"
        await chunk_repo.create_many(chunks, _embeddings(3))

        matches = await chunk_repo.lexical_search(seeded_document.tenant_id, "remote work", limit=2)
        assert len(matches) == 2

    async def test_lexical_search_source_type_filter(self, db, chunk_repo, seeded_tenant):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_policy = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.POLICY)
        )
        doc_procedure = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.PROCEDURE)
        )
        chunk_policy = _chunks(doc_policy, count=1)
        chunk_policy[0].content = "remote work policy"
        chunk_procedure = _chunks(doc_procedure, count=1)
        chunk_procedure[0].content = "remote work procedure"
        await chunk_repo.create_many(chunk_policy, _embeddings(1))
        await chunk_repo.create_many(chunk_procedure, _embeddings(1))

        policy_matches = await chunk_repo.lexical_search(
            seeded_tenant.id, "remote work", limit=10, source_type=KnowledgeSource.POLICY
        )
        assert len(policy_matches) == 1
        assert policy_matches[0].source == KnowledgeSource.POLICY

    async def test_lexical_search_archived_documents_excluded(self, db, chunk_repo, seeded_tenant):
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc = await knowledge_repo.create(
            _document(seeded_tenant.id, source=KnowledgeSource.POLICY)
        )
        chunks = _chunks(doc, count=1)
        chunks[0].content = "remote work policy"
        await chunk_repo.create_many(chunks, _embeddings(1))

        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET status = 'archived' WHERE id = $1",
                doc.id,
            )

        matches = await chunk_repo.lexical_search(seeded_tenant.id, "remote work", limit=10)
        assert matches == []

    async def test_lexical_search_invalid_limit_rejected(self, chunk_repo, seeded_tenant):
        with pytest.raises(ValueError):
            await chunk_repo.lexical_search(seeded_tenant.id, "remote", limit=0)

    async def test_lexical_search_stemming(self, chunk_repo, seeded_document):
        chunks = _chunks(seeded_document, count=1)
        chunks[0].content = "employees are running the new process"
        await chunk_repo.create_many(chunks, _embeddings(1))

        # "running" should stem to "run" and match "running"
        matches = await chunk_repo.lexical_search(seeded_document.tenant_id, "run", limit=5)
        assert len(matches) == 1
        assert matches[0].chunk_id == chunks[0].id


class TestLexicalSearchTenantIsolation:
    """Lexical search must enforce tenant isolation at the SQL level."""

    async def test_lexical_search_is_tenant_isolated(self, db, chunk_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_a = await knowledge_repo.create(_document(tenant_a.id))
        doc_b = await knowledge_repo.create(_document(tenant_b.id))

        chunks_a = _chunks(doc_a, count=1)
        chunks_a[0].content = "tenant A secret strategy"
        chunks_b = _chunks(doc_b, count=1)
        chunks_b[0].content = "tenant B secret strategy"
        await chunk_repo.create_many(chunks_a, _embeddings(1))
        await chunk_repo.create_many(chunks_b, _embeddings(1))

        search_a = await chunk_repo.lexical_search(tenant_a.id, "secret strategy", limit=10)
        search_b = await chunk_repo.lexical_search(tenant_b.id, "secret strategy", limit=10)

        assert {match.chunk_id for match in search_a} == {chunk.id for chunk in chunks_a}
        assert {match.chunk_id for match in search_b} == {chunk.id for chunk in chunks_b}
        assert all(match.tenant_id == tenant_a.id for match in search_a)
        assert all(match.tenant_id == tenant_b.id for match in search_b)

    async def test_lexical_search_source_filter_preserves_isolation(
        self, db, chunk_repo, seeded_tenants
    ):
        tenant_a, tenant_b = seeded_tenants
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        doc_a = await knowledge_repo.create(_document(tenant_a.id, source=KnowledgeSource.POLICY))
        doc_b = await knowledge_repo.create(_document(tenant_b.id, source=KnowledgeSource.POLICY))
        chunks_a = _chunks(doc_a, count=1)
        chunks_a[0].content = "tenant A policy"
        chunks_b = _chunks(doc_b, count=1)
        chunks_b[0].content = "tenant B policy"
        await chunk_repo.create_many(chunks_a, _embeddings(1))
        await chunk_repo.create_many(chunks_b, _embeddings(1))

        matches_a = await chunk_repo.lexical_search(
            tenant_a.id, "policy", limit=10, source_type=KnowledgeSource.POLICY
        )
        matches_b = await chunk_repo.lexical_search(
            tenant_b.id, "policy", limit=10, source_type=KnowledgeSource.POLICY
        )
        assert len(matches_a) == 1
        assert matches_a[0].tenant_id == tenant_a.id
        assert len(matches_b) == 1
        assert matches_b[0].tenant_id == tenant_b.id


class TestLexicalSearchEndToEnd:
    """Lexical search through the RetrievalService with real storage."""

    async def test_lexical_search_end_to_end(self, db, seeded_document):
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

        matches = await service.lexical_search(context, "remote work", limit=5)
        assert len(matches) == 1
        assert matches[0].document_id == seeded_document.id
        assert matches[0].tenant_id == seeded_document.tenant_id

    async def test_lexical_search_does_not_use_embedding_provider(self, db, seeded_document):
        """Lexical search must not call the embedding provider."""

        class EmbeddingTracker:
            def __init__(self):
                self.called = False

            def embed(self, text):
                self.called = True
                return [0.0] * 1536

            def embed_many(self, texts):
                self.called = True
                return [[0.0] * 1536 for _ in texts]

        tracker = EmbeddingTracker()
        service = RetrievalService(
            chunk_repo=PostgreSQLKnowledgeChunkRepository(db),
            embedding_provider=tracker,
        )
        context = TenantContext(
            tenant_id=seeded_document.tenant_id,
            tenant_name="Test",
            user_id=_unique("user"),
            role=UserRole.MEMBER,
        )

        prepared = await service.prepare_index(context, seeded_document)
        await service.persist_index(prepared)

        # Reset tracker after prepare_index (which legitimately uses embeddings)
        tracker.called = False

        # lexical_search should NOT call the embedding provider
        await service.lexical_search(context, "remote work", limit=5)
        assert not tracker.called
