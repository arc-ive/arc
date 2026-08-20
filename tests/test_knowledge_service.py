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

from arc.db.connection import NotFoundError
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

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self.created.append(document)
        self.by_id[document.id] = document
        return document

    async def create_document_with_chunks(self, document, chunks, embeddings) -> KnowledgeDocument:
        if self.fail_atomic_chunks:
            raise RuntimeError("chunk persistence failed")
        await self.create(document)
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
