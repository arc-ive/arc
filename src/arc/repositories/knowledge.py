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

from typing import List, Optional

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
)
from arc.repositories import DEFAULT_LIST_LIMIT
from arc.repositories.retrieval import _vector_to_text

# Single source of truth for every knowledge_documents SELECT projection so
# column additions (e.g. ADR-003 external_id) cannot drift between queries.
_DOCUMENT_COLUMNS = (
    "id, tenant_id, source, provenance, version, "
    "status, content, external_id, created_at, updated_at"
)


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
                        status, content, external_id, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    document.id,
                    document.tenant_id,
                    document.source.value,
                    document.provenance,
                    document.version,
                    document.status.value,
                    document.content,
                    document.external_id,
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
                        status, content, external_id, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    document.id,
                    document.tenant_id,
                    document.source.value,
                    document.provenance,
                    document.version,
                    document.status.value,
                    document.content,
                    document.external_id,
                    document.created_at,
                    document.updated_at,
                )
                await self._insert_chunks(conn, chunks, embeddings)
            except asyncpg.UniqueViolationError as e:
                # A UniqueViolationError here is either the document PK or
                # the ADR-003 identity index uq_knowledge_documents_identity;
                # callers disambiguate by re-resolving logical identity.
                raise DuplicateKeyError(
                    f"Knowledge document {document.id} or a chunk already exists "
                    f"for tenant {document.tenant_id}"
                ) from e
        return document

    @staticmethod
    async def _insert_chunks(
        conn: asyncpg.Connection,
        chunks: List[KnowledgeChunk],
        embeddings: List[List[float]],
    ) -> None:
        """Insert one prepared chunk set inside an open transaction."""
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

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID, scoped to a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_DOCUMENT_COLUMNS}
                FROM knowledge_documents
                WHERE id = $1 AND tenant_id = $2
                """,
                document_id,
                tenant_id,
            )
            if not row:
                raise NotFoundError("Knowledge document not found")
            return self._row_to_document(row)

    async def delete_by_id(self, document_id: str, tenant_id: str) -> None:
        """Delete a knowledge document by ID, scoped to a tenant."""
        async with self.db._connection_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge_documents WHERE id = $1 AND tenant_id = $2",
                document_id,
                tenant_id,
            )
            if result == "DELETE 0":
                raise NotFoundError("Knowledge document not found")

    async def get_by_external_id(
        self, external_id: str, source: KnowledgeSource, tenant_id: str
    ) -> KnowledgeDocument:
        """Resolve one logical document by its ADR-003 identity.

        The lookup is strictly tenant-scoped: the same external identifier
        under a different tenant or source can never match.
        """
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_DOCUMENT_COLUMNS}
                FROM knowledge_documents
                WHERE external_id = $1 AND source = $2 AND tenant_id = $3
                """,
                external_id,
                source.value,
                tenant_id,
            )
            if not row:
                raise NotFoundError("Knowledge document not found")
            return self._row_to_document(row)

    async def update_document_with_chunks(
        self,
        document: KnowledgeDocument,
        chunks: List[KnowledgeChunk],
        embeddings: List[List[float]],
    ) -> KnowledgeDocument:
        """Apply an accepted content change to an existing logical document.

        Atomically in ONE transaction (ADR-003): update the existing row
        (matched by id AND tenant), replace the whole chunk set. Any
        failure rolls back so the prior version and its complete old index
        remain intact. ``document.version`` must already carry the bumped
        value computed by the service layer.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if any(chunk.tenant_id != document.tenant_id for chunk in chunks):
            raise ValueError("All chunks must belong to the document's tenant")

        async with self.db.transaction() as conn:
            try:
                status = await conn.execute(
                    """
                    UPDATE knowledge_documents
                    SET content = $3,
                        version = $4,
                        status = $5,
                        updated_at = $6
                    WHERE id = $1 AND tenant_id = $2
                    """,
                    document.id,
                    document.tenant_id,
                    document.content,
                    document.version,
                    document.status.value,
                    document.updated_at,
                )
                if status == "UPDATE 0":
                    raise NotFoundError("Knowledge document not found")
                await conn.execute(
                    """
                    DELETE FROM knowledge_chunks
                    WHERE document_id = $1 AND tenant_id = $2
                    """,
                    document.id,
                    document.tenant_id,
                )
                await self._insert_chunks(conn, chunks, embeddings)
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Knowledge chunk already exists for document {document.id} "
                    f"in tenant {document.tenant_id}"
                ) from e
        return document

    async def update_document_metadata(self, document: KnowledgeDocument) -> KnowledgeDocument:
        """Apply a metadata-only change to an existing logical document.

        Updates source/provenance/status/updated_at on the existing row
        (matched by id AND tenant) without touching content, version, or
        the chunk set.
        """
        async with self.db.transaction() as conn:
            status = await conn.execute(
                """
                UPDATE knowledge_documents
                SET source = $3,
                    provenance = $4,
                    status = $5,
                    updated_at = $6
                WHERE id = $1 AND tenant_id = $2
                """,
                document.id,
                document.tenant_id,
                document.source.value,
                document.provenance,
                document.status.value,
                document.updated_at,
            )
            if status == "UPDATE 0":
                raise NotFoundError("Knowledge document not found")
        return document

    async def list_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> List[KnowledgeDocument]:
        """List ACTIVE knowledge documents for a tenant.

        Archived documents (ADR-003 lifecycle) are retained for
        recovery/audit via ``get_by_id`` but are not part of the normal
        listing/retrieval surface.
        """
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_DOCUMENT_COLUMNS}
                FROM knowledge_documents
                WHERE tenant_id = $1 AND status = 'active'
                ORDER BY created_at DESC, id ASC
                LIMIT $2
                """,
                tenant_id,
                limit,
            )
            return [self._row_to_document(row) for row in rows]

    async def list_for_tenant_paginated(self, tenant_id: str, limit: int, offset: int) -> tuple:
        """List ACTIVE knowledge documents with LIMIT/OFFSET and total count."""
        async with self.db._connection_pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM knowledge_documents "
                "WHERE tenant_id = $1 AND status = 'active'",
                tenant_id,
            )
            total = count_row["cnt"]
            rows = await conn.fetch(
                f"""
                SELECT {_DOCUMENT_COLUMNS}
                FROM knowledge_documents
                WHERE tenant_id = $1 AND status = 'active'
                ORDER BY created_at DESC, id ASC
                LIMIT $2 OFFSET $3
                """,
                tenant_id,
                limit,
                offset,
            )
            items = [self._row_to_document(row) for row in rows]
            return items, total

    async def find_legacy_duplicate_candidates(self, tenant_id: Optional[str] = None) -> List[dict]:
        """Discover legacy duplicate groups (ADR-003 follow-up cleanup).

        Candidate predicate (deliberately narrow — see ADR-003 and the
        note in ``archive_legacy_duplicates``): rows created before the
        identity model existed, i.e. ``external_id IS NULL``, still
        ``active``, whose provenance matches the deterministic historical
        connector binding ``connector:{provider}:{source_id}``.

        Rows are grouped per tenant by ``(tenant_id, source, provenance)``.
        Within each group the newest ``created_at`` (tie-break: smallest
        ``id``) is the WINNER and remains active; every other row in the
        group is an archival candidate. Read-only: no state changes.

        ``tenant_id`` optionally narrows the sweep to a single tenant;
        ``None`` (the default) sweeps every tenant. Grouping NEVER spans
        tenants regardless.
        """
        async with self.db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tenant_id, source, provenance, id, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY tenant_id, source, provenance
                           ORDER BY created_at DESC, id ASC
                       ) AS rn
                FROM knowledge_documents
                WHERE external_id IS NULL
                  AND status = 'active'
                  AND provenance LIKE 'connector:%'
                  AND ($1::varchar IS NULL OR tenant_id = $1)
                """,
                tenant_id,
            )
            return [
                {
                    "tenant_id": row["tenant_id"],
                    "source": row["source"],
                    "provenance": row["provenance"],
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "is_winner": row["rn"] == 1,
                }
                for row in rows
            ]

    async def archive_legacy_duplicates(self, tenant_id: Optional[str] = None) -> int:
        """Archive non-winner legacy duplicate rows; return the count.

        ONE atomic statement that RE-CHECKS the exact safety predicate and
        the winner rule at mutation time (no stale ID list from a dry run
        can be blindly mutated). Archive-only: content, chunks, external_id
        values, and the per-group winner are never touched. Idempotent:
        already-archived rows stop matching the predicate, so reruns
        archive nothing.

        ``tenant_id`` optionally narrows the mutation to a single tenant;
        ``None`` (the default) sweeps every tenant. Grouping NEVER spans
        tenants.
        """
        async with self.db.transaction() as conn:
            status = await conn.execute(
                """
                WITH candidates AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY tenant_id, source, provenance
                               ORDER BY created_at DESC, id ASC
                           ) AS rn
                    FROM knowledge_documents
                    WHERE external_id IS NULL
                      AND status = 'active'
                      AND provenance LIKE 'connector:%'
                      AND ($1::varchar IS NULL OR tenant_id = $1)
                )
                UPDATE knowledge_documents kd
                SET status = 'archived',
                    updated_at = CURRENT_TIMESTAMP
                FROM candidates c
                WHERE kd.id = c.id
                  AND c.rn > 1
                  -- Concurrent-execution guard: a loser already archived by
                  -- a parallel run is no longer active and must not be
                  -- re-written; the reported count then reflects only real
                  -- ACTIVE → ARCHIVED state transitions.
                  AND kd.status = 'active'
                """,
                tenant_id,
            )
            archived = int(status.split()[-1]) if status else 0
        return archived

    @staticmethod
    def _row_to_document(row: asyncpg.Record) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=row["id"],
            tenant_id=row["tenant_id"],
            source=KnowledgeSource(row["source"]),
            provenance=row["provenance"],
            version=row["version"],
            status=KnowledgeStatus(row["status"]),
            content=row["content"],
            external_id=row["external_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
