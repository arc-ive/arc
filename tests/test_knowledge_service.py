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
    """In-memory KnowledgeRepository capturing persisted documents."""

    def __init__(self):
        self.created: List[KnowledgeDocument] = []
        self.by_id = {}

    async def create(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self.created.append(document)
        self.by_id[document.id] = document
        return document

    async def get_by_id(self, document_id: str, tenant_id: str) -> KnowledgeDocument:
        document = self.by_id.get(document_id)
        if document is None or document.tenant_id != tenant_id:
            raise NotFoundError(f"missing {document_id}")
        return document

    async def list_for_tenant(self, tenant_id: str) -> List[KnowledgeDocument]:
        return [d for d in self.created if d.tenant_id == tenant_id]


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
