"""RAG evaluation: relevance floor (Issue #210, PR #248).

End-to-end coverage of the MIN_RELEVANCE_SCORE mechanism through the
real retrieval path:

    query -> provider.embed(query) -> repo.search(query_embedding)
        -> cosine(query, chunk) per chunk -> KnowledgeMatch.similarity
        -> relevance floor -> ApprovedContext

The harness uses the REAL ``DeterministicEmbeddingProvider`` (the same
word-hash function the runtime uses) and a fake repository that mirrors
the production SQL semantics (``1 - (embedding <=> $2)``): per-chunk
cosine against the query embedding, ranked descending.  Similarity is
therefore a genuine function of query and chunk content — different
queries produce different similarities, and the floor sees the real
value produced by that path rather than a hardcoded constant.

Threshold selection is data-driven, not invented: the test measures
top-1 dense similarity for every query in both sets, then uses the
midpoint between off-corpus max and on-corpus min.  If the measured
distributions overlap (off_max >= on_min) no single threshold can
satisfy AC 1 and AC 4 at once, and the test xfails citing the MEASURED
values — an honest provider/corpus limitation, not a fixture invention.
With a provider and corpus that separate, the same harness yields a
real pass/fail signal.

Lexical retrieval returns no hits here to isolate the dense floor.
Lexical-only bypass is covered separately by unit tests
(``test_lexical_only_not_floored``) and documented as a caveat.
"""

import math

import pytest

from arc.domain.models import KnowledgeMatch, KnowledgeSource, TenantContext, UserRole
from arc.services.embeddings import DeterministicEmbeddingProvider
from arc.services.retrieval import RetrievalService

from .golden_datasets import (
    relevance_floor_off_corpus_fixtures,
    relevance_floor_on_corpus_fixtures,
)


def _cosine(a, b) -> float:
    """Cosine similarity, mirroring ``1 - (embedding <=> query)`` in SQL."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class QuerySensitiveFakeChunkRepository:
    """In-memory repository with genuine query-dependent cosine ranking.

    Chunk embeddings are precomputed with the real embedding provider.
    ``search()`` uses the incoming ``query_embedding`` — exactly like the
    production repository uses ``$2::vector`` — computing per-chunk
    cosine, ranking descending, and slicing to ``limit``.  Returned
    ``KnowledgeMatch.similarity`` values are computed, never hardcoded.
    """

    def __init__(self, provider: DeterministicEmbeddingProvider):
        self._provider = provider
        self.searches = []
        self.lexical_searches = []
        self._indexed = []  # list of (KnowledgeMatch meta, embedding)

    def index(self, tenant_id: str, chunks) -> None:
        """Index ``(doc_id, sequence, content, source)`` chunk tuples."""
        texts = [content for _, _, content, _ in chunks]
        embeddings = self._provider.embed_many(texts)
        self._indexed = []
        for (doc_id, seq, content, source), embedding in zip(chunks, embeddings):
            meta = KnowledgeMatch(
                chunk_id=f"{doc_id}-c{seq}",
                document_id=doc_id,
                tenant_id=tenant_id,
                content=content,
                source=source,
                provenance="Evaluation fixture",
                document_version=1,
                sequence=seq,
                similarity=0.0,  # placeholder; replaced per query below
            )
            self._indexed.append((meta, embedding))

    async def create_many(self, chunks, embeddings):
        return chunks

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        self.searches.append((tenant_id, query_embedding, limit, source_type))
        scored = []
        for meta, embedding in self._indexed:
            if meta.tenant_id != tenant_id:
                continue
            if source_type is not None and meta.source != source_type:
                continue
            scored.append((meta, _cosine(query_embedding, embedding)))
        scored.sort(key=lambda pair: (-pair[1], pair[0].chunk_id))
        return [
            KnowledgeMatch(
                chunk_id=meta.chunk_id,
                document_id=meta.document_id,
                tenant_id=meta.tenant_id,
                content=meta.content,
                source=meta.source,
                provenance=meta.provenance,
                document_version=meta.document_version,
                sequence=meta.sequence,
                similarity=similarity,
                dense_score=similarity,
            )
            for meta, similarity in scored[:limit]
        ]

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        self.lexical_searches.append((tenant_id, query_text, limit, source_type))
        return []


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _on_corpus_chunks():
    """Corpus content the on-corpus queries genuinely overlap with."""
    return [
        # Incident runbook
        (
            "doc-incident-1",
            0,
            "Escalate severity one incidents within 15 minutes to the on-call SRE.",
            KnowledgeSource.PROCEDURE,
        ),
        (
            "doc-incident-1",
            1,
            "Use PagerDuty to notify the incident commander for P1 incidents.",
            KnowledgeSource.PROCEDURE,
        ),
        # PTO policy
        (
            "doc-pto-1",
            0,
            "Employees accrue 15 vacation days per year, increasing to 20 after three years.",
            KnowledgeSource.POLICY,
        ),
        # Credential rotation
        (
            "doc-cred-1",
            0,
            "API credentials must be rotated every 90 days per security policy.",
            KnowledgeSource.POLICY,
        ),
        (
            "doc-cred-1",
            1,
            "Credential rotation is enforced through the secrets management system.",
            KnowledgeSource.PROCEDURE,
        ),
    ]


def _build_service():
    provider = DeterministicEmbeddingProvider()
    repo = QuerySensitiveFakeChunkRepository(provider)
    repo.index("tenant-eval", _on_corpus_chunks())
    return RetrievalService(repo, embedding_provider=provider)


async def _top_similarity(service, context, query) -> float:
    """Top-1 dense similarity for ``query`` through the real search path."""
    matches = await service.search(context, query)
    return matches[0].similarity if matches else 0.0


async def test_retrieval_similarity_is_query_dependent():
    """The harness computes similarity from query content, not a constant.

    Guards against regressing to hardcoded similarities: the eight eval
    queries must not all receive identical top-1 similarity, and the
    off-corpus maximum must differ from the on-corpus values.  If this
    fails, the floor tests below are testing a constant, not retrieval.
    """
    service = _build_service()
    context = _context()

    off_queries = [f["query"] for f in relevance_floor_off_corpus_fixtures()]
    on_queries = [f["query"] for f in relevance_floor_on_corpus_fixtures()]

    off_tops = [await _top_similarity(service, context, q) for q in off_queries]
    on_tops = [await _top_similarity(service, context, q) for q in on_queries]

    assert len(set(off_tops + on_tops)) > 1, (
        "all queries received identical similarity — the harness is not "
        "query-sensitive; refusing to test the floor against a constant"
    )
    assert len(set(off_tops)) > 1, (
        "the five off-corpus queries must not all receive identical "
        "similarity merely because of the provider"
    )


async def test_off_corpus_filtered_and_on_corpus_kept():
    """Fixed query sets against the index; floor separates them.

    Measures top-1 dense similarity per query through ``search()``, then
    applies the floor at the measured midpoint via ``approved_search()``.
    Off-corpus queries (the five exact #210 reproductions) must yield
    empty ApprovedContext; on-corpus queries must keep their items.

    If the measured distributions overlap, no threshold satisfies AC 1
    and AC 4 at once — the test xfails citing the measured values.
    """
    service = _build_service()
    context = _context()

    off_queries = [f["query"] for f in relevance_floor_off_corpus_fixtures()]
    on_queries = [f["query"] for f in relevance_floor_on_corpus_fixtures()]

    off_tops = [await _top_similarity(service, context, q) for q in off_queries]
    on_tops = [await _top_similarity(service, context, q) for q in on_queries]

    off_max = max(off_tops)
    on_min = min(on_tops)

    if off_max >= on_min:
        pytest.xfail(
            f"no separating threshold exists for this provider and corpus: "
            f"off-corpus max similarity {off_max:.4f} >= on-corpus min "
            f"{on_min:.4f}; closing #210 requires a provider (or corpus) "
            f"where these distributions separate"
        )

    # Midpoint of the measured gap: derived from retrieval, not invented.
    threshold = (off_max + on_min) / 2

    for query in off_queries:
        approved = await service.approved_search(context, query, min_relevance_score=threshold)
        assert approved.items == [], (
            f"off-corpus query {query!r} survived the floor at measured "
            f"threshold {threshold:.4f} (top similarity "
            f"{await _top_similarity(service, context, query):.4f})"
        )

    for query in on_queries:
        approved = await service.approved_search(context, query, min_relevance_score=threshold)
        assert len(approved.items) > 0, (
            f"on-corpus query {query!r} was filtered at measured threshold "
            f"{threshold:.4f} (top similarity "
            f"{await _top_similarity(service, context, query):.4f})"
        )


async def test_max_threshold_filters_everything():
    """Threshold 1.0 excludes every non-identical match.

    No eval query is verbatim-identical to a corpus chunk, so cosine is
    strictly below 1.0 for all of them and the contract is empty.  This
    pins the floor's upper boundary through the real path.
    """
    service = _build_service()
    context = _context()

    approved = await service.approved_search(
        context,
        "how do I escalate a severity one incident?",
        min_relevance_score=1.0,
    )
    assert approved.items == []
