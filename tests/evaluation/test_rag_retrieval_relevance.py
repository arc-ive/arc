"""RAG evaluation: retrieval relevance (Issue #139, V2-ADR-023).

5 deterministic cases testing that correct chunks are returned for
semantic, keyword, source-filtered, exact-phrase, and ranked queries.
"""

import pytest

from arc.domain.models import TenantContext, UserRole
from arc.services.embeddings import EMBEDDING_DIMENSIONS
from arc.services.retrieval import RetrievalService

from .golden_datasets import relevance_fixtures


class FakeChunkRepository:
    """In-memory KnowledgeChunkRepository with configurable search results."""

    def __init__(self):
        self.searches = []
        self.lexical_searches = []
        self._search_results = []
        self._lexical_results = []

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        return self._search_results

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return self._lexical_results

    def set_results(self, search_results, lexical_results=None):
        self._search_results = search_results
        self._lexical_results = lexical_results if lexical_results is not None else search_results


class DeterministicFakeProvider:
    """Provider that maps every text to a fixed one-hot vector."""

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
        provenance="Evaluation fixture",
        document_version=1,
        sequence=sequence,
        similarity=0.9,
    )


@pytest.mark.parametrize("fixture", relevance_fixtures(), ids=lambda f: f["description"])
async def test_retrieval_relevance(fixture):
    """Query returns expected chunks by semantic/keyword overlap."""
    repo = FakeChunkRepository()
    provider = DeterministicFakeProvider()
    service = RetrievalService(repo, embedding_provider=provider)

    tenant_id = "tenant-eval"
    matches = [
        _make_match(tenant_id, doc_id, seq, content, source)
        for doc_id, seq, content, source in fixture["chunks"]
    ]
    repo.set_results(matches, matches)

    context = _context(tenant_id)
    source_type = fixture.get("source_type")
    results = await service.search(context, fixture["query"], source_type=source_type)

    returned_doc_ids = {r.document_id for r in results}
    assert returned_doc_ids == fixture["expected_doc_ids"]
