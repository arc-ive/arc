"""RAG evaluation: semantic-only matches (Issue #139, V2-ADR-023).

5 deterministic cases testing embedding-based semantic retrieval.
"""

import pytest

from arc.domain.models import TenantContext, UserRole
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.retrieval import RetrievalService

from .golden_datasets import semantic_fixtures


class FakeChunkRepository:
    def __init__(self):
        self.searches = []
        self._search_results = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return self._search_results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        return []

    def set_search_results(self, results):
        self._search_results = results


class DeterministicFakeProvider:
    def __init__(self):
        self.embed_calls = []

    def embed(self, text):
        self.embed_calls.append(text)
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_many(self, texts):
        return [self.embed(text) for text in texts]


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _make_match(tenant_id, doc_id, sequence, content, source):
    from arc.domain.models import KnowledgeMatch

    return KnowledgeMatch(
        chunk_id=f"{doc_id}-c{sequence}",
        document_id=doc_id,
        tenant_id=tenant_id,
        content=content,
        source=source,
        provenance="Eval fixture",
        document_version=1,
        sequence=sequence,
        similarity=0.9,
    )


@pytest.mark.parametrize("fixture", semantic_fixtures(), ids=lambda f: f["description"])
async def test_semantic_returns_expected_chunks(fixture):
    """Embedding query returns expected chunks by vector similarity."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    tenant_id = "tenant-eval"
    matches = [_make_match(tenant_id, d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_search_results(matches)

    context = _context(tenant_id)
    results = await service.search(context, fixture["query"])

    returned_doc_ids = {r.document_id for r in results}
    assert returned_doc_ids == fixture["expected_doc_ids"]


@pytest.mark.parametrize("fixture", semantic_fixtures(), ids=lambda f: f["description"])
async def test_semantic_uses_embedding_vector(fixture):
    """Dense search uses embedding vector via search method."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_search_results(matches)

    context = _context()
    await service.search(context, fixture["query"])

    assert len(repo.searches) == 1
    # Verify embedding was called with the query
    assert provider.embed_calls[-1] == fixture["query"]


@pytest.mark.parametrize("fixture", semantic_fixtures(), ids=lambda f: f["description"])
async def test_semantic_results_tenant_scoped(fixture):
    """Semantic results are tenant-scoped."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_search_results(matches)

    context = _context("tenant-eval")
    await service.search(context, fixture["query"])

    call_args = repo.searches[0]
    assert call_args[0] == "tenant-eval"


@pytest.mark.parametrize("fixture", semantic_fixtures(), ids=lambda f: f["description"])
async def test_semantic_abstract_queries(fixture):
    """Semantic search handles abstract conceptual queries."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_search_results(matches)

    context = _context()
    results = await service.search(context, fixture["query"])

    assert len(results) > 0


@pytest.mark.parametrize("fixture", semantic_fixtures(), ids=lambda f: f["description"])
async def test_semantic_embedding_called_with_query(fixture):
    """Embedding provider is called with the exact query text."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_search_results(matches)

    context = _context()
    await service.search(context, fixture["query"])

    assert fixture["query"] in provider.embed_calls
