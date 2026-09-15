"""RAG evaluation: no-match behavior (Issue #139, V2-ADR-023).

5 deterministic cases testing correct behavior when no relevant context
exists: empty results, no LLM invocation, context_used=False.
"""

import pytest

from arc.domain.models import TenantContext, UserRole
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import DeterministicLlmProvider
from arc.services.retrieval import RetrievalService

from .golden_datasets import no_match_fixtures


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


class DeterministicFakeProvider:
    def embed(self, text):
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_many(self, texts):
        return [self.embed(text) for text in texts]


class RecordingLlmProvider:
    """LLM provider that records whether it was called."""

    def __init__(self):
        self.call_count = 0

    def complete(self, prompt):
        self.call_count += 1
        return "This should never be called on no-match"

    @property
    def last_usage(self):
        return None


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


@pytest.mark.parametrize("fixture", no_match_fixtures(), ids=lambda f: f["description"])
async def test_no_match_returns_empty(fixture):
    """Unrelated query returns empty results from retrieval."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context()
    results = await service.search(context, fixture["query"])
    assert results == []


@pytest.mark.parametrize("fixture", no_match_fixtures(), ids=lambda f: f["description"])
async def test_no_match_approved_context_empty(fixture):
    """Empty retrieval produces empty ApprovedContext."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context()
    approved = await service.approved_search(context, fixture["query"])
    assert approved.items == []


@pytest.mark.parametrize("fixture", no_match_fixtures(), ids=lambda f: f["description"])
async def test_no_match_llm_never_invoked(fixture):
    """LLM provider is never called when no context matches."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    retrieval = RetrievalService(repo, embedding_provider=provider)

    llm = RecordingLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    context = _context()
    answer = await intelligence.answer_query(context, fixture["query"])

    assert llm.call_count == 0
    assert answer.context_used is False


@pytest.mark.parametrize("fixture", no_match_fixtures(), ids=lambda f: f["description"])
async def test_no_match_answer_is_none(fixture):
    """Answer is None when no approved context is available."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    retrieval = RetrievalService(repo, embedding_provider=provider)

    llm = DeterministicLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    context = _context()
    answer = await intelligence.answer_query(context, fixture["query"])

    assert answer.answer is None
    assert answer.citations == []


@pytest.mark.parametrize("fixture", no_match_fixtures(), ids=lambda f: f["description"])
async def test_no_match_context_used_false(fixture):
    """context_used is False when no approved context is available."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    retrieval = RetrievalService(repo, embedding_provider=provider)

    llm = DeterministicLlmProvider()
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    context = _context()
    answer = await intelligence.answer_query(context, fixture["query"])

    assert answer.context_used is False
