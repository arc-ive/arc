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

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5):
        self.searches.append((tenant_id, query_embedding, limit))
        return self.search_results


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
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work", limit=3)

        assert isinstance(contract, ApprovedContext)
        assert contract.request_id
        assert contract.tenant_id == "tenant-1"
        assert contract.principal_id == "user-1"
        assert contract.query == "remote work"
        assert contract.retrieval_method == RetrievalMethod.DENSE_SEMANTIC
        assert contract.security_metadata.tenant_id == "tenant-1"
        assert contract.security_metadata.authorization_status == "approved"
        assert contract.security_metadata.pii_status == "sanitized"
        assert repo.searches == [("tenant-1", [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), 3)]

        item = contract.items[0]
        assert isinstance(item, ApprovedContextItem)
        assert item.document_id == repo.search_results[0].document_id
        assert item.chunk_id == repo.search_results[0].chunk_id
        assert item.content == "approved remote work policy"
        assert item.source == KnowledgeSource.POLICY
        assert item.provenance == "Policy handbook 2026"
        assert item.document_version == 1
        assert item.sequence == 2
        assert item.relevance_score == 0.9
        assert item.citation_reference == f"{item.document_id}#c2"

    async def test_preserves_ordering_and_scores(self):
        repo = FakeChunkRepository()
        repo.search_results = [
            _match(sequence=0, similarity=0.9),
            _match(sequence=1, similarity=0.5),
        ]
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert [item.sequence for item in contract.items] == [0, 1]
        assert [item.relevance_score for item in contract.items] == [0.9, 0.5]

    async def test_no_match_returns_safe_empty_contract(self):
        repo = FakeChunkRepository()
        repo.search_results = []
        service = _service(repo)

        contract = await service.approved_search(_context(), "remote work")

        assert contract.items == []
        assert contract.tenant_id == "tenant-1"
        assert contract.retrieval_method == RetrievalMethod.DENSE_SEMANTIC

    async def test_uses_trusted_tenant_only(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(tenant_id="tenant-a")]
        service = _service(repo)

        contract = await service.approved_search(_context("tenant-a"), "remote work")

        assert repo.searches[0][0] == "tenant-a"
        assert contract.tenant_id == "tenant-a"

    async def test_cross_tenant_match_fails_closed(self):
        repo = FakeChunkRepository()
        repo.search_results = [_match(tenant_id="tenant-b")]
        service = _service(repo)

        with pytest.raises(RuntimeError):
            await service.approved_search(_context("tenant-a"), "remote work")

    async def test_embedding_failure_propagates_without_contract(self):
        repo = FakeChunkRepository()
        service = RetrievalService(repo, embedding_provider=ExplodingProvider())

        with pytest.raises(EmbeddingError):
            await service.approved_search(_context(), "remote work")
        assert repo.searches == []

    async def test_rejects_empty_query_and_invalid_limit(self):
        service = _service(FakeChunkRepository())

        with pytest.raises(ValueError):
            await service.approved_search(_context(), "")
        with pytest.raises(ValueError):
            await service.approved_search(_context(), "   ")
        with pytest.raises(ValueError):
            await service.approved_search(_context(), "remote work", limit=0)
