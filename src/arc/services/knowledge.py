"""Knowledge service for the Arc Company Brain foundation.

The KnowledgeService accepts a trusted ``TenantContext`` established by
X-10 and derives the tenant boundary from it. The service never queries
tenancy tables, never authenticates users, and never authorizes callers.

The critical security boundary is the PII guard:

    RAW CONTENT
        ↓
    PII Guard (PiiGuardService)
        ↓
    SANITIZED CONTENT
        ↓
    PERSISTENCE

The service reuses the existing ``PiiGuardService`` (Microsoft Presidio).
It never copies PII detection logic and never instantiates a second PII
implementation. If sanitization fails, the service fails closed: no
unsanitized content is persisted and a PiiGuardError is raised.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from arc.domain.models import (
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeStatus,
    TenantContext,
)
from arc.repositories import KnowledgeRepository
from arc.services.pii import PiiGuardService
from arc.services.retrieval import RetrievalService


class KnowledgeService:
    """Domain service for tenant-scoped knowledge document operations."""

    def __init__(
        self,
        knowledge_repo: KnowledgeRepository,
        pii_guard: Optional[PiiGuardService] = None,
        indexer: Optional[RetrievalService] = None,
    ):
        self.knowledge_repo = knowledge_repo
        self.pii_guard = pii_guard if pii_guard is not None else PiiGuardService()
        self.indexer = indexer

    async def ingest_document(
        self,
        context: TenantContext,
        source: KnowledgeSource,
        provenance: str,
        content: str,
        version: int = 1,
    ) -> KnowledgeDocument:
        """Sanitize and persist a knowledge document for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10's TenantContextService. The tenant boundary is
        derived exclusively from it; tenant identifiers supplied by an
        untrusted payload are never accepted.

        Raw content is passed through ``PiiGuardService`` before any
        persistence. If sanitization fails (PiiGuardError), nothing is
        persisted and the exception propagates (fail closed).

        When an ``indexer`` (Secure RAG foundation) is configured, chunks
        and embeddings are prepared entirely in memory from the sanitized
        content, and the knowledge document is then created together with
        ALL of its chunks inside ONE database transaction
        (``create_document_with_chunks``). The ordering is fail closed:

        - an embedding failure aborts before any database write, so
          nothing is persisted;
        - a failure while inserting the document or any chunk rolls back
          the whole transaction, so there is never a document without its
          complete index, nor a partial chunk set.
        """
        if not isinstance(source, KnowledgeSource):
            raise ValueError(f"Invalid knowledge source: {source!r}")
        if not provenance:
            raise ValueError("Knowledge document provenance cannot be empty")
        if not content:
            raise ValueError("Knowledge document content cannot be empty")
        if not isinstance(version, int) or version < 1:
            raise ValueError("Knowledge document version must be a positive integer")

        sanitized = self.pii_guard.sanitize(content)

        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            source=source,
            provenance=provenance,
            version=version,
            status=KnowledgeStatus.ACTIVE,
            content=sanitized.sanitized_text,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        prepared = None
        if self.indexer is not None:
            prepared = await self.indexer.prepare_index(context, document)

        if self.indexer is not None and prepared is not None:
            return await self.knowledge_repo.create_document_with_chunks(
                document, prepared.chunks, prepared.embeddings
            )
        return await self.knowledge_repo.create(document)

    async def get_document(self, context: TenantContext, document_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID within a tenant."""
        return await self.knowledge_repo.get_by_id(document_id, context.tenant_id)

    async def list_documents(self, context: TenantContext) -> List[KnowledgeDocument]:
        """List all knowledge documents for a tenant."""
        return await self.knowledge_repo.list_for_tenant(context.tenant_id)
