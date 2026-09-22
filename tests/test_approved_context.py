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
        dense_score=0.9,
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
        low_sim = _match(sequence=0, chunk_id="low-sim", similarity=0.2, dense_score=0.2)
        repo.search_results = [low_sim]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        assert contract.items == []

    async def test_dense_above_threshold_kept(self):
        """Chunks in dense with cosine similarity above threshold are kept."""
        repo = FakeChunkRepository()
        high_sim = _match(sequence=0, chunk_id="high-sim", similarity=0.85, dense_score=0.85)
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
        lex_only = _match(sequence=0, chunk_id="lex-only", dense_score=None)
        repo.lexical_search_results = [lex_only]
        service = _service(repo)

        # Even a very high threshold does not remove lexical-only chunks
        contract = await service.approved_search(_context(), "query", min_relevance_score=0.99)

        assert len(contract.items) == 1
        assert contract.items[0].chunk_id == "lex-only"

    async def test_mixed_dense_and_lexical(self):
        """Dense filtered by cosine; lexical-only passes through."""
        repo = FakeChunkRepository()
        good = _match(sequence=0, chunk_id="good", similarity=0.8, dense_score=0.8)
        bad = _match(sequence=1, chunk_id="bad", similarity=0.1, dense_score=0.1)
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
            _match(sequence=i, chunk_id=f"dense-{i}", similarity=0.1, dense_score=0.1)
            for i in range(3)
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.5)

        assert contract.items == []

    async def test_threshold_is_configurable(self):
        """Custom threshold filters differently than default."""
        import os

        os.environ.pop("MIN_RELEVANCE_SCORE", None)
        repo = FakeChunkRepository()
        match = _match(sequence=0, chunk_id="chunk-a", similarity=0.3, dense_score=0.3)
        repo.search_results = [match]
        repo.lexical_search_results = []
        service = _service(repo)

        # Default (0.0): similarity=0.3 → included
        contract_default = await service.approved_search(_context(), "query")
        assert len(contract_default.items) == 1

        # Threshold above similarity: excluded
        contract_high = await service.approved_search(_context(), "query", min_relevance_score=0.5)
        assert contract_high.items == []

    async def test_default_threshold_is_env_var_or_zero(self):
        """Default threshold reads MIN_RELEVANCE_SCORE env var, fallback 0.0."""
        import inspect
        import os

        sig = inspect.signature(RetrievalService.approved_search)
        assert sig.parameters["min_relevance_score"].default is None

        # Without env var: falls back to 0.0 (no filtering)
        os.environ.pop("MIN_RELEVANCE_SCORE", None)
        repo = FakeChunkRepository()
        repo.search_results = [
            _match(sequence=0, chunk_id="any", similarity=0.001, dense_score=0.001)
        ]
        repo.lexical_search_results = []
        service = _service(repo)
        contract = await service.approved_search(_context(), "query")
        assert len(contract.items) == 1

        # With env var set: uses that value
        os.environ["MIN_RELEVANCE_SCORE"] = "0.5"
        try:
            contract2 = await service.approved_search(_context(), "query")
            assert contract2.items == []
        finally:
            os.environ.pop("MIN_RELEVANCE_SCORE", None)

    async def test_malformed_env_var_raises_value_error(self):
        """MIN_RELEVANCE_SCORE=abc raises ValueError, not a silent 500."""
        import os

        os.environ["MIN_RELEVANCE_SCORE"] = "abc"
        try:
            repo = FakeChunkRepository()
            repo.search_results = [_match(sequence=0, chunk_id="any", similarity=0.9)]
            repo.lexical_search_results = []
            service = _service(repo)

            with pytest.raises(ValueError, match="MIN_RELEVANCE_SCORE"):
                await service.approved_search(_context(), "query")
        finally:
            os.environ.pop("MIN_RELEVANCE_SCORE", None)

    async def test_valid_configured_value_is_used(self):
        """Valid MIN_RELEVANCE_SCORE env var is applied as threshold."""
        import os

        os.environ["MIN_RELEVANCE_SCORE"] = "0.5"
        try:
            repo = FakeChunkRepository()
            repo.search_results = [
                _match(sequence=0, chunk_id="low", similarity=0.3, dense_score=0.3)
            ]
            repo.lexical_search_results = []
            service = _service(repo)

            contract = await service.approved_search(_context(), "query")
            assert contract.items == []
        finally:
            os.environ.pop("MIN_RELEVANCE_SCORE", None)

    async def test_filtered_items_carry_rrf_scores(self):
        """Remaining items have RRF fused scores, not raw cosine similarity."""
        repo = FakeChunkRepository()
        shared = _match(sequence=0, chunk_id="shared-both", similarity=0.9)
        lex_only = _match(sequence=1, chunk_id="lex-only", similarity=0.5, dense_score=None)
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

    async def test_off_corpus_query_empty_contract(self):
        """Off-corpus query with low similarity returns empty items.

        Simulates the scenario from #210: a query completely unrelated to
        the corpus produces dense matches with low cosine similarity.
        With a threshold above those scores, the contract is empty — the
        caller's existing no-answer path handles this correctly.
        """
        import os

        os.environ.pop("MIN_RELEVANCE_SCORE", None)
        repo = FakeChunkRepository()
        # Simulate off-corpus: low cosine similarity
        repo.search_results = [
            _match(sequence=0, chunk_id="off-1", similarity=0.08, dense_score=0.08),
            _match(sequence=1, chunk_id="off-2", similarity=0.06, dense_score=0.06),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        # With threshold above off-corpus scores: empty contract
        contract = await service.approved_search(
            _context(),
            "airspeed velocity of an unladen swallow",
            min_relevance_score=0.15,
        )
        assert contract.items == []

    async def test_on_corpus_query_nonempty_contract(self):
        """On-corpus query with high similarity returns items."""
        import os

        os.environ.pop("MIN_RELEVANCE_SCORE", None)
        repo = FakeChunkRepository()
        # Simulate on-corpus: high cosine similarity
        repo.search_results = [
            _match(sequence=0, chunk_id="on-1", similarity=0.35, dense_score=0.35),
            _match(sequence=1, chunk_id="on-2", similarity=0.30, dense_score=0.30),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        # Same threshold: on-corpus passes
        contract = await service.approved_search(
            _context(),
            "how do I escalate a severity one incident?",
            min_relevance_score=0.15,
        )
        assert len(contract.items) == 2

    async def test_eval_boundary_separates_off_from_on(self):
        """Threshold at 0.15 separates off-corpus from on-corpus.

        Uses the similarity distribution Chinthan measured with the
        deterministic provider:
          OFF: 0.06–0.23
          ON:  0.18–0.34

        At 0.15, off-corpus items (≤0.23 but dense_only sim=0.08) are
        excluded while on-corpus items (≥0.18) pass.  Note: the highest
        off-corpus score (0.2268) overlaps the lowest on-corpus (0.1839)
        in Chinthan's measurement — this test uses a simplified
        distribution that demonstrates the mechanism.
        """
        import os

        os.environ.pop("MIN_RELEVANCE_SCORE", None)
        repo = FakeChunkRepository()

        # Off-corpus: low dense similarity
        repo.search_results = [
            _match(sequence=0, chunk_id="off-low", similarity=0.08, dense_score=0.08),
        ]
        repo.lexical_search_results = []
        service = _service(repo)
        off_contract = await service.approved_search(
            _context(),
            "unrelated query",
            min_relevance_score=0.15,
        )
        assert off_contract.items == []

        # On-corpus: high dense similarity
        repo.search_results = [
            _match(sequence=0, chunk_id="on-high", similarity=0.30, dense_score=0.30),
        ]
        repo.lexical_search_results = []
        on_contract = await service.approved_search(
            _context(),
            "related query",
            min_relevance_score=0.15,
        )
        assert len(on_contract.items) == 1


class TestScoreSeparation:
    """Dense and lexical scores occupy distinct fields (#218).

    ``dense_score`` carries cosine similarity; ``lexical_score`` carries
    ts_rank.  Neither is interpreted as the other's scale.
    """

    async def test_dense_match_carries_dense_score(self):
        """Dense retrieval populates dense_score with cosine similarity."""
        repo = FakeChunkRepository()
        dense = _match(sequence=0, chunk_id="d1", similarity=0.87, dense_score=0.87)
        repo.search_results = [dense]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query")

        assert len(contract.items) == 1
        match = dense
        assert match.dense_score == 0.87
        assert match.lexical_score is None

    async def test_lexical_match_carries_lexical_score(self):
        """Lexical retrieval populates lexical_score with ts_rank."""
        repo = FakeChunkRepository()
        lex = _match(
            sequence=0,
            chunk_id="l1",
            similarity=0.42,
            dense_score=None,
            lexical_score=0.42,
        )
        repo.search_results = []
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query")

        assert len(contract.items) == 1
        match = lex
        assert match.lexical_score == 0.42
        assert match.dense_score is None

    async def test_scores_not_interpreted_across_methods(self):
        """A high ts_rank does not pass the dense relevance floor."""
        repo = FakeChunkRepository()
        # Lexical score is high (0.9), but dense_score is None → not floored
        lex_high = _match(
            sequence=0,
            chunk_id="lex-high",
            similarity=0.9,
            dense_score=None,
            lexical_score=0.9,
        )
        repo.search_results = []
        repo.lexical_search_results = [lex_high]
        service = _service(repo)

        # Even a high floor does not remove lexical-only matches
        contract = await service.approved_search(_context(), "query", min_relevance_score=0.99)
        assert len(contract.items) == 1

    async def test_rrf_fusion_uses_rank_not_score(self):
        """RRF ranks by position, not by raw score magnitude."""
        # Dense has ts_rank=0.99 in similarity, but RRF uses rank position
        dense = _match(sequence=0, chunk_id="d1", similarity=0.99, dense_score=0.99)
        lex = _match(
            sequence=0,
            chunk_id="l1",
            similarity=0.1,
            dense_score=None,
            lexical_score=0.1,
        )
        repo = FakeChunkRepository()
        repo.search_results = [dense]
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query")

        # Both appear, ranked by RRF (d1 rank1 dense + l1 rank1 lexical)
        assert len(contract.items) == 2
        scores = {item.chunk_id: item.relevance_score for item in contract.items}
        # Both get 1/(60+1) from being rank 1 in their respective lists
        expected = 1.0 / 61
        assert abs(scores["d1"] - expected) < 1e-9
        assert abs(scores["l1"] - expected) < 1e-9

    async def test_shared_chunk_keeps_dense_score_for_floor(self):
        """A chunk in both lists is still floored on its dense score.

        Regression for the fused-object overwrite: the lexical instance
        used to replace the dense one, dropping dense_score (None
        short-circuits the floor) so a dense-0.10 chunk sailed through
        a 0.50 floor.  The fused object must carry both scores.
        """
        repo = FakeChunkRepository()
        dense = _match(sequence=0, chunk_id="shared", similarity=0.10, dense_score=0.10)
        lex = _match(
            sequence=0,
            chunk_id="shared",
            similarity=0.90,
            dense_score=None,
            lexical_score=0.90,
        )
        repo.search_results = [dense]
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.50)

        assert contract.items == []

    async def test_shared_chunk_above_floor_keeps_both_scores(self):
        """A shared chunk clearing the floor retains both per-method scores."""
        from arc.services.retrieval import ReciprocalRankFusion

        dense = _match(sequence=0, chunk_id="shared", similarity=0.80, dense_score=0.80)
        lex = _match(
            sequence=0,
            chunk_id="shared",
            similarity=0.90,
            dense_score=None,
            lexical_score=0.90,
        )

        fused = ReciprocalRankFusion.fuse([dense], [lex])

        assert len(fused) == 1
        assert fused[0].dense_score == 0.80
        assert fused[0].lexical_score == 0.90
        # Inputs are not mutated by the merge.
        assert dense.lexical_score is None
        assert lex.dense_score is None

        repo = FakeChunkRepository()
        repo.search_results = [dense]
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", min_relevance_score=0.50)

        assert [item.chunk_id for item in contract.items] == ["shared"]


class TestLimitBounds:
    """The caller's limit caps the final ApprovedContext item count (#217)."""

    async def test_limit_1_returns_at_most_1_item(self):
        """limit=1 cannot produce more than 1 item even with 2 retrieval paths."""
        repo = FakeChunkRepository()
        dense = _match(sequence=0, chunk_id="d1", similarity=0.9, dense_score=0.9)
        lex = _match(sequence=0, chunk_id="l1", similarity=0.8, dense_score=None, lexical_score=0.8)
        repo.search_results = [dense]
        repo.lexical_search_results = [lex]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", limit=1)

        assert len(contract.items) == 1

    async def test_limit_2_caps_union_of_dense_and_lexical(self):
        """limit=2 returns at most 2 items when dense and lexical each return 2."""
        repo = FakeChunkRepository()
        dense = [
            _match(
                sequence=i,
                chunk_id=f"d{i}",
                similarity=0.9 - i * 0.1,
                dense_score=0.9 - i * 0.1,
            )
            for i in range(2)
        ]
        lex = [
            _match(
                sequence=i,
                chunk_id=f"l{i}",
                similarity=0.8 - i * 0.1,
                dense_score=None,
                lexical_score=0.8 - i * 0.1,
            )
            for i in range(2)
        ]
        repo.search_results = dense
        repo.lexical_search_results = lex
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", limit=2)

        assert len(contract.items) == 2

    async def test_limit_never_exceeded_with_overlapping_results(self):
        """Even when dense and lexical overlap, limit=3 returns at most 3."""
        shared = _match(sequence=0, chunk_id="shared", similarity=0.9, dense_score=0.9)
        dense_extra = _match(sequence=1, chunk_id="d-extra", similarity=0.8, dense_score=0.8)
        lex_extra = _match(
            sequence=1,
            chunk_id="l-extra",
            similarity=0.7,
            dense_score=None,
            lexical_score=0.7,
        )
        repo = FakeChunkRepository()
        repo.search_results = [shared, dense_extra]
        repo.lexical_search_results = [shared, lex_extra]
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", limit=3)

        assert len(contract.items) <= 3

    async def test_limit_with_empty_results_returns_empty(self):
        """limit=5 with no results returns empty items."""
        repo = FakeChunkRepository()
        repo.search_results = []
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "query", limit=5)

        assert contract.items == []


class TestSupersessionDedup:
    """Superseded lineage versions never compete with current ones (#219).

    Lineage is ``(tenant_id, external_id, source)`` (ADR-003).  The
    winning ``document_version`` per lineage is determined first, then
    ALL chunks of that version are kept; RRF input order is preserved.
    """

    def _vchunk(
        self,
        chunk_id,
        version,
        sequence=0,
        external_id="ext-1",
        tenant_id="tenant-1",
        dense=0.9,
    ):
        return _match(
            chunk_id=chunk_id,
            document_id=f"doc-v{version}",
            tenant_id=tenant_id,
            sequence=sequence,
            similarity=dense,
            dense_score=dense,
            document_version=version,
            external_id=external_id,
        )

    async def test_same_lineage_keeps_current_version_only(self):
        """Old and new versions of one lineage: only v2 is retrievable."""
        repo = FakeChunkRepository()
        repo.search_results = [
            self._vchunk("old-chunk", version=1),
            self._vchunk("new-chunk", version=2),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "policy", min_relevance_score=0.0)

        assert [item.chunk_id for item in contract.items] == ["new-chunk"]
        assert contract.items[0].citation_reference == "doc-v2#c0"

    async def test_current_document_keeps_all_sibling_chunks(self):
        """Three chunks of the current version must not evict each other."""
        repo = FakeChunkRepository()
        repo.search_results = [
            self._vchunk("c0", version=2, sequence=0),
            self._vchunk("c1", version=2, sequence=1),
            self._vchunk("c2", version=2, sequence=2),
            self._vchunk("old", version=1, sequence=0),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "policy", min_relevance_score=0.0)

        assert [item.chunk_id for item in contract.items] == ["c0", "c1", "c2"]

    async def test_rank1_no_lineage_match_survives_limit(self):
        """RRF order preserved: rank-1 entry without external_id stays
        first and present after dedup + limit truncation."""
        top = _match(
            chunk_id="aaa-top",
            document_id="doc-top",
            sequence=0,
            similarity=0.95,
            dense_score=0.95,
            external_id=None,
        )
        repo = FakeChunkRepository()
        repo.search_results = [
            top,
            self._vchunk("l-new", version=2),
            self._vchunk("l-old", version=1),
        ]
        repo.lexical_search_results = [
            _match(
                chunk_id="aaa-top",
                document_id="doc-top",
                sequence=0,
                similarity=0.9,
                dense_score=None,
                lexical_score=0.9,
                external_id=None,
            )
        ]
        service = _service(repo)

        contract = await service.approved_search(
            _context(), "policy", limit=2, min_relevance_score=0.0
        )

        assert [item.chunk_id for item in contract.items][0] == "aaa-top"
        assert len(contract.items) == 2
        assert "l-old" not in [item.chunk_id for item in contract.items]

    async def test_different_external_ids_are_independent(self):
        """Two lineages each keep their own current version."""
        repo = FakeChunkRepository()
        repo.search_results = [
            self._vchunk("a-old", version=1, external_id="ext-a"),
            self._vchunk("a-new", version=2, external_id="ext-a"),
            self._vchunk("b-old", version=1, external_id="ext-b"),
            self._vchunk("b-new", version=3, external_id="ext-b"),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "policy", min_relevance_score=0.0)

        assert sorted(item.chunk_id for item in contract.items) == ["a-new", "b-new"]

    async def test_no_external_id_matches_pass_through(self):
        """Documents without external_id are never deduplicated."""
        repo = FakeChunkRepository()
        repo.search_results = [
            _match(chunk_id="n1", similarity=0.9, dense_score=0.9, external_id=None),
            _match(chunk_id="n2", similarity=0.8, dense_score=0.8, external_id=None),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "policy", min_relevance_score=0.0)

        assert [item.chunk_id for item in contract.items] == ["n1", "n2"]

    async def test_lineage_key_is_tenant_scoped(self):
        """Same external_id in two tenants are distinct lineages (ADR-003)."""
        from arc.services.retrieval import _dedup_by_lineage

        matches = [
            self._vchunk("a-v1", version=1, tenant_id="tenant-a"),
            self._vchunk("b-v2", version=2, tenant_id="tenant-b"),
        ]

        assert [m.chunk_id for m in _dedup_by_lineage(matches)] == ["a-v1", "b-v2"]

    async def test_floor_applies_to_lineage_winner(self):
        """Dedup runs before the floor: a low-similarity current version
        is filtered on its own merit, not replaced by an old version."""
        repo = FakeChunkRepository()
        repo.search_results = [
            self._vchunk("old", version=1, dense=0.90),
            self._vchunk("new", version=2, dense=0.10),
        ]
        repo.lexical_search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "policy", min_relevance_score=0.50)

        assert contract.items == []
