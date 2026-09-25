"""RAG evaluation: the lexical-only floor bypass, and closing it.

Companion to ``test_rag_relevance_floor.py``, which covers the dense
(cosine) floor with lexical retrieval deliberately returning nothing.
This module covers the case that one excludes: a query that misses
semantically but lands an incidental lexical hit.

The defect being pinned: ``MIN_RELEVANCE_SCORE`` floors ``dense_score``.
A lexical-only match has no ``dense_score``, so before
``MIN_LEXICAL_RELEVANCE_SCORE`` existed it was waved through
unconditionally — an operator who had measured and configured a dense
floor still shipped arbitrary context for any off-corpus query sharing a
word with the corpus. The floor was bypassable by accident.

Both scores are floored on their own scale on purpose. ``ts_rank`` and
cosine are not comparable, and the fused RRF score (a sum of
``1/(k+rank)`` terms) carries no similarity semantics at all, so
thresholding it would be meaningless. The tests below assert that
separation rather than assuming it.

The harness mirrors production SQL semantics: dense cosine against the
real ``DeterministicEmbeddingProvider``, lexical results supplied
explicitly so the bypass can be exercised deterministically without
depending on PostgreSQL's ``ts_rank`` values.
"""

import math

from arc.domain.models import KnowledgeMatch, KnowledgeSource, TenantContext, UserRole
from arc.services.embeddings import DeterministicEmbeddingProvider
from arc.services.retrieval import RetrievalService


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


CORPUS = [
    (
        "doc-incident-1",
        0,
        "Escalate severity one incidents within 15 minutes to the on-call SRE.",
        KnowledgeSource.PROCEDURE,
    ),
    (
        "doc-pto-1",
        0,
        "Employees accrue 15 vacation days per year, increasing to 20 after three years.",
        KnowledgeSource.POLICY,
    ),
    (
        "doc-cred-1",
        0,
        "API credentials must be rotated every 90 days per security policy.",
        KnowledgeSource.POLICY,
    ),
]


class ScriptedRepository:
    """Real cosine for dense; caller-supplied results for lexical.

    Lexical hits are scripted rather than computed because the point of
    these tests is the floor's treatment of a lexical-only match, not
    PostgreSQL's ranking function. Dense similarity stays genuine so the
    dense floor is exercised against a real value.
    """

    def __init__(self, provider, lexical_results=None):
        self._provider = provider
        self._lexical_results = lexical_results or []
        texts = [content for _, _, content, _ in CORPUS]
        embeddings = provider.embed_many(texts)
        self._indexed = [
            (doc_id, seq, content, source, embedding)
            for (doc_id, seq, content, source), embedding in zip(CORPUS, embeddings)
        ]

    async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
        matches = [
            KnowledgeMatch(
                chunk_id=f"{doc_id}-c{seq}",
                document_id=doc_id,
                tenant_id=tenant_id,
                content=content,
                similarity=_cosine(query_embedding, embedding),
                source=source,
                sequence=seq,
                provenance=f"test/{doc_id}",
                document_version=1,
                dense_score=_cosine(query_embedding, embedding),
            )
            for doc_id, seq, content, source, embedding in self._indexed
        ]
        matches.sort(key=lambda m: -m.similarity)
        return matches[:limit]

    async def lexical_search(self, tenant_id, query_text, limit=5, source_type=None):
        return [
            KnowledgeMatch(
                chunk_id=chunk_id,
                document_id=doc_id,
                tenant_id=tenant_id,
                content=content,
                similarity=ts_rank,
                source=KnowledgeSource.POLICY,
                sequence=0,
                provenance=f"test/{doc_id}",
                document_version=1,
                lexical_score=ts_rank,
            )
            for chunk_id, doc_id, content, ts_rank in self._lexical_results
        ][:limit]


def _context(tenant_id="tenant-lexfloor"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Lexical Floor Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _service(lexical_results=None):
    provider = DeterministicEmbeddingProvider()
    return RetrievalService(
        ScriptedRepository(provider, lexical_results),
        embedding_provider=provider,
    )


# A query with no semantic relationship to the corpus that nonetheless
# shares a token ("policy") with it — the realistic shape of the bypass,
# not a contrived one.
OFF_CORPUS_QUERY = "what is the refund policy for concert tickets?"

# The lexical hit must be a chunk the dense search did NOT return, or RRF
# merges the two instances and the match carries a dense_score — which is
# the already-correct path, not the bypass. This models what lexical
# retrieval is for: finding something the embedding missed.
LEXICAL_ONLY_DOC = "doc-refund-1"
LEXICAL_ONLY_CONTENT = "Ticket refund policy: refunds are issued within 30 days."

# A weak lexical hit: present, but poorly ranked. ts_rank values in this
# range are what PostgreSQL returns for an incidental single-term match.
WEAK_LEXICAL = [(f"{LEXICAL_ONLY_DOC}-c0", LEXICAL_ONLY_DOC, LEXICAL_ONLY_CONTENT, 0.03)]
STRONG_LEXICAL = [(f"{LEXICAL_ONLY_DOC}-c0", LEXICAL_ONLY_DOC, LEXICAL_ONLY_CONTENT, 0.85)]


class TestLexicalOnlyBypass:
    """The bypass is real: pin it, then pin that the new floor closes it."""

    async def test_dense_floor_alone_is_bypassed_by_a_lexical_hit(self):
        """A dense floor of 1.0 rejects everything dense — yet context survives.

        This is the defect. The operator has configured the strictest
        possible cosine floor; a single incidental lexical match still
        puts arbitrary content into the approved context.
        """
        service = _service(lexical_results=WEAK_LEXICAL)
        approved = await service.approved_search(
            _context(), OFF_CORPUS_QUERY, min_relevance_score=1.0
        )
        assert approved.items, (
            "expected the lexical-only match to bypass the dense floor; if this "
            "now returns empty, the bypass was closed elsewhere and this test "
            "no longer pins what it claims"
        )
        assert all(item.document_id == LEXICAL_ONLY_DOC for item in approved.items)

    async def test_lexical_floor_closes_the_bypass(self):
        """With both floors configured, the off-corpus query yields nothing."""
        service = _service(lexical_results=WEAK_LEXICAL)
        approved = await service.approved_search(
            _context(),
            OFF_CORPUS_QUERY,
            min_relevance_score=1.0,
            min_lexical_relevance_score=0.5,
        )
        assert approved.items == []

    async def test_strong_lexical_match_still_survives_its_floor(self):
        """The floor rejects weak hits, not lexical retrieval itself.

        Without this, 'closing the bypass' could just mean breaking
        lexical search, which would silently gut hybrid retrieval.
        """
        service = _service(lexical_results=STRONG_LEXICAL)
        approved = await service.approved_search(
            _context(),
            OFF_CORPUS_QUERY,
            min_relevance_score=1.0,
            min_lexical_relevance_score=0.5,
        )
        assert len(approved.items) == 1
        assert approved.items[0].document_id == LEXICAL_ONLY_DOC

    async def test_lexical_floor_defaults_to_disabled(self):
        """Default behaviour is unchanged: no floor unless configured."""
        service = _service(lexical_results=WEAK_LEXICAL)
        approved = await service.approved_search(_context(), OFF_CORPUS_QUERY)
        assert approved.items, "the default must remain fail-open, as documented"


class TestFloorsAreIndependent:
    """Each score family is floored on its own scale."""

    async def test_lexical_floor_does_not_filter_dense_matches(self):
        """A dense hit is judged by cosine, never by the lexical threshold.

        A high lexical floor must not evict a semantically strong match
        that simply has no ts_rank.
        """
        service = _service(lexical_results=[])
        approved = await service.approved_search(
            _context(),
            "how often must API credentials be rotated?",
            min_relevance_score=0.0,
            min_lexical_relevance_score=0.99,
        )
        assert approved.items, "a dense-only match was filtered by the lexical floor"

    async def test_dense_floor_does_not_use_the_fused_rrf_score(self):
        """RRF scores are ~0.016-0.033 and carry no similarity meaning.

        If the dense floor were ever applied to the fused score instead
        of cosine, a threshold of 0.25 would empty every result even for
        a perfectly on-corpus query. This asserts it does not.
        """
        service = _service(lexical_results=[])
        approved = await service.approved_search(
            _context(),
            "how often must API credentials be rotated?",
            min_relevance_score=0.25,
        )
        assert approved.items, (
            "an on-corpus query was emptied at a threshold below its measured "
            "cosine (0.5698) — the floor is being applied to the RRF score"
        )
        # The exposed relevance_score remains the RRF score, unchanged.
        assert all(0.0 < item.relevance_score < 0.1 for item in approved.items)


class TestFloorConfiguration:
    """Configuration fails closed rather than silently disabling the gate."""

    async def test_invalid_lexical_threshold_raises(self, monkeypatch):
        monkeypatch.setenv("MIN_LEXICAL_RELEVANCE_SCORE", "not-a-number")
        service = _service(lexical_results=WEAK_LEXICAL)
        try:
            await service.approved_search(_context(), OFF_CORPUS_QUERY)
        except ValueError as exc:
            assert "MIN_LEXICAL_RELEVANCE_SCORE" in str(exc)
        else:
            raise AssertionError("a non-numeric threshold must fail closed")

    async def test_lexical_threshold_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("MIN_RELEVANCE_SCORE", "1.0")
        monkeypatch.setenv("MIN_LEXICAL_RELEVANCE_SCORE", "0.5")
        service = _service(lexical_results=WEAK_LEXICAL)
        approved = await service.approved_search(_context(), OFF_CORPUS_QUERY)
        assert approved.items == []


class TestTenantIsolationUnderFloors:
    """The floor must never become a way around the tenant boundary."""

    async def test_cross_tenant_match_still_fails_closed(self):
        """A foreign match raises even when it would clear every floor."""
        provider = DeterministicEmbeddingProvider()

        class LeakyRepository(ScriptedRepository):
            async def search(self, tenant_id, query_embedding, limit=5, source_type=None):
                matches = await super().search(tenant_id, query_embedding, limit, source_type)
                return [
                    KnowledgeMatch(
                        chunk_id=m.chunk_id,
                        document_id=m.document_id,
                        tenant_id="some-other-tenant",
                        content=m.content,
                        similarity=m.similarity,
                        source=m.source,
                        sequence=m.sequence,
                        provenance=m.provenance,
                        document_version=m.document_version,
                        dense_score=m.dense_score,
                    )
                    for m in matches
                ]

        service = RetrievalService(LeakyRepository(provider, []), embedding_provider=provider)
        try:
            await service.approved_search(
                _context(),
                "how often must API credentials be rotated?",
                min_relevance_score=0.0,
                min_lexical_relevance_score=0.0,
            )
        except RuntimeError as exc:
            assert "outside the trusted tenant" in str(exc)
        else:
            raise AssertionError("a cross-tenant match must fail closed")
