"""PostgreSQL implementation of the KnowledgeRepository contract.

Follows the same conventions as ``arc.repositories.connectors``: the
repository receives an ``ArcDatabase`` instance and issues raw SQL via
asyncpg. Every query that reads or modifies a knowledge document includes
a ``tenant_id`` condition so that cross-tenant access is impossible at
the SQL level.

The repository performs no authorization. The trusted ``tenant_id`` must
come from an X-10 validated ``TenantContext`` established by the
application layer, never from an arbitrary request payload.
"""

from typing import List

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
)
from arc.repositories.retrieval import _vector_to_text


class PostgreSQLKnowledgeRepository:
    """PostgreSQL implementation of the KnowledgeRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        """Create a new knowledge document."""
        async with self.db.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO knowledge_documents (
                        id, tenant_id, source, provenance, version,
                        status, content, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    document.id,
                    document.tenant_id,
                    document.source.value,
                    document.provenance,
                    document.version,
                    document.status.value,
                    document.content,
                    document.created_at,
                    document.updated_at,
                )
                return document
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Knowledge document {document.id} already exists "
                    f"for tenant {document.tenant_id}"
                ) from e
            except Exception as e:
                raise Exception(f"Failed to create knowledge document: {e}") from e

    async def create_document_with_chunks(
        self,
        document: KnowledgeDocument,
        chunks: List[KnowledgeChunk],
        embeddings: List[List[float]],
    ) -> KnowledgeDocument:
        """Create a knowledge document and all its chunks atomically.

        The document row and every chunk row are inserted in ONE
        transaction: if the document insert or any chunk insert fails,
        the entire operation rolls back. No knowledge document row may
        remain without its complete retrieval index, and no partial chunk
        set may remain.

        Embedding vectors are passed as opaque ``List[float]`` values and
        encoded as pgvector text input (see ``arc.repositories.retrieval``).
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if any(chunk.tenant_id != document.tenant_id for chunk in chunks):
            raise ValueError("All chunks must belong to the document's tenant")

        async with self.db.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO knowledge_documents (
                        id, tenant_id, source, provenance, version,
                        status, content, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    document.id,
                    document.tenant_id,
                    document.source.value,
                    document.provenance,
                    document.version,
                    document.status.value,
                    document.content,
                    document.created_at,
                    document.updated_at,
                )
                for chunk, embedding in zip(chunks, embeddings):
                    await conn.execute(
                        """
                        INSERT INTO knowledge_chunks (
                            id, document_id, tenant_id, content, sequence,
                            embedding, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
                        """,
                        chunk.id,
                        chunk.document_id,
                        chunk.tenant_id,
                        chunk.content,
                        chunk.sequence,
                        _vector_to_text(embedding),
                        chunk.created_at,
                    )
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Knowledge document {document.id} or a chunk already exists "
                    f"for tenant {document.tenant_id}"
                ) from e
        return document

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID, scoped to a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, source, provenance, version,
                       status, content, created_at, updated_at
                FROM knowledge_documents
                WHERE id = $1 AND tenant_id = $2
                """,
                document_id,
                tenant_id,
            )
            if not row:
                raise NotFoundError(
                    f"Knowledge document {document_id} not found in tenant {tenant_id}"
                )
            return KnowledgeDocument(
                id=row["id"],
                tenant_id=row["tenant_id"],
                source=KnowledgeSource(row["source"]),
                provenance=row["provenance"],
                version=row["version"],
                status=KnowledgeStatus(row["status"]),
                content=row["content"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def list_for_tenant(self, tenant_id: str) -> List[KnowledgeDocument]:
        """List all knowledge documents for a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, source, provenance, version,
                       status, content, created_at, updated_at
                FROM knowledge_documents
                WHERE tenant_id = $1
                ORDER BY created_at DESC
                """,
                tenant_id,
            )
            return [
                KnowledgeDocument(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    source=KnowledgeSource(row["source"]),
                    provenance=row["provenance"],
                    version=row["version"],
                    status=KnowledgeStatus(row["status"]),
                    content=row["content"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
