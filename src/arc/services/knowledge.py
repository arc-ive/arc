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
from typing import Optional

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

    async def list_documents(self, context: TenantContext) -> list:
        """List ACTIVE knowledge documents for a tenant."""
        return await self.knowledge_repo.list_for_tenant(context.tenant_id)

    async def list_documents_paginated(
        self, context: TenantContext, limit: int, offset: int
    ) -> tuple:
        """List ACTIVE knowledge documents with LIMIT/OFFSET and total count."""
        return await self.knowledge_repo.list_for_tenant_paginated(context.tenant_id, limit, offset)

    async def archive_legacy_duplicates(
        self, dry_run: bool = True, tenant_id: Optional[str] = None
    ) -> dict:
        """One-time ADR-003 lifecycle cleanup (see ADR-003 follow-ups).

        Detects duplicate logical documents created BEFORE the identity
        model existed — strictly rows with ``external_id IS NULL`` whose
        provenance matches the deterministic historical connector binding
        ``connector:{provider}:{source_id}`` — grouped per tenant by
        ``(tenant_id, source, provenance)``.

        Safety model:

        - ``dry_run=False``: executes the archive-only mutation, which
          RE-CHECKS the exact predicate at mutation time inside one
          statement (including an outer ``kd.status = 'active'`` guard so
          concurrent runs never re-write already-archived losers).
          Archive-only: winners/content/chunks/external_id are
          preserved; nothing is deleted. Idempotent - already-archived
          rows stop matching and reruns archive nothing.

        Residual caveat (documented in ADR-003): a pre-model MANUAL
        document could theoretically carry a connector-style provenance;
        archive-only reversibility is the mitigation.

        Recovery semantics: archival is a STATUS-ONLY transition
        (active -> archived) and is therefore technically reversible, but
        there is NO application-level restore/unarchive operation today.
        Recovery is a controlled manual DBA action (flipping
        ``status`` back to ``'active'`` via SQL). An application-level
        restore API is a deferred future follow-up, not an existing
        capability.

        Returns a content-free report: mode, group/candidate counts,
        per-group winner and would-archive IDs/metadata only.
        """
        candidates = await self.knowledge_repo.find_legacy_duplicate_candidates(tenant_id)
        groups: dict = {}
        for row in candidates:
            key = (row["tenant_id"], row["source"], row["provenance"])
            groups.setdefault(key, []).append(row)

        group_reports = []
        to_archive = []
        for (tenant_id, source, provenance), rows in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        ):
            winner = next(row for row in rows if row["is_winner"])
            losers = sorted(
                (row for row in rows if not row["is_winner"]),
                key=lambda row: str(row["id"]),
            )
            group_reports.append(
                {
                    "tenant_id": tenant_id,
                    "source": source,
                    "provenance": provenance,
                    "winner_id": winner["id"],
                    "winner_created_at": winner["created_at"].isoformat(),
                    "would_archive": [
                        {"id": row["id"], "created_at": row["created_at"].isoformat()}
                        for row in losers
                    ],
                }
            )
            to_archive.extend(row["id"] for row in losers)

        report = {
            "dry_run": bool(dry_run),
            "candidate_rows": len(candidates),
            "duplicate_groups": len(group_reports),
            "rows_to_archive": len(to_archive),
            "groups": group_reports,
            "guarantees": {
                "no_deletion": True,
                "no_content_or_chunk_mutation": True,
                "no_external_id_fabrication": True,
                "archive_only": True,
            },
        }

        if dry_run:
            return report

        archived = await self.knowledge_repo.archive_legacy_duplicates(tenant_id)
        report["dry_run"] = False
        report["archived_rows"] = archived
        return report
