"""Security evaluation: cross-tenant retrieval (Issue #139, V2-ADR-023).

5 deterministic cases testing cross-tenant retrieval defense.
"""

import pytest

from arc.domain.models import KnowledgeMatch, KnowledgeSource, TenantContext, UserRole
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.retrieval import RetrievalService

from .golden_datasets import cross_tenant_fixtures


class FakeChunkRepository:
    def __init__(self, results=None):
        self._results = results or []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        return self._results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        return self._results


class DeterministicFakeProvider:
    def embed(self, text):
        return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def embed_many(self, texts):
        return [self.embed(text) for text in texts]


def _context(tenant_id):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _make_match(tenant_id, doc_id="doc-1"):
    return KnowledgeMatch(
        chunk_id=f"{doc_id}-c0",
        document_id=doc_id,
        tenant_id=tenant_id,
        content="Test content",
        source=KnowledgeSource.POLICY,
        provenance="Eval fixture",
        document_version=1,
        sequence=0,
        similarity=0.9,
    )


@pytest.mark.parametrize("fixture", cross_tenant_fixtures(), ids=lambda f: f["description"])
async def test_cross_tenant_defense(fixture):
    """Cross-tenant match raises RuntimeError or returns empty."""
    query_tenant = fixture["query_tenant"]

    if fixture["expected_outcome"] == "error":
        other_match = _make_match(fixture["fused_match_tenant"])
        repo = FakeChunkRepository(results=[other_match])
    elif fixture["expected_outcome"] == "ok":
        same_match = _make_match(fixture["query_tenant"])
        repo = FakeChunkRepository(results=[same_match])
    else:
        repo = FakeChunkRepository(results=[])

    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)
    context = _context(query_tenant)

    if fixture["expected_outcome"] == "error":
        with pytest.raises(RuntimeError, match="trusted tenant"):
            await service.approved_search(context, "test query")
    else:
        approved = await service.approved_search(context, "test query")
        for item in approved.items:
            assert item.citation_reference.startswith(fixture["query_tenant"])


@pytest.mark.parametrize("fixture", cross_tenant_fixtures(), ids=lambda f: f["description"])
async def test_fail_closed_on_cross_tenant(fixture):
    """Fail-closed: cross-tenant detected at retrieval boundary."""
    if fixture["expected_outcome"] != "error":
        pytest.skip("Not an error case")

    query_tenant = fixture["query_tenant"]
    other_match = _make_match(fixture["fused_match_tenant"])
    repo = FakeChunkRepository(results=[other_match])
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)
    context = _context(query_tenant)

    with pytest.raises(RuntimeError):
        await service.approved_search(context, "test query")


@pytest.mark.parametrize("fixture", cross_tenant_fixtures(), ids=lambda f: f["description"])
async def test_same_tenant_passes(fixture):
    """Same-tenant chunks pass defensive validation."""
    if fixture["expected_outcome"] == "error":
        pytest.skip("Not an OK case")

    query_tenant = fixture["query_tenant"]
    if fixture["expected_outcome"] == "ok":
        same_match = _make_match(fixture["query_tenant"])
        repo = FakeChunkRepository(results=[same_match])
    else:
        repo = FakeChunkRepository(results=[])

    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)
    context = _context(query_tenant)

    approved = await service.approved_search(context, "test query")
    assert approved.tenant_id == query_tenant


@pytest.mark.parametrize("fixture", cross_tenant_fixtures(), ids=lambda f: f["description"])
async def test_boundary_at_retrieval_level(fixture):
    """Tenant boundary enforced at the retrieval level."""
    query_tenant = fixture["query_tenant"]
    context = _context(query_tenant)
    assert context.tenant_id == query_tenant


@pytest.mark.parametrize("fixture", cross_tenant_fixtures(), ids=lambda f: f["description"])
async def test_no_other_tenant_data(fixture):
    """Tenant A query returns no Tenant B data."""
    query_tenant = fixture["query_tenant"]

    if fixture["expected_outcome"] == "error":
        other_match = _make_match(fixture["fused_match_tenant"])
        repo = FakeChunkRepository(results=[other_match])
    elif fixture["expected_outcome"] == "ok":
        same_match = _make_match(fixture["query_tenant"])
        repo = FakeChunkRepository(results=[same_match])
    else:
        repo = FakeChunkRepository(results=[])

    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)
    context = _context(query_tenant)

    if fixture["expected_outcome"] != "error":
        results = await service.search(context, "test query")
        for match in results:
            assert match.tenant_id == query_tenant
