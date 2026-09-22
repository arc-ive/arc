"""Tenant-scoped retrieval service for the Company Brain Secure RAG foundation.

The ``RetrievalService`` accepts a trusted ``TenantContext`` established
by X-10 and derives the tenant boundary exclusively from it. The service
never queries tenancy tables, never authenticates users, and never
authorizes callers.

Chunking operates exclusively on already-sanitized knowledge content: the
PII Guard boundary lives in ``KnowledgeService`` ingestion, and this
service only ever receives ``KnowledgeDocument`` instances produced by
that boundary.

Fail-closed ordering: chunk texts and embeddings are computed BEFORE the
owning document is persisted (``prepare_index``), so an embedding-provider
failure prevents any persistence at all — there is never a document
without a complete index, nor a partial chunk set.
"""

import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from arc.domain.models import (
    ApprovedContext,
    ApprovedContextItem,
    ApprovedContextSecurityMetadata,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeMatch,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
)
from arc.repositories import KnowledgeChunkRepository
from arc.services.chunking import KnowledgeChunker
from arc.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    EmbeddingProvider,
)


@dataclass
class PreparedIndex:
    """Chunks and embeddings computed for a document, not yet persisted.

    Prepared indexes are persisted atomically by ``persist_index`` so
    that a document is never partially indexed.
    """

    chunks: List[KnowledgeChunk]
    embeddings: List[List[float]]


class ReciprocalRankFusion:
    """Deterministic Reciprocal Rank Fusion for dense and lexical ranked lists.

    For each result at 1-based rank ``r`` in a ranked list, the contribution
    is ``1 / (k + r)``. When the same chunk appears in both lists, its
    contributions are summed. Results are sorted by descending fused score,
    with ascending ``chunk_id`` as the deterministic tie-breaker.

    This component is stateless and does not mutate input lists or
    ``KnowledgeMatch`` objects.
    """

    @staticmethod
    def fuse(
        dense: List[KnowledgeMatch],
        lexical: List[KnowledgeMatch],
        k: int = 60,
    ) -> List[KnowledgeMatch]:
        """Fuse dense and lexical ranked lists using Reciprocal Rank Fusion.

        Returns a single ranked list with RRF scores applied. The original
        ``KnowledgeMatch`` objects are not mutated; the fused score is
        returned separately for the caller to use when constructing
        ``ApprovedContextItem.relevance_score``.

        When a chunk appears in both lists, the retained object carries
        both per-method scores: ``dense_score`` from the dense hit and
        ``lexical_score`` from the lexical hit.  Without this merge the
        lexical instance would overwrite the dense one and drop its
        ``dense_score``, silently bypassing the relevance floor.
        """
        scores: Dict[str, float] = {}
        chunk_map: Dict[str, KnowledgeMatch] = {}

        for rank, match in enumerate(dense, start=1):
            scores[match.chunk_id] = scores.get(match.chunk_id, 0.0) + 1.0 / (k + rank)
            chunk_map[match.chunk_id] = match

        for rank, match in enumerate(lexical, start=1):
            scores[match.chunk_id] = scores.get(match.chunk_id, 0.0) + 1.0 / (k + rank)
            existing = chunk_map.get(match.chunk_id)
            if existing is None:
                chunk_map[match.chunk_id] = match
            else:
                chunk_map[match.chunk_id] = replace(
                    match,
                    dense_score=(
                        existing.dense_score
                        if existing.dense_score is not None
                        else match.dense_score
                    ),
                    lexical_score=(
                        match.lexical_score
                        if match.lexical_score is not None
                        else existing.lexical_score
                    ),
                )

        ranked_ids = sorted(scores.keys(), key=lambda cid: (-scores[cid], cid))
        return [chunk_map[cid] for cid in ranked_ids]

    @staticmethod
    def scores(
        dense: List[KnowledgeMatch],
        lexical: List[KnowledgeMatch],
        k: int = 60,
    ) -> Dict[str, float]:
        """Return the RRF score per chunk_id without constructing a ranked list.

        Useful for callers that need the score mapping without the
        ordered result list.
        """
        result: Dict[str, float] = {}

        for rank, match in enumerate(dense, start=1):
            result[match.chunk_id] = result.get(match.chunk_id, 0.0) + 1.0 / (k + rank)

        for rank, match in enumerate(lexical, start=1):
            result[match.chunk_id] = result.get(match.chunk_id, 0.0) + 1.0 / (k + rank)

        return result


def _dedup_by_lineage(matches: List[KnowledgeMatch]) -> List[KnowledgeMatch]:
    """Drop superseded chunks, keeping every chunk of the current version.

    Documents sharing ``(tenant_id, external_id, source)`` are versions
    of the same logical document (ADR-003).  The winning
    ``document_version`` per lineage is determined first; then ALL
    chunks belonging to that version are kept, so sibling chunks of the
    current document (``sequence=0,1,2,...``) never evict each other.

    Input order (RRF ranking) is preserved: the result is an in-place
    filter, so the top-ranked match stays top-ranked and a later
    ``[:limit]`` truncation cannot drop it.

    Matches with ``external_id is None`` pass through unchanged; without
    a lineage key we cannot determine which documents are related.
    """
    winning_version: Dict[tuple, int] = {}
    for match in matches:
        if match.external_id is None:
            continue
        key = (match.tenant_id, match.external_id, match.source)
        if key not in winning_version or match.document_version > winning_version[key]:
            winning_version[key] = match.document_version

    return [
        match
        for match in matches
        if match.external_id is None
        or match.document_version == winning_version[(match.tenant_id, match.external_id, match.source)]
    ]


class RetrievalService:
    """Domain service for tenant-scoped knowledge chunking and retrieval."""

    def __init__(
        self,
        chunk_repo: KnowledgeChunkRepository,
        chunker: Optional[KnowledgeChunker] = None,
        embedding_provider: EmbeddingProvider = None,  # type: ignore[assignment]
    ):
        self.chunk_repo = chunk_repo
        self.chunker = chunker if chunker is not None else KnowledgeChunker()
        if embedding_provider is None:
            raise TypeError("embedding_provider is required")
        self.embedding_provider = embedding_provider

    async def prepare_index(
        self, context: TenantContext, document: KnowledgeDocument
    ) -> Optional[PreparedIndex]:
        """Chunk and embed sanitized document content WITHOUT persisting.

        Returns ``None`` when the document produces no chunks. Embedding
        failures (``EmbeddingError``) propagate so the caller aborts before
        any persistence: fail closed.
        """
        if document.tenant_id != context.tenant_id:
            raise ValueError("Knowledge document does not belong to the trusted tenant")

        texts = self.chunker.chunk(document.content)
        if not texts:
            return None

        chunks = [
            KnowledgeChunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                tenant_id=context.tenant_id,
                content=text,
                sequence=sequence,
                created_at=datetime.now(timezone.utc),
            )
            for sequence, text in enumerate(texts)
        ]

        embeddings = self.embedding_provider.embed_many([chunk.content for chunk in chunks])
        for embedding in embeddings:
            if len(embedding) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError(
                    f"Embedding provider returned {len(embedding)} dimensions; "
                    f"storage expects {EMBEDDING_DIMENSIONS}"
                )

        return PreparedIndex(chunks=chunks, embeddings=embeddings)

    async def persist_index(self, prepared: PreparedIndex) -> List[KnowledgeChunk]:
        """Persist prepared chunks atomically with their embeddings."""
        return await self.chunk_repo.create_many(prepared.chunks, prepared.embeddings)

    async def search(
        self,
        context: TenantContext,
        query: str,
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Embed the query and return the top tenant-scoped matches.

        The tenant boundary comes exclusively from the trusted context;
        caller-supplied tenant identifiers are never accepted. Embedding
        failures (``EmbeddingError``) propagate: fail closed, no partial
        or misleading results.

        When ``source_type`` is provided, only chunks belonging to
        documents of that source type are candidates.

        Raises:
            ValueError: for an empty query or a non-positive limit.
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        if limit < 1:
            raise ValueError("Search limit must be a positive integer")

        query_embedding = self.embedding_provider.embed(query)
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"Embedding provider returned {len(query_embedding)} dimensions; "
                f"storage expects {EMBEDDING_DIMENSIONS}"
            )

        return await self.chunk_repo.search(
            context.tenant_id, query_embedding, limit, source_type=source_type
        )

    async def lexical_search(
        self,
        context: TenantContext,
        query: str,
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Return top tenant-scoped matches via PostgreSQL full-text search.

        This method does NOT call the embedding provider: lexical
        retrieval uses the pre-computed ``search_vector`` column and
        ``plainto_tsquery`` for query parsing. The tenant boundary comes
        exclusively from the trusted context; caller-supplied tenant
        identifiers are never accepted.

        When ``source_type`` is provided, only chunks belonging to
        documents of that source type are candidates.

        Raises:
            ValueError: for an empty query or a non-positive limit.
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        if limit < 1:
            raise ValueError("Search limit must be a positive integer")

        return await self.chunk_repo.lexical_search(
            context.tenant_id, query, limit, source_type=source_type
        )

    async def approved_search(
        self,
        context: TenantContext,
        query: str,
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
        min_relevance_score: Optional[float] = None,
    ) -> ApprovedContext:
        """Return retrieval results as the Approved Context Contract.

        This is the ONLY representation a future Unified
        Intelligence/LLM layer may consume: it carries already-sanitized
        content with provenance/citation metadata and never exposes the
        repository, vectors, or authorization state.

        V2 uses hybrid retrieval: dense semantic retrieval + lexical
        retrieval fused via Reciprocal Rank Fusion (``HYBRID_RRF``).

        Items whose dense cosine similarity falls below
        ``min_relevance_score`` are excluded from the approved context.
        Lexical-only matches (no dense retrieval hit) are not floored
        because their score is ts_rank, which is not comparable to
        cosine similarity.  Note: an off-corpus query that lands a
        lexical hit (e.g. a word overlap) bypasses the floor entirely.
        When no items clear the threshold the contract has an empty
        ``items`` list; the caller
        (``UnifiedIntelligenceService.answer_query``) returns the
        existing no-answer response in that case.

        The threshold defaults to the ``MIN_RELEVANCE_SCORE`` env var,
        falling back to ``0.0`` (no filtering).  A value of ``0.0``
        disables the floor, which is correct for the ``deterministic``
        provider used in CI where cosine similarity values do not
        separate on- from off-corpus queries.  Production deployments
        with a real embedding provider should set this to a measured
        threshold that rejects known off-corpus queries.

        The tenant boundary comes exclusively from the trusted context,
        the SQL similarity search is tenant-scoped, and every returned
        match is defensively re-validated against the trusted tenant
        (an invariant violation fails closed instead of leaking context).

        When ``source_type`` is provided, only chunks belonging to
        documents of that source type are candidates.

        **Supersession dedup** (issue #219): when multiple chunks belong
        to documents sharing the same ``(tenant_id, external_id, source)``
        lineage, only chunks from the highest ``document_version`` are
        kept — every chunk of the current version, not just one.  This
        prevents superseded and current versions of the same logical
        document from appearing as competing sources.  Documents without
        an ``external_id`` are not deduplicated against each other.

        Raises:
            ValueError: for an empty query or a non-positive limit.
            EmbeddingError: when the embedding provider fails; no
                contract is produced (fail closed).
            RuntimeError: when the repository returns a match outside the
                trusted tenant (invariant violation; fail closed).
        """
        if min_relevance_score is None:
            raw = os.getenv("MIN_RELEVANCE_SCORE", "0.0")
            try:
                min_relevance_score = float(raw)
            except ValueError:
                raise ValueError(f"MIN_RELEVANCE_SCORE must be a numeric value, got {raw!r}")
        dense_matches = await self.search(context, query, limit=limit, source_type=source_type)
        lexical_matches = await self.lexical_search(
            context, query, limit=limit, source_type=source_type
        )

        fused = ReciprocalRankFusion.fuse(dense_matches, lexical_matches)
        rrf_scores = ReciprocalRankFusion.scores(dense_matches, lexical_matches)

        for match in fused:
            if match.tenant_id != context.tenant_id:
                raise RuntimeError("Retrieval returned a match outside the trusted tenant")

        deduped = _dedup_by_lineage(fused)

        def _passes_floor(match: KnowledgeMatch) -> bool:
            dense = match.dense_score
            if dense is None:
                return True
            return dense >= min_relevance_score

        filtered = [match for match in deduped if _passes_floor(match)]
        filtered = filtered[:limit]

        items = [
            ApprovedContextItem(
                document_id=match.document_id,
                chunk_id=match.chunk_id,
                content=match.content,
                source=match.source,
                provenance=match.provenance,
                document_version=match.document_version,
                sequence=match.sequence,
                relevance_score=rrf_scores[match.chunk_id],
                citation_reference=f"{match.document_id}#c{match.sequence}",
            )
            for match in filtered
        ]

        return ApprovedContext(
            request_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            principal_id=context.user_id,
            query=query,
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(
                tenant_id=context.tenant_id,
                authorization_status="approved",
                pii_status="sanitized",
            ),
        )
