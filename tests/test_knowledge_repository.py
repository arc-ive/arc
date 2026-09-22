"""Integration tests for the PostgreSQL KnowledgeRepository.

These tests exercise the concrete PostgreSQL knowledge repository against
a real PostgreSQL database. They verify the repository contract and,
critically, tenant isolation: a document created by tenant A must never
be retrievable or listable by tenant B.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"kd-{prefix}-{uuid.uuid4().hex[:10]}"


def _document(tenant_id: str, **overrides):
    values = dict(
        id=_unique("doc"),
        tenant_id=tenant_id,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    values.update(overrides)
    return KnowledgeDocument(**values)


def _chunks(document: KnowledgeDocument, count: int = 2, **overrides):
    return [
        KnowledgeChunk(
            id=overrides.get("id", _unique(f"chunk-{index}")),
            document_id=document.id,
            tenant_id=document.tenant_id,
            content=f"chunk content number {index}",
            sequence=index,
            created_at=datetime.now(timezone.utc),
        )
        for index in range(count)
    ]


def _embeddings(count: int, dimension: int = 1536):
    """Non-zero collinear embeddings: safe for presence assertions."""
    return [[float(index) + 1.0] * dimension for index in range(count)]


@pytest.fixture
async def db():
    """Connect to PostgreSQL and ensure the schema exists."""
    database = ArcDatabase(DATABASE_URL)
    await database.connect()
    async with database._connection_pool.acquire() as conn:
        schema = SCHEMA_PATH.read_text()
        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)
    yield database
    await database.disconnect()


@pytest.fixture
async def knowledge_repo(db):
    """Create a PostgreSQLKnowledgeRepository."""
    return PostgreSQLKnowledgeRepository(db)


@pytest.fixture
async def seeded_tenant(db):
    """Create a tenant for test data and clean up afterwards."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_id = _unique("tenant")
    tenant = await tenant_repo.create(Tenant(id=tenant_id, name="Knowledge Test Tenant"))
    yield tenant
    await tenant_repo.delete(tenant.id)


@pytest.fixture
async def seeded_tenants(db):
    """Create two tenants for cross-tenant isolation tests."""
    tenant_repo = PostgreSQLTenantRepository(db)
    tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant-a"), name="Tenant A"))
    tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="Tenant B"))
    yield tenant_a, tenant_b
    await tenant_repo.delete(tenant_a.id)
    await tenant_repo.delete(tenant_b.id)


class TestKnowledgeRepositoryContract:
    """Verify the KnowledgeRepository methods against PostgreSQL."""

    async def test_create_and_get(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        created = await knowledge_repo.create(document)

        assert created.id == document.id
        assert created.tenant_id == seeded_tenant.id
        assert created.source == KnowledgeSource.POLICY
        assert created.provenance == "Policy handbook 2026 edition"
        assert created.version == 1

        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.id == document.id
        assert fetched.tenant_id == seeded_tenant.id
        assert fetched.content == "Approved remote work policy."

    async def test_get_by_id_not_found(self, knowledge_repo, seeded_tenant):
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id("missing-id", seeded_tenant.id)

    async def test_list_for_tenant_empty(self, knowledge_repo, seeded_tenant):
        result = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert result == []

    async def test_list_for_tenant_multiple(self, knowledge_repo, seeded_tenant):
        ids = []
        for i in range(3):
            doc = _document(seeded_tenant.id, id=_unique(f"doc-{i}"), provenance=f"provenance-{i}")
            await knowledge_repo.create(doc)
            ids.append(doc.id)

        result = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(result) == 3
        returned_ids = {d.id for d in result}
        assert returned_ids == set(ids)

    async def test_duplicate_id_is_rejected(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        await knowledge_repo.create(document)

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create(document)

    async def test_source_and_provenance_are_round_tripped(self, knowledge_repo, seeded_tenant):
        document = _document(
            seeded_tenant.id,
            source=KnowledgeSource.INCIDENT_REPORT,
            provenance="Incident INC-2026-0042",
            version=3,
            content="Network outage resolved by restarting the gateway.",
        )
        await knowledge_repo.create(document)

        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.source == KnowledgeSource.INCIDENT_REPORT
        assert fetched.provenance == "Incident INC-2026-0042"
        assert fetched.version == 3


class TestKnowledgeTenantIsolation:
    """Prove that the SQL WHERE clause enforces tenant isolation."""

    async def test_get_by_id_isolation(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        document = _document(tenant_a.id)
        await knowledge_repo.create(document)

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, tenant_b.id)

    async def test_list_isolation(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        doc_a = _document(tenant_a.id)
        doc_b = _document(tenant_b.id)
        await knowledge_repo.create(doc_a)
        await knowledge_repo.create(doc_b)

        list_a = await knowledge_repo.list_for_tenant(tenant_a.id)
        assert len(list_a) == 1
        assert list_a[0].id == doc_a.id

        list_b = await knowledge_repo.list_for_tenant(tenant_b.id)
        assert len(list_b) == 1
        assert list_b[0].id == doc_b.id


class TestKnowledgeDocumentWithChunks:
    """Atomicity of create_document_with_chunks (one transaction).

    The document row and every chunk row are inserted in ONE PostgreSQL
    transaction: a failure while inserting a chunk rolls back the
    document insert too. There must never be a knowledge document without
    its complete retrieval index, nor a partial chunk set.
    """

    async def test_document_and_all_chunks_persist_atomically(
        self, db, knowledge_repo, seeded_tenant
    ):
        chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=3)

        created = await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(3))

        assert created.id == document.id
        fetched = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert fetched.id == document.id

        matches = await chunk_repo.search(seeded_tenant.id, [1.0] * 1536, limit=10)
        assert {match.chunk_id for match in matches} == {chunk.id for chunk in chunks}
        assert all(match.document_id == document.id for match in matches)

    async def test_chunk_insertion_failure_rolls_back_document_and_chunks(
        self, db, knowledge_repo, seeded_tenant
    ):
        chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
        document = _document(seeded_tenant.id)
        # Both chunks share one ID: the first chunk insert succeeds, the
        # second violates the primary key INSIDE the transaction.
        chunks = _chunks(document, count=2, id=_unique("duplicate-chunk"))

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(2))

        # The document insert was rolled back: no row, no chunks.
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert await chunk_repo.search(seeded_tenant.id, [1.0] * 1536, limit=10) == []

    async def test_length_mismatch_is_rejected_before_any_write(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=2)

        with pytest.raises(ValueError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(1))

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)

    async def test_tenant_mismatch_between_document_and_chunks_is_rejected(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id)
        chunks = _chunks(document, count=2)
        chunks[0].tenant_id = f"{seeded_tenant.id}-other"

        with pytest.raises(ValueError):
            await knowledge_repo.create_document_with_chunks(document, chunks, _embeddings(2))

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_id(document.id, seeded_tenant.id)

    async def test_document_duplicate_is_rejected(self, knowledge_repo, seeded_tenant):
        document = _document(seeded_tenant.id)
        await knowledge_repo.create(document)

        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create_document_with_chunks(
                document, _chunks(document, count=1), _embeddings(1)
            )


class TestKnowledgeDocumentIdentity:
    """ADR-003: logical identity (tenant_id, source, external_id)."""

    async def test_identity_uniqueness_enforced_by_database(self, knowledge_repo, seeded_tenant):
        first = _document(seeded_tenant.id, external_id="ext-shared")
        await knowledge_repo.create(first)

        duplicate = _document(seeded_tenant.id, external_id="ext-shared")
        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.create(duplicate)

    async def test_null_external_id_is_excluded_from_identity(self, knowledge_repo, seeded_tenant):
        await knowledge_repo.create(_document(seeded_tenant.id))
        await knowledge_repo.create(_document(seeded_tenant.id))

        rows = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(rows) == 2
        assert all(row.external_id is None for row in rows)

    async def test_same_identity_across_tenants_is_allowed(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants

        doc_a = await knowledge_repo.create(_document(tenant_a.id, external_id="shared-ext"))
        doc_b = await knowledge_repo.create(_document(tenant_b.id, external_id="shared-ext"))

        assert doc_a.tenant_id != doc_b.tenant_id

    async def test_get_by_external_id_round_trip_and_scoping(self, knowledge_repo, seeded_tenants):
        tenant_a, tenant_b = seeded_tenants
        created = await knowledge_repo.create(
            _document(tenant_a.id, external_id="lookup-1", provenance="connector:github:42")
        )

        found = await knowledge_repo.get_by_external_id(
            "lookup-1", KnowledgeSource.POLICY, tenant_a.id
        )
        assert found.id == created.id
        assert found.external_id == "lookup-1"

        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id("lookup-1", KnowledgeSource.POLICY, tenant_b.id)
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id(
                "lookup-1", KnowledgeSource.SOLUTION, tenant_a.id
            )
        with pytest.raises(NotFoundError):
            await knowledge_repo.get_by_external_id("missing", KnowledgeSource.POLICY, tenant_a.id)

    async def test_update_replaces_document_and_chunks_atomically(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id, external_id="upd-1", content="old content")
        old_chunks = _chunks(document, count=2)
        await knowledge_repo.create_document_with_chunks(
            document, old_chunks, _embeddings(len(old_chunks))
        )

        updated = KnowledgeDocument(
            id=document.id,
            tenant_id=document.tenant_id,
            source=document.source,
            provenance=document.provenance,
            version=document.version + 1,
            status=document.status,
            content="new content",
            external_id=document.external_id,
            created_at=document.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        new_chunks = _chunks(document, count=1)
        result = await knowledge_repo.update_document_with_chunks(
            updated, new_chunks, _embeddings(len(new_chunks))
        )

        assert result.version == 2
        assert result.content == "new content"
        stored = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert stored.version == 2
        assert stored.content == "new content"

        async with knowledge_repo.db._connection_pool.acquire() as conn:
            chunk_ids = await conn.fetch(
                "SELECT id FROM knowledge_chunks WHERE document_id = $1",
                document.id,
            )
        assert {row["id"] for row in chunk_ids} == {new_chunks[0].id}

    async def test_update_failure_rolls_back_to_prior_version_and_chunks(
        self, knowledge_repo, seeded_tenant
    ):
        document = _document(seeded_tenant.id, external_id="rb-1", content="old content")
        old_chunks = _chunks(document, count=2)
        await knowledge_repo.create_document_with_chunks(
            document, old_chunks, _embeddings(len(old_chunks))
        )

        # Two chunks share one id: the second insert violates the chunk PK
        # INSIDE the transaction (after the UPDATE and DELETE), so the whole
        # operation must roll back to the prior version and prior chunks.
        broken_new_chunks = [
            KnowledgeChunk(
                id="duplicate-chunk-id",
                document_id=document.id,
                tenant_id=document.tenant_id,
                content="new chunk a",
                sequence=0,
                created_at=datetime.now(timezone.utc),
            ),
            KnowledgeChunk(
                id="duplicate-chunk-id",
                document_id=document.id,
                tenant_id=document.tenant_id,
                content="new chunk b",
                sequence=1,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        bumped = KnowledgeDocument(
            id=document.id,
            tenant_id=document.tenant_id,
            source=document.source,
            provenance=document.provenance,
            version=document.version + 1,
            status=document.status,
            content="doomed new content",
            external_id=document.external_id,
            created_at=document.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(DuplicateKeyError):
            await knowledge_repo.update_document_with_chunks(
                bumped, broken_new_chunks, _embeddings(len(broken_new_chunks))
            )

        stored = await knowledge_repo.get_by_id(document.id, seeded_tenant.id)
        assert stored.version == 1
        assert stored.content == "old content"

        async with knowledge_repo.db._connection_pool.acquire() as conn:
            remaining = await conn.fetch(
                "SELECT id FROM knowledge_chunks WHERE document_id = $1 ORDER BY sequence",
                document.id,
            )
        assert [row["id"] for row in remaining] == [chunk.id for chunk in old_chunks]


class TestConcurrentIdentityIngestion:
    """ADR-003 concurrency: races are resolved by the database invariant."""

    class _PassthroughGuard:
        def sanitize(self, text: str):
            from types import SimpleNamespace

            return SimpleNamespace(sanitized_text=text)

    async def test_concurrent_first_delivery_creates_exactly_one_row(self, db, seeded_tenant):
        import asyncio

        from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
        from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
        from arc.services.embeddings import DeterministicEmbeddingProvider
        from arc.services.knowledge import KnowledgeService
        from arc.services.retrieval import RetrievalService

        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        indexer = RetrievalService(
            PostgreSQLKnowledgeChunkRepository(db),
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        service = KnowledgeService(
            knowledge_repo, pii_guard=self._PassthroughGuard(), indexer=indexer
        )
        context = TenantContext(
            tenant_id=seeded_tenant.id,
            tenant_name="Concurrent",
            user_id="user-1",
            role=UserRole.MEMBER,
        )

        results = await asyncio.gather(
            service.ingest_document(
                context,
                source=KnowledgeSource.INTERNAL_KNOWLEDGE,
                provenance="connector:github:race",
                content="identical concurrent content",
                external_id="github:race",
            ),
            service.ingest_document(
                context,
                source=KnowledgeSource.INTERNAL_KNOWLEDGE,
                provenance="connector:github:race",
                content="identical concurrent content",
                external_id="github:race",
            ),
        )

        assert results[0].id == results[1].id
        assert results[0].version == 1

        async with db._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM knowledge_documents
                WHERE tenant_id = $1 AND external_id = $2
                """,
                seeded_tenant.id,
                "github:race",
            )
        assert len(rows) == 1


class TestLegacyDuplicateArchival:
    """ADR-003 lifecycle completion: archive-only legacy duplicate cleanup."""

    def _legacy_doc(self, tenant_id, provenance, created_at=None, **overrides):
        values = dict(
            source=KnowledgeSource.INTERNAL_KNOWLEDGE,
            provenance=provenance,
            content=f"legacy content for {provenance}",
        )
        if created_at is not None:
            values["created_at"] = created_at
        values.update(overrides)
        return _document(tenant_id, **values)

    async def _seed_legacy_pair(self, knowledge_repo, tenant_id, provenance="connector:github:7"):
        older = self._legacy_doc(tenant_id, provenance)
        newer = self._legacy_doc(tenant_id, provenance)
        await knowledge_repo.create(older)
        await knowledge_repo.create(newer)
        return older, newer

    async def test_dry_run_identifies_groups_and_winners_without_mutation(
        self, knowledge_repo, seeded_tenant
    ):
        await self._seed_legacy_pair(knowledge_repo, seeded_tenant.id)

        candidates = await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id)
        winners = [c for c in candidates if c["is_winner"]]

        assert len(candidates) == 2
        assert len(winners) == 1
        rows = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert all(row.status.value == "active" for row in rows)

    async def test_execute_archives_older_duplicates_keeps_winner_active(
        self, knowledge_repo, seeded_tenant
    ):
        await self._seed_legacy_pair(knowledge_repo, seeded_tenant.id)

        archived_count = await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)

        assert archived_count == 1
        rows = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(rows) == 1  # winner remains visible on the active surface

    async def test_rerun_is_idempotent(self, knowledge_repo, seeded_tenant):
        older, newer = await self._seed_legacy_pair(knowledge_repo, seeded_tenant.id)
        first = await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)
        assert first == 1

        # Freeze the archived loser's state right after the first run.
        loser_after_first = await knowledge_repo.get_by_id(older.id, seeded_tenant.id)
        assert loser_after_first.status.value == "archived"

        second = await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)

        assert second == 0

        # Concurrent-execution guard: the already-archived loser was NOT
        # re-written by the second run (updated_at/status frozen), and the
        # winner remains active. Proves the kd.status='active' outer guard.
        loser_after_second = await knowledge_repo.get_by_id(older.id, seeded_tenant.id)
        assert loser_after_second.status.value == "archived"
        assert loser_after_second.updated_at == loser_after_first.updated_at

        winner_after_second = await knowledge_repo.get_by_id(newer.id, seeded_tenant.id)
        assert winner_after_second.status.value == "active"

    async def test_distinct_provenances_are_separate_groups(self, knowledge_repo, seeded_tenant):
        await knowledge_repo.create(self._legacy_doc(seeded_tenant.id, "connector:github:1"))
        await knowledge_repo.create(self._legacy_doc(seeded_tenant.id, "connector:github:2"))

        candidates = await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id)

        assert len(candidates) == 2
        assert all(candidate["is_winner"] for candidate in candidates)
        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 0

    async def test_same_provenance_across_tenants_is_independent(
        self, knowledge_repo, seeded_tenants
    ):
        tenant_a, tenant_b = seeded_tenants
        await knowledge_repo.create(self._legacy_doc(tenant_a.id, "connector:linear:9"))
        await knowledge_repo.create(self._legacy_doc(tenant_a.id, "connector:linear:9"))
        await knowledge_repo.create(self._legacy_doc(tenant_b.id, "connector:linear:9"))

        # Scoped sweep touches ONLY tenant A's duplicate group.
        candidates = await knowledge_repo.find_legacy_duplicate_candidates(tenant_a.id)
        assert len(candidates) == 2

        archived = await knowledge_repo.archive_legacy_duplicates(tenant_a.id)
        assert archived == 1

        rows_a = await knowledge_repo.list_for_tenant(tenant_a.id)
        rows_b = await knowledge_repo.list_for_tenant(tenant_b.id)
        assert len(rows_a) == 1  # tenant A winner kept
        assert len(rows_b) == 1  # tenant B's lone record completely untouched

    async def test_external_id_rows_are_never_candidates(self, knowledge_repo, seeded_tenant, db):
        # Two legacy duplicates of one logical document (both eligible)...
        await knowledge_repo.create(
            _document(seeded_tenant.id, external_id=None, provenance="connector:github:dup")
        )
        await knowledge_repo.create(
            _document(seeded_tenant.id, external_id=None, provenance="connector:github:dup")
        )
        # ...plus a THIRD row with the same tenant/source/provenance that
        # already carries an ADR-003 identity. It must NEVER be a candidate.
        identified = _document(
            seeded_tenant.id,
            external_id="github:dup",
            provenance="connector:github:dup",
        )
        await knowledge_repo.create(identified)

        candidates = await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id)

        assert len(candidates) == 2
        assert all(candidate["id"] != identified.id for candidate in candidates)

        archived_count = await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)

        assert archived_count == 1
        async with db._connection_pool.acquire() as conn:
            states = await conn.fetch(
                """
                SELECT id, external_id, status
                FROM knowledge_documents
                WHERE tenant_id = $1
                """,
                seeded_tenant.id,
            )
        by_external = {row["external_id"]: dict(row) for row in states}
        # Final state: ONE active winner + ONE archived older duplicate +
        # the untouched identity-bearing row (still active, external_id
        # byte-for-byte unchanged).
        assert len([r for r in states if r["status"] == "active"]) == 2
        assert len([r for r in states if r["status"] == "archived"]) == 1
        assert [r for r in states if r["status"] == "archived"][0]["external_id"] is None
        assert by_external["github:dup"]["status"] == "active"
        assert by_external["github:dup"]["external_id"] == "github:dup"

    async def test_archived_rows_are_never_candidates(self, knowledge_repo, seeded_tenant):
        older = self._legacy_doc(seeded_tenant.id, "connector:github:arch")
        newer = self._legacy_doc(seeded_tenant.id, "connector:github:arch")
        await knowledge_repo.create(older)
        await knowledge_repo.create(newer)
        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 1

        # Post-cleanup the surviving winner is still an active
        # connector-provenance row and legitimately appears in discovery as
        # a single-member group (nothing left to archive).
        candidates = await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id)
        assert len(candidates) == 1
        assert candidates[0]["is_winner"] is True

        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 0

    async def test_single_legitimate_connector_record_remains_active(
        self, knowledge_repo, seeded_tenant
    ):
        await knowledge_repo.create(self._legacy_doc(seeded_tenant.id, "connector:slack:only"))

        candidates = await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id)

        assert len(candidates) == 1
        assert candidates[0]["is_winner"] is True
        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 0

    async def test_non_connector_provenance_is_never_a_candidate(
        self, knowledge_repo, seeded_tenant
    ):
        await knowledge_repo.create(_document(seeded_tenant.id, provenance="Policy handbook"))
        await knowledge_repo.create(_document(seeded_tenant.id, provenance="Policy handbook v2"))

        assert await knowledge_repo.find_legacy_duplicate_candidates(seeded_tenant.id) == []
        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 0

    async def test_tenant_scoped_archival_leaves_other_tenants_untouched(
        self, knowledge_repo, seeded_tenants
    ):
        tenant_a, tenant_b = seeded_tenants
        await self._seed_legacy_pair(knowledge_repo, tenant_a.id, "connector:github:scoped")
        await self._seed_legacy_pair(knowledge_repo, tenant_b.id, "connector:github:scoped")

        archived = await knowledge_repo.archive_legacy_duplicates(tenant_a.id)

        assert archived == 1
        rows_a = await knowledge_repo.list_for_tenant(tenant_a.id)
        rows_b = await knowledge_repo.list_for_tenant(tenant_b.id)
        assert len(rows_a) == 1  # tenant A winner kept
        assert len(rows_b) == 2  # tenant B completely untouched

    async def test_created_at_tie_breaks_on_smallest_id(self, knowledge_repo, seeded_tenant):
        stamp = datetime(2026, 8, 24, 12, 0, 0)
        doc_b = self._legacy_doc(seeded_tenant.id, "connector:github:tie")
        doc_a = self._legacy_doc(seeded_tenant.id, "connector:github:tie")
        # Force an exact created_at tie; deterministic rule keeps smallest id.
        for doc in (doc_a, doc_b):
            object.__setattr__(doc, "created_at", stamp)
        await knowledge_repo.create(doc_b)
        await knowledge_repo.create(doc_a)

        await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)

        rows = await knowledge_repo.list_for_tenant(seeded_tenant.id)
        assert len(rows) == 1
        assert rows[0].id == min(doc_a.id, doc_b.id)

        # The loser is deterministically the larger-id row, now archived.
        loser_id = max(doc_a.id, doc_b.id)
        recovered = await knowledge_repo.get_by_id(loser_id, seeded_tenant.id)
        assert recovered.status.value == "archived"

    async def test_archived_chunks_are_retained_but_excluded_from_search(
        self, knowledge_repo, seeded_tenant
    ):
        from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository

        chunk_repo = PostgreSQLKnowledgeChunkRepository(knowledge_repo.db)

        # Two legacy duplicates of one logical document; newest wins.
        older_created = datetime(2026, 8, 20, 9, 0, 0)
        document_old = _document(
            seeded_tenant.id,
            provenance="connector:github:gone",
            created_at=older_created,
        )
        chunks_old = _chunks(document_old, count=1)
        await knowledge_repo.create_document_with_chunks(
            document_old, chunks_old, _embeddings(len(chunks_old))
        )

        document_new = _document(
            seeded_tenant.id,
            provenance="connector:github:gone",
            created_at=datetime(2026, 8, 21, 9, 0, 0),
        )
        chunks_new = _chunks(document_new, count=1)
        await knowledge_repo.create_document_with_chunks(
            document_new, chunks_new, _embeddings(len(chunks_new))
        )

        archived_count = await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)
        assert archived_count == 1

        # Chunks of the archived duplicate are RETAINED (archive-only
        # lifecycle; no deletion anywhere) ...
        async with knowledge_repo.db._connection_pool.acquire() as conn:
            retained = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = $1",
                document_old.id,
            )
        assert retained == 1

        # ...but no longer surface as retrieval candidates, while the
        # winner's chunk does.
        matches = await chunk_repo.search(seeded_tenant.id, [1.0] * 1536, limit=10)
        match_document_ids = {match.document_id for match in matches}
        assert document_old.id not in match_document_ids
        assert document_new.id in match_document_ids

    async def test_get_by_id_still_recovers_archived_documents(self, knowledge_repo, seeded_tenant):
        older = self._legacy_doc(seeded_tenant.id, "connector:github:rec")
        newer = self._legacy_doc(seeded_tenant.id, "connector:github:rec")
        await knowledge_repo.create(older)
        await knowledge_repo.create(newer)
        await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id)

        # Explicit ID lookup still recovers the ARCHIVED duplicate
        # (recovery/audit contract), while the winner stays active.
        recovered = await knowledge_repo.get_by_id(older.id, seeded_tenant.id)
        assert recovered.status.value == "archived"

        winner = await knowledge_repo.get_by_id(newer.id, seeded_tenant.id)
        assert winner.status.value == "active"


class TestLegacyArchivalRetrievalRegression:
    """Archived documents must vanish from RAG/Intelligence candidate paths
    while remaining recoverable by explicit ID."""

    class _PassthroughGuard:
        def sanitize(self, text: str):
            from types import SimpleNamespace

            return SimpleNamespace(sanitized_text=text)

    async def test_approved_search_and_intelligence_exclude_archived_documents(
        self, db, seeded_tenant
    ):
        from arc.domain.models import (
            IntelligenceAnswer,
            KnowledgeSource,
        )
        from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
        from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
        from arc.services.embeddings import DeterministicEmbeddingProvider
        from arc.services.intelligence import UnifiedIntelligenceService
        from arc.services.knowledge import KnowledgeService
        from arc.services.llm import DeterministicLlmProvider
        from arc.services.retrieval import RetrievalService

        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        chunk_repo = PostgreSQLKnowledgeChunkRepository(db)
        indexer = RetrievalService(
            chunk_repo,
            embedding_provider=DeterministicEmbeddingProvider(),
        )
        ingestion = KnowledgeService(
            knowledge_repo,
            pii_guard=self._PassthroughGuard(),
            indexer=indexer,
        )
        context = TenantContext(
            tenant_id=seeded_tenant.id,
            tenant_name="Regression",
            user_id="user-1",
            role=UserRole.MEMBER,
        )

        document_old = await ingestion.ingest_document(
            context,
            source=KnowledgeSource.INTERNAL_KNOWLEDGE,
            provenance="connector:github:legacy-regression",
            content="Unique legacy archival regression body. Older crawl.",
        )
        document_new = await ingestion.ingest_document(
            context,
            source=KnowledgeSource.INTERNAL_KNOWLEDGE,
            provenance="connector:github:legacy-regression",
            content="Unique legacy archival regression body. Newer crawl.",
        )

        # Sanity: BOTH retrievable before archival — this duplication is the
        # exact legacy problem the slice cleans up.
        pre = await indexer.approved_search(context, "legacy archival", limit=5)
        assert {match.document_id for match in pre.items} == {
            document_old.id,
            document_new.id,
        }

        assert await knowledge_repo.archive_legacy_duplicates(seeded_tenant.id) == 1

        post = await indexer.approved_search(context, "legacy archival", limit=5)
        post_ids = {match.document_id for match in post.items}
        assert document_old.id not in post_ids
        assert document_new.id in post_ids

        intelligence = UnifiedIntelligenceService(
            retrieval=indexer,
            llm_provider=DeterministicLlmProvider(),
        )
        answer = await intelligence.answer_query(context, "legacy archival")
        assert isinstance(answer, IntelligenceAnswer)
        assert all(citation.split("#")[0] != document_old.id for citation in answer.citations)
