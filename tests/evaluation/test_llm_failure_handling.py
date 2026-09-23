"""LLM evaluation: failure handling (Issue #139, V2-ADR-023).

5 deterministic cases testing correct failure propagation:
LLM errors, embedding errors, no-context, invalid inputs.
"""

import pytest

from arc.domain.models import (
    ApprovedContext,
    ApprovedContextItem,
    ApprovedContextSecurityMetadata,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.embeddings import EmbeddingError
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import DeterministicLlmProvider, LlmError


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


class FailingLlmProvider:
    """LLM provider that always raises LlmError."""

    def complete(self, prompt):
        raise LlmError("Simulated LLM failure")

    @property
    def last_usage(self):
        return None


class FailingEmbeddingProvider:
    """Embedding provider that always raises EmbeddingError."""

    def embed(self, text):
        raise EmbeddingError("Simulated embedding failure")

    def embed_many(self, texts):
        raise EmbeddingError("Simulated embedding failure")


class FakeChunkRepository:
    def __init__(self):
        self.searches = []
        self.lexical_searches = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return []

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return []


class FakeRetrievalWithApproved:
    """Retrieval that returns pre-built approved context."""

    def __init__(self, approved):
        self._approved = approved

    async def approved_search(self, context, query, limit=5, source_type=None):
        return self._approved


def _approved_context():
    return ApprovedContext(
        request_id="req-eval",
        tenant_id="tenant-eval",
        principal_id="user-eval",
        query="test",
        retrieval_method=RetrievalMethod.HYBRID_RRF,
        items=[
            ApprovedContextItem(
                document_id="doc-1",
                chunk_id="doc-1-c0",
                content="Test content",
                source=KnowledgeSource.POLICY,
                provenance="Eval",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference="doc-1#c0",
            )
        ],
        security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-eval"),
    )


async def test_llm_error_propagates():
    """LLM error propagates with no partial answer."""
    retrieval = FakeRetrievalWithApproved(_approved_context())
    llm = FailingLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    with pytest.raises(LlmError):
        await intelligence.answer_query(_context(), "test query")


async def test_embedding_error_before_llm():
    """Embedding error propagates before LLM is called."""
    repo = FakeChunkRepository()
    provider = FailingEmbeddingProvider()
    retrieval = __import__(
        "arc.services.retrieval", fromlist=["RetrievalService"]
    ).RetrievalService(repo, embedding_provider=provider)
    llm = DeterministicLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    with pytest.raises(EmbeddingError):
        await intelligence.answer_query(_context(), "test query")


async def test_no_context_llm_never_invoked():
    """No approved context means LLM never invoked."""
    repo = FakeChunkRepository()

    class CountingLlm:
        def __init__(self):
            self.count = 0

        def complete(self, prompt):
            self.count += 1
            return "should not be called"

        @property
        def last_usage(self):
            return None

    from arc.services.embeddings import EMBEDDING_DIMENSIONS

    class FakeProvider:
        def embed(self, text):
            return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

        def embed_many(self, texts):
            return [self.embed(t) for t in texts]

    retrieval = __import__(
        "arc.services.retrieval", fromlist=["RetrievalService"]
    ).RetrievalService(repo, embedding_provider=FakeProvider())
    llm = CountingLlm()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    answer = await intelligence.answer_query(_context(), "test query")

    assert llm.count == 0
    assert answer.answer is None


async def test_empty_query_value_error():
    """Empty query raises ValueError before any service call."""
    retrieval = FakeRetrievalWithApproved(_approved_context())
    llm = DeterministicLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    with pytest.raises(ValueError, match="empty"):
        await intelligence.answer_query(_context(), "")


async def test_non_positive_limit_value_error():
    """Non-positive limit raises ValueError before retrieval."""
    retrieval = FakeRetrievalWithApproved(_approved_context())
    llm = DeterministicLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    with pytest.raises(ValueError, match="positive"):
        await intelligence.answer_query(_context(), "test", limit=0)
