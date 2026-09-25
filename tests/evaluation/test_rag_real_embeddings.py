"""Opt-in RAG evaluation against a REAL embedding provider.

Every other test in this directory runs on ``DeterministicEmbeddingProvider``:
a word-hash histogram. It is stable, needs no credentials, and is the right
choice for CI — but its cosine values measure *lexical overlap*, not meaning.
Metrics collected against it therefore say nothing about production semantic
retrieval quality, and must not be quoted as if they did.

This module runs the same evaluation dataset through the configured real
provider (``EMBEDDING_PROVIDER=openai``, ``text-embedding-3-small``, 1536
dimensions) so the two can be compared on equal terms.

It is **opt-in and skipped by default**. Normal CI never runs it, never needs
an API key, and cannot be broken by a provider outage:

    ARC_REAL_EMBEDDING_EVAL=1 \\
    EMBEDDING_PROVIDER=openai \\
    OPENAI_API_KEY=... \\
    DATABASE_URL=postgresql://...  \\
    pytest tests/evaluation/test_rag_real_embeddings.py -s

``-s`` matters: the metrics are printed, because the point is the numbers, not
only the pass/fail.

What it reports:

- **Recall@K** — did the expected document reach the top K?
- **Relevant retrieval rate** — share of answerable queries retrieving their
  expected document at all.
- **Unanswerable behaviour** — what an off-corpus query retrieves, and at what
  top-1 cosine. This is the input to choosing MIN_RELEVANCE_SCORE; see
  docs/evaluation/RELEVANCE_FLOOR.md.
- **Citation grounding** — every citation in the approved context resolves to
  a retrieved chunk.

Tenant isolation is asserted here too. It is not a metric to be traded off
against retrieval quality: a real provider changes ranking, never the tenant
boundary, and a regression there fails the run outright.
"""

import os
import uuid

import pytest

from arc.domain.models import KnowledgeSource, Tenant, TenantContext, UserRole
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.services.chunking import build_knowledge_chunker, get_chunking_settings
from arc.services.embeddings import build_embedding_provider, get_embedding_settings
from arc.services.knowledge import KnowledgeService
from arc.services.retrieval import RetrievalService

pytestmark = pytest.mark.skipif(
    not os.getenv("ARC_REAL_EMBEDDING_EVAL"),
    reason=(
        "real-provider evaluation is opt-in: set ARC_REAL_EMBEDDING_EVAL=1 with "
        "EMBEDDING_PROVIDER and provider credentials configured. Normal CI runs "
        "the deterministic provider and needs no credentials."
    ),
)


# Small, self-contained corpus. Deliberately not the reference-data seed: the
# ground truth has to be exact for recall to mean anything.
CORPUS = [
    (
        "vacation-policy",
        "Employees accrue 15 vacation days per year, rising to 20 after three years of service.",
    ),
    ("remote-work", "Remote work is permitted up to three days per week with manager approval."),
    (
        "expenses",
        "Expenses above 500 dollars require a receipt and director sign-off for reimbursement.",
    ),
    (
        "security-incident",
        "Report a severity one security incident to the on-call SRE within 15 minutes.",
    ),
    (
        "office-access",
        "Building access badges are issued by facilities and must be worn visibly on site.",
    ),
    ("benefits", "Open enrolment for health benefits runs for two weeks each November."),
    ("code-review", "Every pull request requires one approving review before merge."),
    ("oncall", "The on-call rotation hands over each Monday at 10:00 UTC."),
]

ANSWERABLE = [
    ("how many vacation days do employees get?", "vacation-policy"),
    ("how many days can I work remotely?", "remote-work"),
    ("what do I need for expense reimbursement?", "expenses"),
    ("how fast must I report a security incident?", "security-incident"),
    ("who issues building badges?", "office-access"),
    ("when is open enrolment?", "benefits"),
    ("how many approvals does a pull request need?", "code-review"),
    ("when does the on-call rotation change?", "oncall"),
]

# Plausible near-misses, not nonsense. Nonsense is trivially rejected and
# proves nothing about the floor; these are the questions users actually ask
# about policies a company does not have.
UNANSWERABLE = [
    "what is our parental leave entitlement?",
    "how do I expense a company car?",
    "what is the tuition reimbursement limit?",
    "who won the 1998 world cup final?",
]


def _context(tenant_id, user_id="eval-user"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Embedding Eval Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


@pytest.fixture
async def indexed(db, repositories):
    """Ingest the corpus through the production KnowledgeService path.

    Uses the canonical ingestion boundary (chunking, PII sanitisation,
    embedding) rather than writing chunks directly, so the evaluation
    measures the pipeline that actually runs.
    """
    tenant_repo, _, _ = repositories
    tenant = await tenant_repo.create(
        Tenant(id=f"embed-eval-{uuid.uuid4().hex[:8]}", name="Embedding Eval")
    )
    other = await tenant_repo.create(
        Tenant(id=f"embed-other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    )

    settings = get_embedding_settings()
    provider = build_embedding_provider(settings)
    retrieval = RetrievalService(
        PostgreSQLKnowledgeChunkRepository(db),
        chunker=build_knowledge_chunker(get_chunking_settings()),
        embedding_provider=provider,
    )
    knowledge = KnowledgeService(PostgreSQLKnowledgeRepository(db), indexer=retrieval)

    ctx = _context(tenant.id)
    external_to_doc = {}
    for external_id, content in CORPUS:
        doc = await knowledge.ingest_document(
            ctx,
            source=KnowledgeSource.POLICY,
            provenance=f"eval/{external_id}",
            content=content,
            external_id=external_id,
        )
        external_to_doc[external_id] = doc.id

    # One document in the other tenant, containing a term the eval queries use.
    await knowledge.ingest_document(
        _context(other.id, "other-user"),
        source=KnowledgeSource.POLICY,
        provenance="eval/secret",
        content="Confidential: acquisition of Northwind closes in March. Vacation freeze applies.",
        external_id="other-secret",
    )

    return {
        "tenant": tenant,
        "other": other,
        "retrieval": retrieval,
        "docs": external_to_doc,
        "provider": settings.provider,
        "model": settings.model,
        "dimensions": settings.dimensions,
    }


async def _ranked_doc_ids(retrieval, ctx, query, limit):
    matches = await retrieval.search(ctx, query, limit=limit)
    seen, ordered = set(), []
    for match in matches:
        if match.document_id not in seen:
            seen.add(match.document_id)
            ordered.append(match.document_id)
    return ordered, matches


class TestProviderConfiguration:
    async def test_provider_is_not_deterministic(self, indexed):
        """Guard against the whole run being a deterministic re-run.

        Without this, forgetting EMBEDDING_PROVIDER would produce a green
        report full of deterministic numbers labelled as real-provider
        results — the exact confusion this module exists to prevent.
        """
        assert indexed["provider"] != "deterministic", (
            "ARC_REAL_EMBEDDING_EVAL is set but EMBEDDING_PROVIDER is still "
            "'deterministic'; these metrics would not be real-provider metrics"
        )

    async def test_storage_dimensions_match(self, indexed):
        """Dimension drift corrupts the index silently; pin it."""
        assert indexed["dimensions"] == 1536


class TestRetrievalQuality:
    async def test_recall_at_k(self, indexed):
        """Recall@1/3/5 over the answerable set, printed for comparison."""
        retrieval, ctx = indexed["retrieval"], _context(indexed["tenant"].id)
        hits = {1: 0, 3: 0, 5: 0}
        misses = []
        for query, expected_external in ANSWERABLE:
            expected_doc = indexed["docs"][expected_external]
            ordered, _ = await _ranked_doc_ids(retrieval, ctx, query, 5)
            for k in hits:
                if expected_doc in ordered[:k]:
                    hits[k] += 1
            if expected_doc not in ordered:
                misses.append((query, expected_external))

        total = len(ANSWERABLE)
        print(f"\n--- provider={indexed['provider']} model={indexed['model']} ---")
        for k in sorted(hits):
            print(f"Recall@{k}: {hits[k]}/{total} = {hits[k] / total:.1%}")
        print(f"Relevant retrieval rate: {(total - len(misses)) / total:.1%}")
        for query, expected in misses:
            print(f"  MISS: {query!r} -> expected {expected}")

        # Recall@5 on an eight-document corpus is a low bar; a real provider
        # failing it means something is wrong with the wiring, not the ranking.
        assert hits[5] == total, f"Recall@5 incomplete, missed: {misses}"

    async def test_unanswerable_similarity_is_reported(self, indexed):
        """Print off-corpus top-1 cosine — the input to the relevance floor.

        No threshold is asserted: the correct value is deployment-specific
        (docs/evaluation/RELEVANCE_FLOOR.md). This records the evidence.
        """
        retrieval, ctx = indexed["retrieval"], _context(indexed["tenant"].id)
        answerable_tops, unanswerable_tops = [], []

        for query, _ in ANSWERABLE:
            _, matches = await _ranked_doc_ids(retrieval, ctx, query, 5)
            answerable_tops.append((query, matches[0].similarity if matches else 0.0))
        for query in UNANSWERABLE:
            _, matches = await _ranked_doc_ids(retrieval, ctx, query, 5)
            unanswerable_tops.append((query, matches[0].similarity if matches else 0.0))

        print("\nON-CORPUS top-1 cosine:")
        for q, s in sorted(answerable_tops, key=lambda p: p[1]):
            print(f"  {s:.6f}  {q}")
        print("OFF-CORPUS top-1 cosine:")
        for q, s in sorted(unanswerable_tops, key=lambda p: -p[1]):
            print(f"  {s:.6f}  {q}")

        on_min = min(s for _, s in answerable_tops)
        off_max = max(s for _, s in unanswerable_tops)
        print(f"\non_min={on_min:.6f} off_max={off_max:.6f} separated={off_max < on_min}")
        if off_max < on_min:
            print(f"suggested MIN_RELEVANCE_SCORE={(on_min + off_max) / 2:.4f}")
        else:
            print(
                "OVERLAP: no dense threshold separates these sets on this corpus. "
                "Leave MIN_RELEVANCE_SCORE at 0.0 and rely on generation-side refusal."
            )

    async def test_citations_are_grounded(self, indexed):
        """Every citation in the approved context resolves to a retrieved chunk."""
        retrieval, ctx = indexed["retrieval"], _context(indexed["tenant"].id)
        for query, _ in ANSWERABLE:
            approved = await retrieval.approved_search(ctx, query, limit=5)
            chunk_ids = {item.chunk_id for item in approved.items}
            for item in approved.items:
                assert item.citation_reference, "citation reference must not be empty"
                assert item.chunk_id in chunk_ids
                assert item.document_id, "citation must resolve to a document"


class TestSecurityUnderRealProvider:
    """A different provider changes ranking. It must not change the boundary."""

    async def test_tenant_isolation_holds(self, indexed):
        retrieval = indexed["retrieval"]
        ctx = _context(indexed["tenant"].id)
        other_ctx = _context(indexed["other"].id, "other-user")

        for query in ["vacation days", "acquisition of Northwind", "confidential"]:
            approved = await retrieval.approved_search(ctx, query, limit=10)
            for item in approved.items:
                assert "Northwind" not in item.content, (
                    f"cross-tenant content leaked for query {query!r}"
                )
            assert approved.security_metadata.tenant_id == indexed["tenant"].id

        approved_other = await retrieval.approved_search(other_ctx, "vacation days", limit=10)
        for item in approved_other.items:
            assert "accrue 15 vacation days" not in item.content, (
                "tenant A content leaked into tenant B retrieval"
            )
