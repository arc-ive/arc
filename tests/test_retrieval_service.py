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
    RetrievalMethod,
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
        self.lexical_searches = []
        self.lexical_search_results = []

    async def create_many(self, chunks, embeddings):
        self.persisted.append((chunks, embeddings))
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return self.search_results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return self.lexical_search_results


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
            sequence=0,
            similarity=0.9,
        )
        repo.search_results = [match]

        matches = await service.search(_context("tenant-1"), "remote work", limit=3)

        assert matches == [match]
        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3, None)]

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

    async def test_search_passes_source_type_to_repository(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        await service.search(
            _context("tenant-1"), "remote work", limit=3, source_type=KnowledgeSource.POLICY
        )

        assert len(repo.searches) == 1
        tenant_id, _embedding, limit, source_type = repo.searches[0]
        assert tenant_id == "tenant-1"
        assert limit == 3
        assert source_type == KnowledgeSource.POLICY

    async def test_search_no_source_type_passes_none_to_repository(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        await service.search(_context("tenant-1"), "remote work", limit=3)

        assert len(repo.searches) == 1
        tenant_id, _embedding, limit, source_type = repo.searches[0]
        assert tenant_id == "tenant-1"
        assert limit == 3
        assert source_type is None


class TestRetrievalServiceLexicalSearch:
    async def test_lexical_search_delegates_to_repository(self):
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
            sequence=0,
            similarity=0.9,
        )
        repo.lexical_search_results = [match]

        matches = await service.lexical_search(_context("tenant-1"), "remote work", limit=3)

        assert matches == [match]
        assert repo.lexical_searches == [("tenant-1", "remote work", 3, None)]

    async def test_lexical_search_rejects_empty_query(self):
        service = _service()
        with pytest.raises(ValueError):
            await service.lexical_search(_context(), "")
        with pytest.raises(ValueError):
            await service.lexical_search(_context(), "   ")

    async def test_lexical_search_rejects_invalid_limit(self):
        service = _service()
        with pytest.raises(ValueError):
            await service.lexical_search(_context(), "remote", limit=0)

    async def test_lexical_search_does_not_use_embedding_provider(self):
        """Lexical search must NOT call the embedding provider."""
        repo = FakeChunkRepository()
        provider = DeterministicFakeProvider()
        service = RetrievalService(repo, embedding_provider=provider)
        match = KnowledgeMatch(
            chunk_id=_unique("chunk"),
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="approved remote work policy",
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        repo.lexical_search_results = [match]

        await service.lexical_search(_context("tenant-1"), "remote work", limit=3)

        assert provider.embed_calls == []

    async def test_lexical_search_passes_source_type_to_repository(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        await service.lexical_search(
            _context("tenant-1"), "remote work", limit=3, source_type=KnowledgeSource.POLICY
        )

        assert len(repo.lexical_searches) == 1
        tenant_id, _query, limit, source_type = repo.lexical_searches[0]
        assert tenant_id == "tenant-1"
        assert _query == "remote work"
        assert limit == 3
        assert source_type == KnowledgeSource.POLICY

    async def test_lexical_search_no_source_type_passes_none(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        await service.lexical_search(_context("tenant-1"), "remote work", limit=3)

        assert len(repo.lexical_searches) == 1
        tenant_id, _query, limit, source_type = repo.lexical_searches[0]
        assert tenant_id == "tenant-1"
        assert limit == 3
        assert source_type is None


class TestReciprocalRankFusion:
    def test_same_inputs_produce_same_output(self):
        from arc.services.retrieval import ReciprocalRankFusion

        a = _unique("chunk")
        b = _unique("chunk")
        dense = [
            KnowledgeMatch(
                chunk_id=a,
                document_id=_unique("doc"),
                tenant_id="t",
                content="a",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            ),
            KnowledgeMatch(
                chunk_id=b,
                document_id=_unique("doc"),
                tenant_id="t",
                content="b",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=1,
                similarity=0.5,
            ),
        ]
        lexical = [
            KnowledgeMatch(
                chunk_id=b,
                document_id=_unique("doc"),
                tenant_id="t",
                content="b",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=1,
                similarity=0.8,
            ),
            KnowledgeMatch(
                chunk_id=a,
                document_id=_unique("doc"),
                tenant_id="t",
                content="a",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.3,
            ),
        ]

        result1 = ReciprocalRankFusion.fuse(dense, lexical)
        result2 = ReciprocalRankFusion.fuse(dense, lexical)
        assert [m.chunk_id for m in result1] == [m.chunk_id for m in result2]

    def test_rank1_contribution(self):
        from arc.services.retrieval import ReciprocalRankFusion

        scores = ReciprocalRankFusion.scores(
            [
                KnowledgeMatch(
                    chunk_id="c",
                    document_id="d",
                    tenant_id="t",
                    content="x",
                    source=KnowledgeSource.POLICY,
                    provenance="p",
                    document_version=1,
                    sequence=0,
                    similarity=0.9,
                )
            ],
            [],
        )
        assert abs(scores["c"] - 1.0 / 61) < 1e-9

    def test_rank2_contribution(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m1 = KnowledgeMatch(
            chunk_id="c1",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        m2 = KnowledgeMatch(
            chunk_id="c2",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=1,
            similarity=0.5,
        )
        scores = ReciprocalRankFusion.scores([m1, m2], [])
        assert abs(scores["c2"] - 1.0 / 62) < 1e-9

    def test_duplicate_chunk_id_sums_contributions(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m = KnowledgeMatch(
            chunk_id="shared",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        scores = ReciprocalRankFusion.scores([m], [m])
        expected = 1.0 / 61 + 1.0 / 61
        assert abs(scores["shared"] - expected) < 1e-9

    def test_higher_fused_score_ranks_first(self):
        from arc.services.retrieval import ReciprocalRankFusion

        dense = [
            KnowledgeMatch(
                chunk_id="dense-1",
                document_id="d",
                tenant_id="t",
                content="x",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            ),
        ]
        lexical = [
            KnowledgeMatch(
                chunk_id="dense-1",
                document_id="d",
                tenant_id="t",
                content="x",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.8,
            ),
            KnowledgeMatch(
                chunk_id="lex-only",
                document_id="d",
                tenant_id="t",
                content="x",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=1,
                similarity=0.5,
            ),
        ]
        result = ReciprocalRankFusion.fuse(dense, lexical)
        assert result[0].chunk_id == "dense-1"
        assert result[1].chunk_id == "lex-only"

    def test_deterministic_chunk_id_tie_break(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m_a = KnowledgeMatch(
            chunk_id="a",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.5,
        )
        m_b = KnowledgeMatch(
            chunk_id="b",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=1,
            similarity=0.5,
        )
        result = ReciprocalRankFusion.fuse([m_a, m_b], [])
        assert result[0].chunk_id == "a"
        assert result[1].chunk_id == "b"

    def test_dense_only_input(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m = KnowledgeMatch(
            chunk_id="c",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        result = ReciprocalRankFusion.fuse([m], [])
        assert len(result) == 1
        assert result[0].chunk_id == "c"

    def test_lexical_only_input(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m = KnowledgeMatch(
            chunk_id="c",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        result = ReciprocalRankFusion.fuse([], [m])
        assert len(result) == 1
        assert result[0].chunk_id == "c"

    def test_both_empty(self):
        from arc.services.retrieval import ReciprocalRankFusion

        result = ReciprocalRankFusion.fuse([], [])
        assert result == []

    def test_inputs_not_mutated(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m = KnowledgeMatch(
            chunk_id="c",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        dense_copy = [m]
        lexical_copy = [m]
        ReciprocalRankFusion.fuse(dense_copy, lexical_copy)
        assert dense_copy[0].similarity == 0.9
        assert lexical_copy[0].similarity == 0.9

    def test_custom_k_value(self):
        from arc.services.retrieval import ReciprocalRankFusion

        m = KnowledgeMatch(
            chunk_id="c",
            document_id="d",
            tenant_id="t",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        scores = ReciprocalRankFusion.scores([m], [], k=10)
        assert abs(scores["c"] - 1.0 / 11) < 1e-9


class TestRetrievalServiceApprovedSearchHybrid:
    async def test_approved_search_calls_both_retrieval_paths(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())
        dense_match = KnowledgeMatch(
            chunk_id=_unique("chunk"),
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="dense match",
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            document_version=1,
            sequence=0,
            similarity=0.9,
        )
        lexical_match = KnowledgeMatch(
            chunk_id=_unique("chunk"),
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="lexical match",
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            document_version=1,
            sequence=0,
            similarity=0.7,
        )
        repo.search_results = [dense_match]
        repo.lexical_search_results = [lexical_match]

        contract = await service.approved_search(_context("tenant-1"), "remote work", limit=3)

        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3, None)]
        assert repo.lexical_searches == [("tenant-1", "remote work", 3, None)]
        assert len(contract.items) == 2

    async def test_approved_search_returns_hybrid_rrf_method(self):
        from arc.domain.models import RetrievalMethod

        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_approved_search_fused_relevance_score(self):
        dense_match = KnowledgeMatch(
            chunk_id="shared",
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.99,
        )
        lexical_match = KnowledgeMatch(
            chunk_id="shared",
            document_id=_unique("doc"),
            tenant_id="tenant-1",
            content="x",
            source=KnowledgeSource.POLICY,
            provenance="p",
            document_version=1,
            sequence=0,
            similarity=0.10,
        )
        repo = FakeChunkRepository()
        repo.search_results = [dense_match]
        repo.lexical_search_results = [lexical_match]
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert len(contract.items) == 1
        expected = 1.0 / 61 + 1.0 / 61
        assert abs(contract.items[0].relevance_score - expected) < 1e-9

    async def test_approved_search_both_empty(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert contract.items == []
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_approved_search_dense_only_fallback(self):
        repo = FakeChunkRepository()
        repo.search_results = [
            KnowledgeMatch(
                chunk_id="dense-1",
                document_id=_unique("doc"),
                tenant_id="tenant-1",
                content="dense",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            )
        ]
        repo.lexical_search_results = []
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "dense-1"

    async def test_approved_search_lexical_only_fallback(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = [
            KnowledgeMatch(
                chunk_id="lex-1",
                document_id=_unique("doc"),
                tenant_id="tenant-1",
                content="lexical",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            )
        ]
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "lex-1"

    async def test_approved_search_cross_tenant_fused_match_fails_closed(self):
        repo = FakeChunkRepository()
        repo.search_results = [
            KnowledgeMatch(
                chunk_id="dense-1",
                document_id=_unique("doc"),
                tenant_id="tenant-a",
                content="x",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            )
        ]
        repo.lexical_search_results = [
            KnowledgeMatch(
                chunk_id="lex-1",
                document_id=_unique("doc"),
                tenant_id="tenant-b",
                content="x",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                similarity=0.9,
            )
        ]
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        with pytest.raises(RuntimeError):
            await service.approved_search(_context("tenant-a"), "remote work")

    async def test_approved_search_source_type_passed_to_both_paths(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = RetrievalService(repo, embedding_provider=DeterministicFakeProvider())

        await service.approved_search(
            _context("tenant-1"), "remote work", limit=3, source_type=KnowledgeSource.POLICY
        )

        assert repo.searches[0][3] == KnowledgeSource.POLICY
        assert repo.lexical_searches[0][3] == KnowledgeSource.POLICY
