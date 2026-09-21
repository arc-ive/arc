"""Unit tests for the Unified Intelligence service and domain contract.

Security invariants under test:

- The ONLY retrieval path is ``approved_search``; the service holds no
  repository reference and forwards the trusted tenant context untouched.
- The LLM prompt is assembled from the Approved Context ONLY (sanitized
  content + citation references): no tenant/principal identifiers,
  vectors, scores, or authorization state cross into the prompt.
- When there is no approved context, the LLM is never invoked and the
  answer is ``None`` (nothing is invented).
- Fail closed: embedding and LLM failures propagate with no partial
  answer.
"""

import pytest

from arc.domain.models import (
    ApprovedContext,
    ApprovedContextItem,
    ApprovedContextSecurityMetadata,
    IntelligenceAnswer,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.embeddings import EmbeddingError
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import DeterministicLlmProvider, LlmError


def _context(tenant_id="tenant-1", user_id="user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Tenant One",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _item(document_id="doc-1", content="Approved remote work policy.", sequence=0):
    return ApprovedContextItem(
        document_id=document_id,
        chunk_id=f"{document_id}-c{sequence}",
        content=content,
        source=KnowledgeSource.POLICY,
        provenance="Policy handbook 2026 edition",
        document_version=1,
        sequence=sequence,
        relevance_score=0.95,
        citation_reference=f"{document_id}#c{sequence}",
    )


def _approved(items, tenant_id="tenant-1", user_id="user-1", query="remote work policy"):
    return ApprovedContext(
        request_id="req-1",
        tenant_id=tenant_id,
        principal_id=user_id,
        query=query,
        retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
        items=items,
        security_metadata=ApprovedContextSecurityMetadata(tenant_id=tenant_id),
    )


class FakeLlmProvider:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            "Deterministic response using 1 approved context item(s): doc-1#c0\n"
            "[1] citation: doc-1#c0"
        )


class FakeRetrieval:
    def __init__(self, approved=None, error=None):
        self.approved = approved
        self.error = error
        self.calls = []

    async def approved_search(self, context, query, limit=5):
        self.calls.append((context.tenant_id, context.user_id, query, limit))
        if self.error is not None:
            raise self.error
        return self.approved


class TestIntelligenceAnswerDomain:
    def test_valid_answer_passes(self):
        answer = IntelligenceAnswer(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="remote work policy",
            answer="Some answer",
            citations=["doc-1#c0"],
            retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
            context_used=True,
        )
        assert answer.answer == "Some answer"

    def test_empty_request_id_is_rejected(self):
        with pytest.raises(ValueError):
            IntelligenceAnswer(
                request_id="",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="q",
                answer=None,
            )

    def test_empty_query_is_rejected(self):
        with pytest.raises(ValueError):
            IntelligenceAnswer(
                request_id="req-1",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="  ",
                answer=None,
            )

    def test_answer_none_requires_no_context(self):
        with pytest.raises(ValueError):
            IntelligenceAnswer(
                request_id="req-1",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="q",
                answer="",
                context_used=True,
            )

    def test_citations_must_be_strings(self):
        with pytest.raises(ValueError):
            IntelligenceAnswer(
                request_id="req-1",
                tenant_id="tenant-1",
                principal_id="user-1",
                query="q",
                answer=None,
                citations=[1, 2],
            )


class TestUnifiedIntelligenceService:
    async def test_happy_path_preserves_context_and_citations(self):
        retrieval = FakeRetrieval(_approved([_item()]))
        llm = FakeLlmProvider()
        service = UnifiedIntelligenceService(retrieval, llm)

        answer = await service.answer_query(_context(), "remote work policy")

        assert answer.context_used is True
        assert answer.answer == (
            "Deterministic response using 1 approved context item(s): doc-1#c0\n"
            "[1] citation: doc-1#c0"
        )
        assert answer.citations == ["doc-1#c0"]
        assert answer.tenant_id == "tenant-1"
        assert answer.principal_id == "user-1"
        assert answer.retrieval_method == RetrievalMethod.DENSE_SEMANTIC
        assert retrieval.calls[0][0] == "tenant-1"

    async def test_no_context_never_invokes_the_llm(self):
        retrieval = FakeRetrieval(_approved([]))
        llm = FakeLlmProvider()
        service = UnifiedIntelligenceService(retrieval, llm)

        answer = await service.answer_query(_context(), "remote work policy")

        assert llm.prompts == []
        assert answer.answer is None
        assert answer.citations == []
        assert answer.context_used is False
        assert answer.tenant_id == "tenant-1"

    async def test_prompt_contains_only_content_and_citations(self):
        retrieval = FakeRetrieval(
            _approved(
                [
                    _item(document_id="doc-1", content="Sanitized policy body.", sequence=0),
                    _item(document_id="doc-2", content="Engineering on-call runbook.", sequence=3),
                ]
            )
        )
        llm = FakeLlmProvider()
        service = UnifiedIntelligenceService(retrieval, llm)

        await service.answer_query(_context(), "remote work policy")

        prompt = llm.prompts[0]
        # Expected citation/reference pairs are present.
        assert "[1] citation: doc-1#c0" in prompt
        assert "Sanitized policy body." in prompt
        assert "[2] citation: doc-2#c3" in prompt
        assert "Engineering on-call runbook." in prompt
        # The user query is present.
        assert "QUERY: remote work policy" in prompt
        # ApprovedContext structural header is present.
        assert "APPROVED CONTEXT:" in prompt
        # No tenant/principal identifiers, vectors, scores, or
        # authorization state cross into the LLM prompt.
        assert "tenant-1" not in prompt
        assert "user-1" not in prompt
        assert "0.95" not in prompt
        assert "DENSE_SEMANTIC" not in prompt
        # No ApprovedContext metadata leaks into the prompt.
        assert "req-1" not in prompt
        # No KnowledgeMatch/retrieval metadata leaks into the prompt.
        assert "POLICY" not in prompt
        assert "Policy handbook 2026 edition" not in prompt
        assert "doc-1-c0" not in prompt
        assert "doc-2-c3" not in prompt

    async def test_prompt_structurally_separates_instructions_from_retrieved_content(self):
        """TRD 10: prompts must structurally distinguish instructions from retrieved content."""
        retrieval = FakeRetrieval(_approved([_item(content="Retrieved document body.")]))
        llm = FakeLlmProvider()
        service = UnifiedIntelligenceService(retrieval, llm)

        await service.answer_query(_context(), "question")

        prompt = llm.prompts[0]
        lines = prompt.split("\n")
        # The first line is the system/trusted instruction.
        assert lines[0].startswith("You are Arc's Unified Intelligence.")
        # The retrieved content block has its own labeled header.
        assert "APPROVED CONTEXT:" in lines
        # Retrieved content appears only after the header, not before it.
        assert "Retrieved document body." not in prompt[: prompt.index("APPROVED CONTEXT:")]
        # The query follows the retrieved content.
        assert "QUERY: question" in lines

    async def test_empty_query_is_rejected(self):
        retrieval = FakeRetrieval(_approved([]))
        service = UnifiedIntelligenceService(retrieval)

        with pytest.raises(ValueError):
            await service.answer_query(_context(), "  ")

    async def test_non_positive_limit_is_rejected(self):
        retrieval = FakeRetrieval(_approved([]))
        service = UnifiedIntelligenceService(retrieval)

        with pytest.raises(ValueError):
            await service.answer_query(_context(), "remote work policy", limit=0)

    async def test_embedding_failure_propagates_and_llm_is_never_called(self):
        retrieval = FakeRetrieval(error=EmbeddingError("provider down"))
        llm = FakeLlmProvider()
        service = UnifiedIntelligenceService(retrieval, llm)

        with pytest.raises(EmbeddingError):
            await service.answer_query(_context(), "remote work policy")

        assert llm.prompts == []

    async def test_llm_failure_propagates(self):
        class FailingLlm:
            def complete(self, prompt: str) -> str:
                raise LlmError("model unavailable")

        retrieval = FakeRetrieval(_approved([_item()]))
        service = UnifiedIntelligenceService(retrieval, FailingLlm())

        with pytest.raises(LlmError):
            await service.answer_query(_context(), "remote work policy")

    async def test_default_provider_is_deterministic(self):
        service = UnifiedIntelligenceService(FakeRetrieval(_approved([])))
        assert isinstance(service.llm_provider, DeterministicLlmProvider)

    async def test_partial_citations_only_grounded_items_returned(self):
        """Only citations the LLM actually referenced are returned."""

        class PartialCitationLlm:
            def complete(self, prompt: str) -> str:
                return "Answer using item 1 only.\n[1] citation: doc-1#c0"

        items = [
            _item(document_id="doc-1", content="Policy A.", sequence=0),
            _item(document_id="doc-2", content="Policy B.", sequence=1),
        ]
        retrieval = FakeRetrieval(_approved(items))
        service = UnifiedIntelligenceService(retrieval, PartialCitationLlm())

        answer = await service.answer_query(_context(), "policy question")

        assert answer.citations == ["doc-1#c0"]
        assert "doc-2#c1" not in answer.citations

    async def test_no_citations_when_llm_omits_references(self):
        """When the LLM output contains no citation patterns, citations are empty."""

        class NoCitationLlm:
            def complete(self, prompt: str) -> str:
                return "I cannot answer from the provided context."

        retrieval = FakeRetrieval(_approved([_item()]))
        service = UnifiedIntelligenceService(retrieval, NoCitationLlm())

        answer = await service.answer_query(_context(), "remote work policy")

        assert answer.citations == []
        assert answer.answer == "I cannot answer from the provided context."

    async def test_fabricated_citation_index_ignored(self):
        """Citation indices not in the approved set are silently dropped."""

        class FabricatingLlm:
            def complete(self, prompt: str) -> str:
                return (
                    "Answer referencing a non-existent item.\n"
                    "[1] citation: doc-1#c0\n"
                    "[99] citation: fake-ref#x"
                )

        retrieval = FakeRetrieval(_approved([_item()]))
        service = UnifiedIntelligenceService(retrieval, FabricatingLlm())

        answer = await service.answer_query(_context(), "remote work policy")

        assert answer.citations == ["doc-1#c0"]
