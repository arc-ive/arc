"""Unit tests for the RetrievalService (Secure RAG retrieval service).

The service is tested with fakes for the chunk repository and embedding
provider so the fail-closed behavior is deterministic:

- embedding failures abort BEFORE any persistence
- dimension mismatches fail fast with a clear error
- the tenant boundary comes exclusively from the trusted context
- empty queries and invalid limits are rejected
"""

import uuid
from typing import List

import pytest

from arc.domain.models import (
    KnowledgeDocument,
    KnowledgeMatch,
    KnowledgeSource,
    KnowledgeStatus,
    TenantContext,
    UserRole,
)
from arc.services.embeddings import EMBEDDING_DIMENSIONS, EmbeddingError
from arc.services.retrieval import RetrievalService


def _unique(prefix: str) -> str:
    return f"rs-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str = "tenant-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Acme",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


def _service(repo=None, **provider_overrides):
    return RetrievalService(
        repo if repo is not None else FakeChunkRepository(),
        embedding_provider=DeterministicFakeProvider(**provider_overrides),
    )


def _document(tenant_id: str, content: str = "approved remote work policy", **overrides):
    values = dict(
        id=_unique("doc"),
        tenant_id=tenant_id,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook",
        version=1,
        status=KnowledgeStatus.ACTIVE,
        content=content,
    )
    values.update(overrides)
    return KnowledgeDocument(**values)


class FakeChunkRepository:
    """In-memory KnowledgeChunkRepository capturing operations."""

    def __init__(self):
        self.persisted = []
        self.searches = []
        self.search_results = []

    async def create_many(self, chunks, embeddings):
        self.persisted.append((chunks, embeddings))
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5):
        self.searches.append((tenant_id, query_embedding, limit))
        return self.search_results


class DeterministicFakeProvider:
    """Provider that maps text to a deterministic one-hot vector."""

    def __init__(self, dimensions=EMBEDDING_DIMENSIONS, fail=False, wrong_dim=False):
        self.dimensions = dimensions
        self.fail = fail
        self.wrong_dim = wrong_dim
        self.embed_calls = []

    def embed(self, text: str) -> List[float]:
        self.embed_calls.append(text)
        if self.fail:
            raise EmbeddingError("embedding provider unavailable")
        vector = [0.0] * self.dimensions
        vector[0] = 1.0 if text else 0.0
        if self.wrong_dim:
            return vector[:-1]
        return vector

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(text) for text in texts]


class TestRetrievalServicePrepare:
    async def test_prepare_index_chunks_and_embeds(self):
        service = _service()
        document = _document("tenant-1", content="approved remote work policy")

        prepared = await service.prepare_index(_context("tenant-1"), document)

        assert prepared is not None
        assert len(prepared.chunks) == 1
        assert len(prepared.embeddings) == 1
        chunk = prepared.chunks[0]
        assert chunk.tenant_id == "tenant-1"
        assert chunk.document_id == document.id
        assert chunk.content == "approved remote work policy"
        assert chunk.sequence == 0

    async def test_prepare_index_uses_sanitized_content_only(self):
        service = _service()
        document = _document("tenant-1", content="approved remote work policy")

        prepared = await service.prepare_index(_context("tenant-1"), document)

        assert prepared.chunks[0].content == document.content
        # Nothing is persisted by prepare_index: persistence happens only
        # after the owning document exists.
        assert service.chunk_repo.persisted == []

    async def test_prepare_index_rejects_document_of_another_tenant(self):
        service = _service()
        document = _document("tenant-b")

        with pytest.raises(ValueError):
            await service.prepare_index(_context("tenant-a"), document)

    async def test_prepare_index_returns_none_for_empty_content(self):
        service = _service()
        document = _document("tenant-1", content="   ")

        assert await service.prepare_index(_context("tenant-1"), document) is None

    async def test_prepare_index_propagates_embedding_failure(self):
        service = _service(fail=True)
        document = _document("tenant-1")

        with pytest.raises(EmbeddingError):
            await service.prepare_index(_context("tenant-1"), document)
        assert service.chunk_repo.persisted == []

    async def test_prepare_index_rejects_wrong_dimension_embeddings(self):
        service = _service(wrong_dim=True)
        document = _document("tenant-1")

        with pytest.raises(EmbeddingError):
            await service.prepare_index(_context("tenant-1"), document)


class TestRetrievalServicePersist:
    async def test_persist_index_delegates_to_repository(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())
        document = _document("tenant-1")
        prepared = await service.prepare_index(_context("tenant-1"), document)

        persisted = await service.persist_index(prepared)

        assert persisted == prepared.chunks
        assert repo.persisted == [(prepared.chunks, prepared.embeddings)]


class TestRetrievalServiceSearch:
    async def test_search_embeds_query_and_uses_trusted_tenant(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())
        match = KnowledgeMatch(
            chunk_id=_unique("chunk"),
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="approved remote work policy",
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            document_version=1,
            similarity=0.9,
        )
        repo.search_results = [match]

        matches = await service.search(_context("tenant-1"), "remote work", limit=3)

        assert matches == [match]
        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3)]

    async def test_search_rejects_empty_query(self):
        service = _service()
        with pytest.raises(ValueError):
            await service.search(_context(), "")
        with pytest.raises(ValueError):
            await service.search(_context(), "   ")

    async def test_search_rejects_invalid_limit(self):
        service = _service()
        with pytest.raises(ValueError):
            await service.search(_context(), "remote", limit=0)

    async def test_search_propagates_embedding_failure(self):
        service = _service(fail=True)
        with pytest.raises(EmbeddingError):
            await service.search(_context(), "remote work")
        assert service.chunk_repo.searches == []

    async def test_search_rejects_wrong_dimension_embedding(self):
        service = _service(wrong_dim=True)
        with pytest.raises(EmbeddingError):
            await service.search(_context(), "remote work")
        assert service.chunk_repo.searches == []
