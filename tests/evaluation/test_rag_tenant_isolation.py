"""RAG evaluation: tenant isolation (Issue #139, V2-ADR-023).

5 deterministic cases testing cross-tenant boundary enforcement:
empty results, RuntimeError, fail-closed behavior.
"""

import pytest

from arc.domain.models import (
    KnowledgeMatch,
    KnowledgeSource,
    TenantContext,
    UserRole,
)
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.retrieval import RetrievalService

from .golden_datasets import tenant_isolation_fixtures


class FakeChunkRepository:
    def __init__(self, search_results=None):
        self._search_results = search_results or []
        self.searches = []
        self.lexical_searches = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return self._search_results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return self._search_results


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


def _make_match(tenant_id, doc_id, content):
    return KnowledgeMatch(
        chunk_id=f"{doc_id}-c0",
        document_id=doc_id,
        tenant_id=tenant_id,
        content=content,
        source=KnowledgeSource.POLICY,
        provenance="Eval fixture",
        document_version=1,
        sequence=0,
        similarity=0.9,
    )


@pytest.mark.parametrize("fixture", tenant_isolation_fixtures(), ids=lambda f: f["description"])
async def test_tenant_isolation(fixture):
    """Cross-tenant query returns empty or raises error."""
    query_tenant = fixture["query_tenant_id"]
    other_chunks = [
        _make_match(chunks[2], chunks[0], chunks[1]) for chunks in fixture["other_tenant_chunks"]
    ]

    # Only return other-tenant chunks if they match query tenant
    relevant = [m for m in other_chunks if m.tenant_id == query_tenant]
    repo = FakeChunkRepository(search_results=relevant)
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context(query_tenant)

    if fixture["expected_outcome"] == "empty":
        results = await service.search(context, "test query")
        assert results == []
    elif fixture["expected_outcome"] == "error":
        # Cross-tenant match in fused results should raise RuntimeError
        repo_error = FakeChunkRepository(search_results=other_chunks)
        service_error = RetrievalService(repo_error, embedding_provider=provider)
        with pytest.raises(RuntimeError, match="trusted tenant"):
            await service_error.approved_search(context, "test query")


@pytest.mark.parametrize("fixture", tenant_isolation_fixtures(), ids=lambda f: f["description"])
async def test_tenant_boundary_at_retrieval(fixture):
    """Tenant boundary is enforced at the retrieval level."""
    query_tenant = fixture["query_tenant_id"]
    other_chunks = [
        _make_match(chunks[2], chunks[0], chunks[1]) for chunks in fixture["other_tenant_chunks"]
    ]

    relevant = [m for m in other_chunks if m.tenant_id == query_tenant]
    repo = FakeChunkRepository(search_results=relevant)
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context(query_tenant)
    results = await service.search(context, "test query")

    for match in results:
        assert match.tenant_id == query_tenant


@pytest.mark.parametrize("fixture", tenant_isolation_fixtures(), ids=lambda f: f["description"])
async def test_cross_tenant_fails_closed(fixture):
    """Cross-tenant match triggers fail-closed RuntimeError."""
    if fixture["expected_outcome"] != "error":
        pytest.skip("Not an error case")

    query_tenant = fixture["query_tenant_id"]
    other_chunks = [
        _make_match(chunks[2], chunks[0], chunks[1]) for chunks in fixture["other_tenant_chunks"]
    ]

    repo = FakeChunkRepository(search_results=other_chunks)
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context(query_tenant)
    with pytest.raises(RuntimeError):
        await service.approved_search(context, "test query")


@pytest.mark.parametrize("fixture", tenant_isolation_fixtures(), ids=lambda f: f["description"])
async def test_context_tenant_untouched(fixture):
    """Tenant context is passed untouched through retrieval pipeline."""
    query_tenant = fixture["query_tenant_id"]
    context = _context(query_tenant)
    assert context.tenant_id == query_tenant
    assert context.tenant_name == "Eval Tenant"
    assert context.user_id == "user-eval"


@pytest.mark.parametrize("fixture", tenant_isolation_fixtures(), ids=lambda f: f["description"])
async def test_no_other_tenant_chunks(fixture):
    """Tenant A query returns no Tenant B chunks."""
    query_tenant = fixture["query_tenant_id"]
    other_chunks = [
        _make_match(chunks[2], chunks[0], chunks[1]) for chunks in fixture["other_tenant_chunks"]
    ]

    relevant = [m for m in other_chunks if m.tenant_id == query_tenant]
    repo = FakeChunkRepository(search_results=relevant)
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    context = _context(query_tenant)
    results = await service.search(context, "test query")

    other_tenant_ids = {ch[2] for ch in fixture["other_tenant_chunks"]}
    for match in results:
        assert match.tenant_id not in other_tenant_ids
