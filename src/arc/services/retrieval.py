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

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeMatch,
    TenantContext,
)
from arc.repositories import KnowledgeChunkRepository
from arc.services.chunking import KnowledgeChunker
from arc.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    DeterministicEmbeddingProvider,
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


class RetrievalService:
    """Domain service for tenant-scoped knowledge chunking and retrieval."""

    def __init__(
        self,
        chunk_repo: KnowledgeChunkRepository,
        chunker: Optional[KnowledgeChunker] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        self.chunk_repo = chunk_repo
        self.chunker = chunker if chunker is not None else KnowledgeChunker()
        self.embedding_provider = (
            embedding_provider
            if embedding_provider is not None
            else DeterministicEmbeddingProvider()
        )

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
                created_at=datetime.now(),
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
        self, context: TenantContext, query: str, limit: int = 5
    ) -> List[KnowledgeMatch]:
        """Embed the query and return the top tenant-scoped matches.

        The tenant boundary comes exclusively from the trusted context;
        caller-supplied tenant identifiers are never accepted. Embedding
        failures (``EmbeddingError``) propagate: fail closed, no partial
        or misleading results.

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

        return await self.chunk_repo.search(context.tenant_id, query_embedding, limit)
