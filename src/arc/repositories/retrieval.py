"""PostgreSQL implementation of the KnowledgeChunkRepository contract.

Follows the same conventions as ``arc.repositories.knowledge``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query that reads or modifies a knowledge chunk includes a
``tenant_id`` condition so that cross-tenant access is impossible at the
SQL level.

Embedding vectors are passed as text with explicit ``::vector`` casts.
The repository deliberately does not depend on the pgvector Python codec
package: the shared schema-bootstrap path must be able to connect before
the ``vector`` extension exists, and vector values are only ever written
(insert) or compared (similarity search), never decoded back into Python.

The embedding column is fixed at ``EMBEDDING_DIMENSIONS`` (1536)
dimensions, matching the production embedding provider. The single
source of truth is ``EMBEDDING_DIMENSIONS`` in ``arc.services.embeddings``.

The repository performs no authorization. The trusted ``tenant_id`` must
come from an X-10 validated ``TenantContext`` established by the
application layer, never from an arbitrary request payload.
"""

from typing import List, Optional

from arc.db.connection import ArcDatabase
from arc.domain.models import KnowledgeChunk, KnowledgeMatch, KnowledgeSource


def _vector_to_text(vector: List[float]) -> str:
    """Encode a Python vector as pgvector text input (e.g. ``[0.1,0.2]``)."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class PostgreSQLKnowledgeChunkRepository:
    """PostgreSQL implementation of the KnowledgeChunkRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create_many(
        self, chunks: List[KnowledgeChunk], embeddings: List[List[float]]
    ) -> List[KnowledgeChunk]:
        """Persist chunks atomically with their embedding vectors.

        All chunk rows are inserted in one transaction: a failure inserts
        nothing (no partial index for a document).

        The ``search_vector`` column is populated from ``content`` via
        PostgreSQL's ``to_tsvector('english', ...)`` so that lexical
        retrieval is immediately available after insert.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if chunks and any(chunk.tenant_id != chunks[0].tenant_id for chunk in chunks):
            raise ValueError("All chunks in a batch must belong to the same tenant")

        async with self.db.transaction() as conn:
            for chunk, embedding in zip(chunks, embeddings):
                await conn.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        id, document_id, tenant_id, content, sequence,
                        embedding, search_vector, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::vector,
                            to_tsvector('english', $4), $7)
                    """,
                    chunk.id,
                    chunk.document_id,
                    chunk.tenant_id,
                    chunk.content,
                    chunk.sequence,
                    _vector_to_text(embedding),
                    chunk.created_at,
                )
        return chunks

    async def search(
        self,
        tenant_id: str,
        query_embedding: List[float],
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Return tenant-scoped chunk matches ordered by similarity.

        The SQL boundary is the security boundary: chunks are filtered by
        ``tenant_id`` and joined to their owning document within the same
        tenant, so a tenant B query can never observe tenant A chunks.

        When ``source_type`` is provided, only documents whose
        ``knowledge_documents.source`` matches are included in the
        candidate set.
        """
        if limit < 1:
            raise ValueError("Search limit must be a positive integer")

        if source_type is not None:
            sql = """
                SELECT c.id AS chunk_id,
                       c.document_id,
                       c.tenant_id,
                       c.content,
                       c.sequence,
                       d.source,
                       d.provenance,
                       d.version,
                       d.external_id,
                       1 - (c.embedding <=> $2::vector) AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1
                  AND d.status = 'active'
                  AND d.source = $4
                ORDER BY c.embedding <=> $2::vector
                LIMIT $3
                """
            params = (
                tenant_id,
                _vector_to_text(query_embedding),
                limit,
                source_type.value,
            )
        else:
            sql = """
                SELECT c.id AS chunk_id,
                       c.document_id,
                       c.tenant_id,
                       c.content,
                       c.sequence,
                       d.source,
                       d.provenance,
                       d.version,
                       d.external_id,
                       1 - (c.embedding <=> $2::vector) AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1
                  -- ADR-003 lifecycle: archived documents are retained for
                  -- recovery but are never a retrieval source.
                  AND d.status = 'active'
                ORDER BY c.embedding <=> $2::vector
                LIMIT $3
                """
            params = (
                tenant_id,
                _vector_to_text(query_embedding),
                limit,
            )

        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [
                KnowledgeMatch(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    tenant_id=row["tenant_id"],
                    content=row["content"],
                    source=KnowledgeSource(row["source"]),
                    provenance=row["provenance"],
                    document_version=row["version"],
                    sequence=row["sequence"],
                    similarity=float(row["similarity"]),
                    dense_score=float(row["similarity"]),
                    external_id=row["external_id"],
                )
                for row in rows
            ]

    async def lexical_search(
        self,
        tenant_id: str,
        query_text: str,
        limit: int = 5,
        source_type: Optional[KnowledgeSource] = None,
    ) -> List[KnowledgeMatch]:
        """Return tenant-scoped chunk matches ordered by lexical relevance.

        Uses PostgreSQL full-text search: ``plainto_tsquery`` converts the
        user query to a tsquery (implicit AND between terms), and
        ``ts_rank`` scores matches against the pre-computed
        ``search_vector``. The GIN index on ``search_vector`` accelerates
        the ``@@`` match.

        The SQL boundary is the security boundary: chunks are filtered by
        ``tenant_id`` and joined to their owning document within the same
        tenant, so a tenant B query can never observe tenant A chunks.

        When ``source_type`` is provided, only documents whose
        ``knowledge_documents.source`` matches are included in the
        candidate set.
        """
        if limit < 1:
            raise ValueError("Search limit must be a positive integer")

        if source_type is not None:
            sql = """
                SELECT c.id AS chunk_id,
                       c.document_id,
                       c.tenant_id,
                       c.content,
                       c.sequence,
                       d.source,
                       d.provenance,
                       d.version,
                       d.external_id,
                       ts_rank(c.search_vector,
                               plainto_tsquery('english', $2)) AS rank
                FROM knowledge_chunks c
                JOIN knowledge_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1
                  AND c.search_vector @@ plainto_tsquery('english', $2)
                  AND d.status = 'active'
                  AND d.source = $4
                ORDER BY rank DESC
                LIMIT $3
                """
            params = (tenant_id, query_text, limit, source_type.value)
        else:
            sql = """
                SELECT c.id AS chunk_id,
                       c.document_id,
                       c.tenant_id,
                       c.content,
                       c.sequence,
                       d.source,
                       d.provenance,
                       d.version,
                       d.external_id,
                       ts_rank(c.search_vector,
                               plainto_tsquery('english', $2)) AS rank
                FROM knowledge_chunks c
                JOIN knowledge_documents d
                  ON d.id = c.document_id AND d.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1
                  AND c.search_vector @@ plainto_tsquery('english', $2)
                  AND d.status = 'active'
                ORDER BY rank DESC
                LIMIT $3
                """
            params = (tenant_id, query_text, limit)

        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [
                KnowledgeMatch(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    tenant_id=row["tenant_id"],
                    content=row["content"],
                    source=KnowledgeSource(row["source"]),
                    provenance=row["provenance"],
                    document_version=row["version"],
                    sequence=row["sequence"],
                    similarity=float(row["rank"]),
                    lexical_score=float(row["rank"]),
                    external_id=row["external_id"],
                )
                for row in rows
            ]
