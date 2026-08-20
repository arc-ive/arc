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


class KnowledgeService:
    """Domain service for tenant-scoped knowledge document operations."""

    def __init__(
        self,
        knowledge_repo: KnowledgeRepository,
        pii_guard: Optional[PiiGuardService] = None,
    ):
        self.knowledge_repo = knowledge_repo
        self.pii_guard = pii_guard if pii_guard is not None else PiiGuardService()

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
        return await self.knowledge_repo.create(document)

    async def get_document(self, context: TenantContext, document_id: str) -> KnowledgeDocument:
        """Get a knowledge document by ID within a tenant."""
        return await self.knowledge_repo.get_by_id(document_id, context.tenant_id)

    async def list_documents(self, context: TenantContext) -> List[KnowledgeDocument]:
        """List all knowledge documents for a tenant."""
        return await self.knowledge_repo.list_for_tenant(context.tenant_id)
