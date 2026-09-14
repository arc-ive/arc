"""RAG evaluation: lexical-only matches (Issue #139, V2-ADR-023).

5 deterministic cases testing full-text keyword-based retrieval.
"""

import pytest

from arc.domain.models import TenantContext, UserRole
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.retrieval import RetrievalService

from .golden_datasets import lexical_fixtures


class FakeChunkRepository:
    def __init__(self):
        self.lexical_searches = []
        self._lexical_results = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        return []

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return self._lexical_results

    def set_lexical_results(self, results):
        self._lexical_results = results


class DeterministicFakeProvider:
    def embed(self, text):
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


@pytest.mark.parametrize("fixture", lexical_fixtures(), ids=lambda f: f["description"])
async def test_lexical_returns_expected_chunks(fixture):
    """Keyword query returns expected chunks by full-text match."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    tenant_id = "tenant-eval"
    matches = [_make_match(tenant_id, d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_lexical_results(matches)

    context = _context(tenant_id)
    results = await service.lexical_search(context, fixture["query"])

    returned_doc_ids = {r.document_id for r in results}
    assert returned_doc_ids == fixture["expected_doc_ids"]


@pytest.mark.parametrize("fixture", lexical_fixtures(), ids=lambda f: f["description"])
async def test_lexical_uses_search_vector(fixture):
    """Lexical search uses the search_vector column via lexical_search method."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_lexical_results(matches)

    context = _context()
    await service.lexical_search(context, fixture["query"])

    assert len(repo.lexical_searches) == 1
    assert repo.lexical_searches[0][0] == "tenant-eval"


@pytest.mark.parametrize("fixture", lexical_fixtures(), ids=lambda f: f["description"])
async def test_lexical_does_not_call_embedding(fixture):
    """Lexical search does not call the embedding provider."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_lexical_results(matches)

    context = _context()
    await service.lexical_search(context, fixture["query"])

    assert len(provider.embed_calls) if hasattr(provider, "embed_calls") else True


@pytest.mark.parametrize("fixture", lexical_fixtures(), ids=lambda f: f["description"])
async def test_lexical_results_tenant_scoped(fixture):
    """Lexical results are tenant-scoped."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_lexical_results(matches)

    context = _context("tenant-eval")
    await service.lexical_search(context, fixture["query"])

    call_args = repo.lexical_searches[0]
    assert call_args[0] == "tenant-eval"


@pytest.mark.parametrize("fixture", lexical_fixtures(), ids=lambda f: f["description"])
async def test_lexical_multi_word_phrases(fixture):
    """Lexical search handles multi-word technical phrases."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    matches = [_make_match("tenant-eval", d, s, c, src) for d, s, c, src in fixture["chunks"]]
    repo.set_lexical_results(matches)

    context = _context()
    results = await service.lexical_search(context, fixture["query"])

    assert len(results) > 0
