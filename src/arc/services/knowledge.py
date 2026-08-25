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

from arc.db.connection import DuplicateKeyError, NotFoundError
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
        external_id: Optional[str] = None,
    ) -> KnowledgeDocument:
        """Sanitize and persist a knowledge document for a tenant.

        The ``context`` must be an already-validated TenantContext
        established by X-10's TenantContextService. The tenant boundary is
        derived exclusively from it; tenant identifiers supplied by an
        untrusted payload are never accepted.

        Raw content is ALWAYS passed through ``PiiGuardService`` first —
        including on re-ingestion of an existing logical document
        (ADR-003). If sanitization fails (PiiGuardError), nothing is
        persisted and the exception propagates (fail closed).

        Identity and re-ingestion (ADR-003): when ``external_id`` is
        provided, the logical document is ``(tenant_id, source,
        external_id)``:

        - no existing document → create (version 1);
        - existing document with identical sanitized content → returned
          unchanged (idempotent redelivery; no version bump, no chunk churn);
        - existing document with different sanitized content → new chunks
          and embeddings are prepared entirely in memory FIRST (embedding
          failure aborts before any write), then the document is updated in
          place with ``version = version + 1`` and its whole chunk set
          replaced atomically;
        - a concurrent first delivery of the same identity loses the insert
          race at the database identity index and is re-resolved through the
          identical/changed-content logic above.

        When ``external_id`` is omitted, behavior is unchanged from the
        original foundation: every ingestion creates a new document.

        With an ``indexer`` configured, a created or updated document and
        ALL of its chunks are written inside ONE database transaction, so
        there is never a document without its complete index, nor a partial
        chunk set.
        """
        if not isinstance(source, KnowledgeSource):
            raise ValueError(f"Invalid knowledge source: {source!r}")
        if not provenance:
            raise ValueError("Knowledge document provenance cannot be empty")
        if not content:
            raise ValueError("Knowledge document content cannot be empty")
        if not isinstance(version, int) or version < 1:
            raise ValueError("Knowledge document version must be a positive integer")
        if external_id is not None:
            if not isinstance(external_id, str) or not external_id:
                raise ValueError(
                    "Knowledge document external_id must be a non-empty string when provided"
                )
            if len(external_id) > 255:
                raise ValueError("Knowledge document external_id cannot exceed 255 characters")

        # PII boundary first — on every path, including re-ingestion.
        sanitized_text = self.pii_guard.sanitize(content).sanitized_text

        existing: Optional[KnowledgeDocument] = None
        if external_id is not None:
            try:
                existing = await self.knowledge_repo.get_by_external_id(
                    external_id, source, context.tenant_id
                )
            except NotFoundError:
                existing = None

        if existing is not None:
            return await self._reingest_existing(context, source, existing, sanitized_text)

        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            source=source,
            provenance=provenance,
            version=version,
            status=KnowledgeStatus.ACTIVE,
            content=sanitized_text,
            external_id=external_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        prepared = await self._prepare_or_none(context, document)
        return await self._create(context, document, prepared)

    async def _reingest_existing(
        self,
        context: TenantContext,
        source: KnowledgeSource,
        existing: KnowledgeDocument,
        sanitized_text: str,
    ) -> KnowledgeDocument:
        """Apply ADR-003 re-ingestion semantics to one resolved document."""
        if existing.source != source or existing.tenant_id != context.tenant_id:
            # Defensive re-check; resolution is already tenant/source-scoped.
            raise ValueError("Resolved knowledge document does not match the trusted identity")

        if existing.content == sanitized_text:
            # Idempotent redelivery: same logical document, unchanged content.
            return existing

        updated = KnowledgeDocument(
            id=existing.id,
            tenant_id=existing.tenant_id,
            source=existing.source,
            provenance=existing.provenance,
            version=existing.version + 1,
            status=existing.status,
            content=sanitized_text,
            external_id=existing.external_id,
            created_at=existing.created_at,
            updated_at=datetime.now(),
        )

        prepared = await self._prepare_or_none(context, updated)
        if prepared is not None:
            return await self.knowledge_repo.update_document_with_chunks(
                updated, prepared.chunks, prepared.embeddings
            )
        return await self.knowledge_repo.update_document_with_chunks(updated, [], [])

    async def _prepare_or_none(self, context: TenantContext, document: KnowledgeDocument):
        """Prepare the retrieval index in memory, or None without an indexer.

        Embedding failures propagate BEFORE any persistence/update so the
        fail-closed ordering of the original foundation is preserved.
        """
        if self.indexer is None:
            return None
        return await self.indexer.prepare_index(context, document)

    async def _create(
        self,
        context: TenantContext,
        document: KnowledgeDocument,
        prepared,
    ) -> KnowledgeDocument:
        """Create a document (plus its prepared chunks atomically)."""
        try:
            if prepared is not None:
                return await self.knowledge_repo.create_document_with_chunks(
                    document, prepared.chunks, prepared.embeddings
                )
            return await self.knowledge_repo.create(document)
        except DuplicateKeyError:
            # Concurrent first delivery of the SAME logical identity won the
            # race at the database identity index (ADR-003). Re-resolve and
            # apply the identical/changed-content semantics to the winner.
            if document.external_id is None:
                raise
            try:
                winner = await self.knowledge_repo.get_by_external_id(
                    document.external_id, document.source, context.tenant_id
                )
            except NotFoundError:
                raise
            return await self._reingest_existing(context, document.source, winner, document.content)

    async def get_document(self, context: TenantContext, document_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID within a tenant."""
        return await self.knowledge_repo.get_by_id(document_id, context.tenant_id)

    async def list_documents(self, context: TenantContext) -> List[KnowledgeDocument]:
        """List all knowledge documents for a tenant."""
        return await self.knowledge_repo.list_for_tenant(context.tenant_id)
