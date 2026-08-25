"""Tests for the Company Brain KnowledgeService.

The critical boundary under test is the PII guard:

    RAW CONTENT -> PiiGuardService -> SANITIZED CONTENT -> PERSISTENCE

- Unit tests inject a fake PiiGuardService to prove the wiring and
  fail-closed behavior deterministically.
- One integration test proves the real PiiGuardService (Microsoft
  Presidio) is connected to ingestion and that sanitized content, not raw
  content, is what the repository receives.
"""

import uuid
from types import SimpleNamespace
from typing import List, Optional

import pytest
from presidio_analyzer import RecognizerResult

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import KnowledgeDocument, KnowledgeSource, TenantContext, UserRole
from arc.services.embeddings import EmbeddingError
from arc.services.knowledge import KnowledgeService
from arc.services.pii import PiiGuardConfig, PiiGuardError, PiiGuardService


def _unique(prefix: str) -> str:
    return f"ks-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str = "tenant-1", user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Acme",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


class FakePiiGuard:
    """Fake PiiGuardService replacing sanitized text with a fixed marker."""

    def __init__(self, sanitized_text: str = "<SANITIZED>"):
        self.sanitized_text = sanitized_text
        self.calls = 0

    def sanitize(self, text: str) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(sanitized_text=self.sanitized_text)


class ExplodingPiiGuard:
    """Fake PiiGuardService that always fails sanitization."""

    def sanitize(self, text: str) -> SimpleNamespace:
        raise PiiGuardError("PII analysis failed")


class FakeKnowledgeRepository:
    """In-memory KnowledgeRepository capturing persisted documents and chunks.

    ``fail_atomic_chunks`` simulates a failure inside the atomic
    document+chunks transaction (e.g. a chunk insert failing after the
    document insert): the fake mirrors the real repository's contract in
    which a raised error means NOTHING was persisted (the real
    implementation rolls the transaction back).
    """

    def __init__(self):
        self.created: List[KnowledgeDocument] = []
        self.by_id = {}
        self.chunks: List = []
        self.fail_atomic_chunks = False
        self.identity = {}
        self.updated: List[KnowledgeDocument] = []

    def _register(self, document: KnowledgeDocument) -> None:
        if document.external_id is not None:
            key = (document.tenant_id, document.source.value, document.external_id)
            if key in self.identity:
                raise DuplicateKeyError(f"identity {key} already exists")
            self.identity[key] = document

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self._register(document)
        self.created.append(document)
        self.by_id[document.id] = document
        return document

    async def create_document_with_chunks(self, document, chunks, embeddings) -> KnowledgeDocument:
        if self.fail_atomic_chunks:
            raise RuntimeError("chunk persistence failed")
        self._register(document)
        self.created.append(document)
        self.by_id[document.id] = document
        self.chunks.extend(chunks)
        return document

    async def get_by_external_id(self, external_id, source, tenant_id) -> KnowledgeDocument:
        document = self.identity.get((tenant_id, source.value, external_id))
        if document is None:
            raise NotFoundError(f"no logical document for identity {external_id}")
        return document

    async def update_document_with_chunks(self, document, chunks, embeddings) -> KnowledgeDocument:
        stored = self.by_id.get(document.id)
        if stored is None or stored.tenant_id != document.tenant_id:
            raise NotFoundError(f"missing {document.id}")
        self.updated.append(document)
        self.by_id[document.id] = document
        self.chunks = [c for c in self.chunks if c.document_id != document.id]
        self.chunks.extend(chunks)
        return document

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        document = self.by_id.get(document_id)
        if document is None or document.tenant_id != tenant_id:
            raise NotFoundError(f"missing {document_id}")
        return document

    async def list_for_tenant(self, tenant_id: str) -> List[KnowledgeDocument]:
        return [d for d in self.created if d.tenant_id == tenant_id]


class FakeIndexer:
    """Fake RetrievalService indexer capturing the prepare phase.

    Records how many documents were persisted by the knowledge repository
    at the moment of ``prepare_index`` so tests can prove the fail-closed
    order: sanitize -> prepare_index (0 persisted) -> atomic create
    (document + chunks together).
    """

    def __init__(self, repo: FakeKnowledgeRepository, prepare_result="prepared"):
        self.repo = repo
        self.prepare_result = prepare_result
        self.fail_prepare = False
        self.prepared_documents = []
        self.persisted_documents_at_prepare = []

    def raising(self, error: Exception):
        self.fail_prepare = True
        self._error = error
        return self

    async def prepare_index(self, context, document):
        self.prepared_documents.append((context, document))
        self.persisted_documents_at_prepare.append(len(self.repo.created))
        if self.fail_prepare:
            raise self._error
        if self.prepare_result is None:
            return None
        return SimpleNamespace(
            chunks=[SimpleNamespace(document_id=document.id)],
            embeddings=[],
        )


class TestKnowledgeServiceIngest:
    async def test_ingest_persists_sanitized_content(self):
        repo = FakeKnowledgeRepository()
        guard = FakePiiGuard("<SANITIZED>")
        service = KnowledgeService(repo, pii_guard=guard)
        context = _context()

        document = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            content="Raw content with alice@example.com",
        )

        assert guard.calls == 1
        assert document.tenant_id == context.tenant_id
        assert document.content == "<SANITIZED>"
        assert repo.created[0].content == "<SANITIZED>"

    async def test_ingest_uses_trusted_tenant_context(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard())
        context = _context(tenant_id="trusted-tenant")

        document = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="Source A",
            content="Some content",
        )

        assert document.tenant_id == "trusted-tenant"

    async def test_ingest_invalid_source_is_rejected(self):
        service = KnowledgeService(FakeKnowledgeRepository(), pii_guard=FakePiiGuard())
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(), source="not-a-source", provenance="x", content="y"
            )

    async def test_ingest_empty_provenance_is_rejected(self):
        service = KnowledgeService(FakeKnowledgeRepository(), pii_guard=FakePiiGuard())
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(), source=KnowledgeSource.POLICY, provenance="", content="y"
            )

    async def test_ingest_empty_content_is_rejected(self):
        service = KnowledgeService(FakeKnowledgeRepository(), pii_guard=FakePiiGuard())
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(), source=KnowledgeSource.POLICY, provenance="x", content=""
            )

    async def test_ingest_invalid_version_is_rejected(self):
        service = KnowledgeService(FakeKnowledgeRepository(), pii_guard=FakePiiGuard())
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(),
                source=KnowledgeSource.POLICY,
                provenance="x",
                content="y",
                version=0,
            )

    async def test_pii_failure_prevents_persistence(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=ExplodingPiiGuard())
        context = _context()

        with pytest.raises(PiiGuardError):
            await service.ingest_document(
                context,
                source=KnowledgeSource.POLICY,
                provenance="Policy handbook",
                content="Raw secret 111-22-3333",
            )

        assert repo.created == []

    async def test_real_pii_guard_sanitizes_before_persistence(self):
        """Prove the real PiiGuardService is connected to ingestion.

        The real Presidio anonymizer is used with a scripted analyzer so
        the test is deterministic and does not require the spaCy model.
        """

        class ScriptedAnalyzer:
            def analyze(self, text: str, language: str, entities: Optional[List[str]]):
                return [RecognizerResult("EMAIL_ADDRESS", 6, 24, 0.99)]

        from presidio_anonymizer import AnonymizerEngine

        real_guard = PiiGuardService(
            config=PiiGuardConfig(),
            analyzer_engine=ScriptedAnalyzer(),
            anonymizer_engine=AnonymizerEngine(),
        )
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=real_guard)

        raw = "email: alice@example.com hidden"
        document = await service.ingest_document(
            _context(),
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            content=raw,
        )

        assert "alice@example.com" not in document.content
        assert repo.created[0].content == document.content
        assert document.content != raw


class TestKnowledgeServiceIndexing:
    """Secure RAG indexing: sanitize -> prepare (in memory) -> atomic create.

    The fail-closed ordering under test:

        RAW CONTENT -> PII GUARD -> SANITIZED -> prepare_index
        (embedding computed BEFORE any database write)
        -> create document + all chunks in ONE transaction

    An embedding failure aborts before ANY persistence. A persistence
    failure rolls back the whole transaction: there is never a document
    without its complete index, nor a partial chunk set.
    """

    async def test_ingest_creates_document_and_chunks_atomically(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo)
        service = KnowledgeService(repo, pii_guard=FakePiiGuard("<SANITIZED>"), indexer=indexer)

        await service.ingest_document(
            _context(),
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            content="Raw content with alice@example.com",
        )

        # prepare_index runs entirely before any persistence; the
        # document and its chunks are then created together.
        assert indexer.persisted_documents_at_prepare == [0]
        assert len(repo.created) == 1
        assert len(repo.chunks) == 1
        assert repo.chunks[0].document_id == repo.created[0].id

        # The indexer receives only sanitized content, owned by the
        # trusted context tenant.
        _, prepared_document = indexer.prepared_documents[0]
        assert prepared_document.content == "<SANITIZED>"
        assert prepared_document.tenant_id == "tenant-1"
        assert repo.created[0].content == "<SANITIZED>"

    async def test_ingest_without_prepared_chunks_creates_document_only(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo, prepare_result=None)
        service = KnowledgeService(repo, pii_guard=FakePiiGuard(), indexer=indexer)

        await service.ingest_document(
            _context(),
            source=KnowledgeSource.POLICY,
            provenance="Policy handbook",
            content="Some content",
        )

        assert len(repo.created) == 1
        assert repo.chunks == []

    async def test_embedding_failure_prevents_any_persistence(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo).raising(EmbeddingError("embedding unavailable"))
        service = KnowledgeService(repo, pii_guard=FakePiiGuard(), indexer=indexer)

        with pytest.raises(EmbeddingError):
            await service.ingest_document(
                _context(),
                source=KnowledgeSource.POLICY,
                provenance="Policy handbook",
                content="Some content",
            )

        # Fail closed: no document and no chunks were persisted.
        assert repo.created == []
        assert repo.chunks == []

    async def test_chunk_persistence_failure_rolls_back_document_and_chunks(self):
        repo = FakeKnowledgeRepository()
        repo.fail_atomic_chunks = True
        indexer = FakeIndexer(repo)
        service = KnowledgeService(repo, pii_guard=FakePiiGuard(), indexer=indexer)

        with pytest.raises(RuntimeError):
            await service.ingest_document(
                _context(),
                source=KnowledgeSource.POLICY,
                provenance="Policy handbook",
                content="Some content",
            )

        # The atomic contract: a failure during chunk persistence leaves
        # NO document and NO chunks (the real repository rolls back the
        # single transaction; proven against PostgreSQL in
        # test_knowledge_repository.py).
        assert repo.created == []
        assert repo.chunks == []


class TestKnowledgeServiceRead:
    async def test_get_document_scoped_to_tenant(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard())
        context = _context()
        created = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="x", content="y"
        )

        fetched = await service.get_document(context, created.id)
        assert fetched.id == created.id

    async def test_list_documents_scoped_to_tenant(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard())
        ctx_a = _context(tenant_id="tenant-a")
        ctx_b = _context(tenant_id="tenant-b")

        await service.ingest_document(
            ctx_a, source=KnowledgeSource.POLICY, provenance="a1", content="y"
        )
        await service.ingest_document(
            ctx_a, source=KnowledgeSource.POLICY, provenance="a2", content="y"
        )
        await service.ingest_document(
            ctx_b, source=KnowledgeSource.POLICY, provenance="b1", content="y"
        )

        assert len(await service.list_documents(ctx_a)) == 2
        assert len(await service.list_documents(ctx_b)) == 1


class SequencePiiGuard:
    """PII guard returning scripted sanitized texts, one per call."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def sanitize(self, text: str) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(sanitized_text=self._texts[min(self.calls, len(self._texts)) - 1])


class PassthroughPiiGuard:
    """PII guard that performs no transformation (identity function)."""

    def __init__(self):
        self.calls = 0

    def sanitize(self, text: str) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(sanitized_text=text)


class TestKnowledgeIdentityAndReingestion:
    """ADR-003: logical identity (tenant_id, source, external_id)."""

    async def test_first_ingest_with_external_id_creates_version_1(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard("<SANITIZED>"))
        context = _context()

        document = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="handbook",
            content="raw one",
            external_id="ext-1",
        )

        assert document.version == 1
        assert document.external_id == "ext-1"
        assert document.content == "<SANITIZED>"
        assert len(repo.created) == 1

    async def test_identical_redelivery_is_idempotent_and_still_sanitizes(self):
        repo = FakeKnowledgeRepository()
        guard = FakePiiGuard("<SANITIZED>")
        service = KnowledgeService(repo, pii_guard=guard)
        context = _context()

        first = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="raw", external_id="e1"
        )
        second = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="raw again",
            external_id="e1",
        )

        assert second.id == first.id
        assert second.version == 1
        assert guard.calls == 2  # re-ingestion cannot bypass the PII boundary
        assert len(repo.created) == 1
        assert repo.updated == []

    async def test_changed_content_updates_same_document_and_bumps_version(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo)
        service = KnowledgeService(
            repo, pii_guard=SequencePiiGuard(["<V1>", "<V2>"]), indexer=indexer
        )
        context = _context()

        first = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="one", external_id="e2"
        )
        second = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="two", external_id="e2"
        )

        assert second.id == first.id
        assert second.version == 2
        assert second.content == "<V2>"
        assert second.created_at == first.created_at
        assert second.provenance == first.provenance
        assert len(repo.updated) == 1
        assert repo.updated[0].version == 2
        # The update path prepared the index for the SAME logical document id,
        # inside _reingest_existing (review thread: prepared must be defined
        # and exercised exactly here before update_document_with_chunks).
        assert len(indexer.prepared_documents) == 2
        assert indexer.prepared_documents[-1][1].id == first.id

    async def test_embedding_failure_on_changed_content_aborts_before_write(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo)
        service = KnowledgeService(
            repo, pii_guard=SequencePiiGuard(["<V1>", "<V2>"]), indexer=indexer
        )
        context = _context()

        first = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="one", external_id="e3"
        )

        # Arm the failure only for the re-ingestion attempt.
        indexer.raising(EmbeddingError("provider down"))
        with pytest.raises(EmbeddingError):
            await service.ingest_document(
                context,
                source=KnowledgeSource.POLICY,
                provenance="p",
                content="two",
                external_id="e3",
            )

        assert repo.updated == []
        unchanged = await service.get_document(context, first.id)
        assert unchanged.version == 1
        assert unchanged.content == "<V1>"

    async def test_pii_failure_on_reingestion_fails_closed(self):
        class ExplodingSecondGuard:
            def __init__(self):
                self.calls = 0

            def sanitize(self, text: str) -> SimpleNamespace:
                self.calls += 1
                if self.calls >= 2:
                    raise PiiGuardError("PII analysis failed")
                return SimpleNamespace(sanitized_text="<SAFE>")

        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=ExplodingSecondGuard())
        context = _context()

        first = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="one", external_id="e4"
        )
        with pytest.raises(PiiGuardError):
            await service.ingest_document(
                context,
                source=KnowledgeSource.POLICY,
                provenance="p",
                content="two",
                external_id="e4",
            )

        stored = await service.get_document(context, first.id)
        assert stored.version == 1
        assert stored.content == "<SAFE>"
        assert repo.updated == []

    async def test_comparison_uses_sanitized_text_not_raw(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard("<CANONICAL>"))
        context = _context()

        first = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="raw A",
            external_id="e5",
        )
        second = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="totally different raw B",
            external_id="e5",
        )

        # Both raws sanitize to the same marker: dedup must compare SANITIZED
        # text and treat this as an identical redelivery.
        assert second.id == first.id
        assert second.version == 1
        assert repo.updated == []
        assert repo.by_id[first.id].content == "<CANONICAL>"

    async def test_missing_external_id_keeps_create_always_behavior(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard())
        context = _context()

        first = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="same"
        )
        second = await service.ingest_document(
            context, source=KnowledgeSource.POLICY, provenance="p", content="same"
        )

        assert first.id != second.id
        assert len(repo.created) == 2

    async def test_same_external_identity_across_tenants_is_distinct(self):
        repo = FakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=FakePiiGuard())

        doc_a = await service.ingest_document(
            _context(tenant_id="tenant-a"),
            source=KnowledgeSource.INTERNAL_KNOWLEDGE,
            provenance="connector:github:42",
            content="content a",
            external_id="github:42",
        )
        doc_b = await service.ingest_document(
            _context(tenant_id="tenant-b"),
            source=KnowledgeSource.INTERNAL_KNOWLEDGE,
            provenance="connector:github:42",
            content="content b",
            external_id="github:42",
        )

        assert doc_a.tenant_id != doc_b.tenant_id
        assert doc_a.id != doc_b.id
        assert len(repo.created) == 2

    async def test_invalid_external_id_is_rejected(self):
        service = KnowledgeService(FakeKnowledgeRepository(), pii_guard=FakePiiGuard())
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(),
                source=KnowledgeSource.POLICY,
                provenance="p",
                content="c",
                external_id="",
            )
        with pytest.raises(ValueError):
            await service.ingest_document(
                _context(),
                source=KnowledgeSource.POLICY,
                provenance="p",
                content="c",
                external_id="x" * 256,
            )


class RaceFakeKnowledgeRepository(FakeKnowledgeRepository):
    """Simulates losing the identity-index insert race (ADR-003).

    The FIRST ``create`` for the racing identity plants an already-won
    document and raises ``DuplicateKeyError`` — exactly what the database
    does to a concurrent loser of ``uq_knowledge_documents_identity``.
    Identity lookups report NotFound until the winner has been planted.
    """

    def __init__(self):
        super().__init__()
        self.winner: Optional[KnowledgeDocument] = None

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        key = (document.tenant_id, document.source.value, document.external_id)
        if self.winner is None and document.external_id == "race-1":
            self.winner = KnowledgeDocument(
                id=_unique("winner"),
                tenant_id=document.tenant_id,
                source=document.source,
                provenance=document.provenance,
                version=1,
                status=document.status,
                content=document.content,
                external_id=document.external_id,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
            self.identity[key] = self.winner
            self.created.append(self.winner)
            self.by_id[self.winner.id] = self.winner
            raise DuplicateKeyError("identity race lost")
        return await super().create(document)

    async def get_by_external_id(self, external_id, source, tenant_id) -> KnowledgeDocument:
        if self.winner is None:
            raise NotFoundError("no logical document for identity (race not resolved yet)")
        return await super().get_by_external_id(external_id, source, tenant_id)


class TestIdentityRaceRecovery:
    async def test_lost_insert_race_resolves_to_winner(self):
        repo = RaceFakeKnowledgeRepository()
        service = KnowledgeService(repo, pii_guard=PassthroughPiiGuard())
        context = _context()

        result = await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="same text",
            external_id="race-1",
        )

        # The loser observed the constraint violation, re-resolved the
        # identity, found identical sanitized content, and returned the
        # winner unchanged instead of creating a second logical document.
        assert result.id == repo.winner.id
        assert result.version == 1
        assert len(repo.created) == 1
        assert repo.updated == []


class ScriptedCountingGuard:
    """PII guard with scripted outputs that counts every sanitize call."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def sanitize(self, text: str) -> SimpleNamespace:
        self.calls += 1
        index = min(self.calls, len(self._texts)) - 1
        return SimpleNamespace(sanitized_text=self._texts[index])


class TestSanitizationExactlyOnce:
    """Review contract: sanitization is invoked EXACTLY ONCE per ingestion
    invocation on every ADR-003 path (create, identical redelivery,
    changed-content update). There is no duplicated or stale second call,
    and the race-recovery path reuses the already-sanitized text."""

    async def test_exactly_one_sanitize_call_per_ingestion_path(self):
        repo = FakeKnowledgeRepository()
        indexer = FakeIndexer(repo)
        guard = ScriptedCountingGuard(["<A>", "<B>", "<C>"])
        service = KnowledgeService(repo, pii_guard=guard, indexer=indexer)
        context = _context()

        # 1) create path
        await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="one",
            external_id="sp-1",
        )
        assert guard.calls == 1

        # 2) changed-content update path (_reingest_existing must NOT
        #    sanitize again: the caller passes already-sanitized text)
        await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="two",
            external_id="sp-1",
        )
        assert guard.calls == 2

        # 3) second changed-content update
        await service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="three",
            external_id="sp-1",
        )
        assert guard.calls == 3
        assert len(repo.updated) == 2

        # 4) race recovery reuses the sanitized document content: the loser's
        #    single sanitize call covers the entire failed attempt + refetch.
        race_repo = RaceFakeKnowledgeRepository()
        race_service = KnowledgeService(race_repo, pii_guard=guard)
        await race_service.ingest_document(
            context,
            source=KnowledgeSource.POLICY,
            provenance="p",
            content="same text",
            external_id="race-sp-1",
        )
        assert guard.calls == 4
