"""Tests for the Approved Context Contract (Secure RAG semantic retrieval).

The contract is the ONLY representation a future Unified
Intelligence/LLM layer may consume. These tests prove:

- the contract and its items carry sanitized content + provenance with
  deterministic citations, and validate their own invariants
- ``approved_search`` builds the contract from tenant-scoped retrieval
  results using the trusted tenant exclusively
- a match outside the trusted tenant fails closed (invariant violation)
- no-match retrieval returns a safe empty contract (no invented context)
- embedding failures propagate: no contract is produced
- ordering and scores are preserved from the retrieval layer
"""

import uuid
from typing import List

import pytest

from arc.domain.models import (
    ApprovedContext,
    ApprovedContextItem,
    ApprovedContextSecurityMetadata,
    KnowledgeMatch,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.embeddings import EMBEDDING_DIMENSIONS, EmbeddingError
from arc.services.retrieval import RetrievalService


class FakeChunkRepository:
    """In-memory KnowledgeChunkRepository capturing search operations."""

    def __init__(self):
        self.searches = []
        self.search_results = []
        self.lexical_searches = []
        self.lexical_search_results = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return self.search_results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return self.lexical_search_results


class DeterministicFakeProvider:
    """Provider that maps every text to a fixed one-hot vector."""

    def embed(self, text: str) -> List[float]:
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(text) for text in texts]


class ExplodingProvider:
    """Provider that always fails: proves the fail-closed search path."""

    def embed(self, text: str) -> List[float]:
        raise EmbeddingError("embedding provider unavailable")

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        raise EmbeddingError("embedding provider unavailable")


def _match(tenant_id: str = "tenant-1", sequence: int = 0, **overrides) -> KnowledgeMatch:
    values = dict(
        chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
        document_id=f"doc-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        content="approved remote work policy",
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook",
        document_version=1,
        sequence=sequence,
        similarity=0.9,
    )
    values.update(overrides)
    return KnowledgeMatch(**values)


def _context(tenant_id: str = "tenant-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Acme",
        user_id="user-1",
        role=UserRole.MEMBER,
    )


def _service(repo: FakeChunkRepository) -> RetrievalService:
    return RetrievalService(repo, embedding_provider=DeterministicFakeProvider())


def _item(**overrides) -> ApprovedContextItem:
    values = dict(
        document_id="doc-1",
        chunk_id="chunk-1",
        content="approved remote work policy",
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook",
        document_version=1,
        sequence=0,
        relevance_score=0.9,
        citation_reference="doc-1#c0",
    )
    values.update(overrides)
    return ApprovedContextItem(**values)


class TestApprovedContextItemDomain:
    def test_item_requires_identifiers(self):
        with pytest.raises(ValueError):
            _item(document_id="")
        with pytest.raises(ValueError):
            _item(chunk_id="")
        with pytest.raises(ValueError):
            _item(content="")
        with pytest.raises(ValueError):
            _item(provenance="")
        with pytest.raises(ValueError):
            _item(citation_reference="")

    def test_item_rejects_negative_sequence_and_bad_version(self):
        with pytest.raises(ValueError):
            _item(sequence=-1)
        with pytest.raises(ValueError):
            _item(document_version=0)

    def test_item_rejects_non_float_relevance_score(self):
        with pytest.raises(ValueError):
            _item(relevance_score="high")


class TestApprovedContextDomain:
    def test_context_requires_identifiers_and_query(self):
        security = ApprovedContextSecurityMetadata(tenant_id="tenant-1")
        with pytest.raises(ValueError):
            ApprovedContext(
                request_id="",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="q",
                retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
                security_metadata=security,
            )
        with pytest.raises(ValueError):
            ApprovedContext(
                request_id="r1",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="   ",
                retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
                security_metadata=security,
            )

    def test_context_security_metadata_must_match_tenant(self):
        with pytest.raises(ValueError):
            ApprovedContext(
                request_id="r1",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="q",
                retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
                security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-2"),
            )


class TestApprovedSearch:
    async def test_builds_contract_from_retrieval_matches(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(sequence=2, provenance="Policy handbook 2026")]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work", limit=3)

        assert isinstance(contract, ApprovedContext)
        assert contract.request_id
        assert contract.tenant_id == "tenant-1"
        assert contract.principal_id == "user-1"
        assert contract.query == "remote work"
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF
        assert contract.security_metadata.tenant_id == "tenant-1"
        assert contract.security_metadata.authorization_status == "approved"
        assert contract.security_metadata.pii_status == "sanitized"
        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3, None)]
        assert repo.lexical_searches == [("tenant-1", "remote work", 3, None)]

        item = contract.items[0]
        assert isinstance(item, ApprovedContextItem)
        assert item.document_id == repo.search_results[0].document_id
        assert item.chunk_id == repo.search_results[0].chunk_id
        assert item.content == "approved remote work policy"
        assert item.source == KnowledgeSource.POLICY
        assert item.provenance == "Policy handbook 2026"
        assert item.document_version == 1
        assert item.sequence == 2
        assert item.citation_reference == f"{item.document_id}#c2"

    async def test_preserves_ordering_and_scores(self):
        repo = FakeChunkRepository()
        match_a = _match(sequence=0, similarity=0.9, chunk_id="chunk-a")
        match_b = _match(sequence=1, similarity=0.5, chunk_id="chunk-b")
        repo.search_results = [match_a, match_b]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert [item.sequence for item in contract.items] == [0, 1]
        from arc.services.retrieval import ReciprocalRankFusion

        rrf_scores = ReciprocalRankFusion.scores([match_a, match_b], [])
        assert contract.items[0].relevance_score == rrf_scores["chunk-a"]
        assert contract.items[1].relevance_score == rrf_scores["chunk-b"]

    async def test_no_match_returns_safe_empty_contract(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert contract.items == []
        assert contract.tenant_id == "tenant-1"
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_uses_trusted_tenant_only(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(tenant_id="tenant-a")]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context("tenant-a"), "remote work")

        assert repo.searches[0][0] == "tenant-a"
        assert repo.lexical_searches[0][0] == "tenant-a"
        assert contract.tenant_id == "tenant-a"

    async def test_cross_tenant_match_fails_closed(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(tenant_id="tenant-b")]
        repo.lexical_search_results = []
        service = _service(repo)

        with pytest.raises(RuntimeError):
            await service.approved_search(_context("tenant-a"), "remote work")

    async def test_embedding_failure_propagates_without_contract(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=ExplodingProvider())

        with pytest.raises(EmbeddingError):
            await service.approved_search(_context(), "remote work")
        assert repo.searches == []
        assert repo.lexical_searches == []

    async def test_rejects_empty_query_and_invalid_limit(self):
        service = _service(FakeChunkRepository())

        with pytest.raises(ValueError):
            await service.approved_search(_context(), "")
        with pytest.raises(ValueError):
            await service.approved_search(_context(), "   ")
        with pytest.raises(ValueError):
            await service.approved_search(_context(), "remote work", limit=0)


class TestApprovedSearchHybrid:
    async def test_calls_both_dense_and_lexical(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(sequence=0, chunk_id="dense-1")]
        repo.lexical_search_results = [_match(sequence=0, chunk_id="lex-1")]
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work", limit=3)

        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3, None)]
        assert repo.lexical_searches == [("tenant-1", "remote work", 3, None)]
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_fuses_overlapping_chunks(self):
        repo = FakeChunkRepository()
        shared = _match(sequence=0, chunk_id="shared-chunk", document_id="doc-1")
        repo.search_results = [shared]
        repo.lexical_search_results = [
            _match(sequence=1, chunk_id="other-chunk", document_id="doc-2")
        ]
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        chunk_ids = [item.chunk_id for item in contract.items]
        assert "shared-chunk" in chunk_ids
        assert "other-chunk" in chunk_ids

    async def test_rrf_score_is_used_not_raw_similarity(self):
        dense_match = _match(sequence=0, chunk_id="chunk-a", similarity=0.99)
        lexical_match = _match(sequence=0, chunk_id="chunk-a", similarity=0.10)
        repo = FakeChunkRepository()
        repo.search_results = [dense_match]
        repo.lexical_search_results = [lexical_match]
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert len(contract.items) == 1
        assert contract.items[0].relevance_score != 0.99
        assert contract.items[0].relevance_score != 0.10
        expected = 1.0 / (60 + 1) + 1.0 / (60 + 1)
        assert abs(contract.items[0].relevance_score - expected) < 1e-9

    async def test_dense_only_fallback(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(sequence=0, chunk_id="dense-only")]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "dense-only"
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_lexical_only_fallback(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = [_match(sequence=0, chunk_id="lex-only")]
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "lex-only"
        assert contract.retrieval_method == RetrievalMethod.HYBRID_RRF

    async def test_cross_tenant_fused_match_fails_closed(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(tenant_id="tenant-a", chunk_id="dense-1")]
        repo.lexical_search_results = [_match(tenant_id="tenant-b", chunk_id="lex-1")]
        service = _service(repo)

        with pytest.raises(RuntimeError):
            await service.approved_search(_context("tenant-a"), "remote work")

    async def test_source_type_passed_to_both_retrieval_paths(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = _service(repo)

        await service.approved_search(
            _context("tenant-1"), "remote work", limit=3, source_type=KnowledgeSource.POLICY
        )

        assert repo.searches[0][3] == KnowledgeSource.POLICY
        assert repo.lexical_searches[0][3] == KnowledgeSource.POLICY

    async def test_security_metadata_preserved(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context("tenant-1"), "remote work")

        assert contract.security_metadata.tenant_id == "tenant-1"
        assert contract.security_metadata.authorization_status == "approved"
        assert contract.security_metadata.pii_status == "sanitized"


class TestRelevanceFloor:
    """Relevance threshold filtering (PRD-17, issue #210).

    The floor is applied to dense cosine similarity, which is a
    comparable relevance signal.  Lexical-only matches are not floored
    because their score is ts_rank (incompatible scale).
    """

    async def test_dense_below_threshold_excluded(self):
        """Chunks in dense with low cosine similarity are filtered out."""
        repo = FakeChunkRepository()
        low_sim = _match(sequence=0, chunk_id="low-sim", similarity=0.2)
        repo.search_results = [low_sim]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        assert contract.items == []

    async def test_dense_above_threshold_kept(self):
        """Chunks in dense with cosine similarity above threshold are kept."""
        repo = FakeChunkRepository()
        high_sim = _match(sequence=0, chunk_id="high-sim", similarity=0.85)
        repo.search_results = [high_sim]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "high-sim"

    async def test_lexical_only_not_floored(self):
        """Chunks in lexical only pass through regardless of threshold."""
        repo = FakeChunkRepository()
        repo.search_results = []
        lex_only = _match(sequence=0, chunk_id="lex-only")
        repo.lexical_search_results = [lex_only]
        service = _service(repo)

        # Even a very high threshold does not remove lexical-only chunks
        contract = await service.approved_search(_context(), "query", min_relevance_score=0.99)

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "lex-only"

    async def test_mixed_dense_and_lexical(self):
        """Dense filtered by cosine; lexical-only passes through."""
        repo = FakeChunkRepository()
        good = _match(sequence=0, chunk_id="good", similarity=0.8)
        bad = _match(sequence=1, chunk_id="bad", similarity=0.1)
        lex = _match(sequence=2, chunk_id="lex-only", similarity=0.5)
        repo.search_results = [good, bad]
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        chunk_ids = [item.chunk_id for item in contract.items]
        assert "good" in chunk_ids
        assert "bad" not in chunk_ids
        assert "lex-only" in chunk_ids

    async def test_all_dense_below_threshold_returns_empty(self):
        """When all dense results are below threshold, only lexical remains."""
        repo = FakeChunkRepository()
        repo.search_results = [
            _match(sequence=i, chunk_id=f"dense-{i}", similarity=0.1) for i in range(3)
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        assert contract.items == []

    async def test_threshold_is_configurable(self):
        """Custom threshold filters differently than default."""
        repo = FakeChunkRepository()
        match = _match(sequence=0, chunk_id="chunk-a", similarity=0.3)
        repo.search_results = [match]
        repo.lexical_search_results = []
        service = _service(repo)

        # Default threshold (0.01): similarity=0.3 → included
        contract_default = await service.approved_search(_context(), "query")
        assert len(contract_default.items) == 1

        # Threshold above similarity: excluded
        contract_high = await service.approved_search(_context(), "query", min_relevance_score=0.5)
        assert contract_high.items == []

    async def test_default_threshold_is_001(self):
        """Default threshold documents the boundary value."""
        import inspect

        sig = inspect.signature(RetrievalService.approved_search)
        assert sig.parameters["min_relevance_score"].default == 0.01

    async def test_filtered_items_carry_rrf_scores(self):
        """Remaining items have RRF fused scores, not raw cosine similarity."""
        repo = FakeChunkRepository()
        shared = _match(sequence=0, chunk_id="shared-both", similarity=0.9)
        lex_only = _match(sequence=1, chunk_id="lex-only", similarity=0.5)
        repo.search_results = [shared]
        repo.lexical_search_results = [shared, lex_only]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query")
        assert len(contract.items) == 2

        scores = {item.chunk_id: item.relevance_score for item in contract.items}
        expected_shared = 1.0 / (60 + 1) + 1.0 / (60 + 1)
        expected_lex_only = 1.0 / (60 + 2)
        assert abs(scores["shared-both"] - expected_shared) < 1e-9
        assert abs(scores["lex-only"] - expected_lex_only) < 1e-9
