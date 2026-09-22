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
from arc.services.intelligence import UnifiedIntelligenceService, _extract_grounded_citations
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


def _two_items():
    """Approved items with references doc-a#c1 and doc-b#c2."""
    return [
        _item(document_id="doc-a", content="Escalation procedure.", sequence=1),
        _item(document_id="doc-b", content="Notification policy.", sequence=2),
    ]


class TestExtractGroundedCitations:
    """Parser tests using raw model-output strings the deterministic
    provider did NOT generate (#211, PR #257 review).

    These prove the parser and the provider are not two halves of the
    same assumption: every input here is a realistic shape a real LLM
    emits, and resolution keys only on the approved set.
    """

    def test_explicit_citation_line(self) -> None:
        output = "Escalate to on-call.\n[1] citation: doc-a#c1"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_bare_index_marker(self) -> None:
        output = "Escalate to on-call [1]."
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_multiple_citations_in_order(self) -> None:
        output = "Follow the incident procedure [1] and notify the security team [2]."
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1", "doc-b#c2"]

    def test_no_citations(self) -> None:
        output = "Escalate to on-call immediately."
        assert _extract_grounded_citations(output, _two_items()) == []

    def test_fabricated_index_dropped(self) -> None:
        output = "Use [9] citation: doc-evil#c1 and [1] citation: doc-a#c1"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_fabricated_reference_resolves_by_index_only(self) -> None:
        """An approved index with an injected reference yields the
        approved reference, never the model-supplied string."""
        output = "[1] citation: doc-evil#c1"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_duplicate_citations_deduplicated(self) -> None:
        output = "[1] citation: doc-a#c1\n[1] citation: doc-a#c1"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_natural_reference_mention(self) -> None:
        output = "According to doc-a#c1, you should escalate."
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_sources_list(self) -> None:
        output = "Escalate.\n\nSources: doc-a#c1, doc-b#c2"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1", "doc-b#c2"]

    def test_parenthesized_reference(self) -> None:
        output = "Escalate immediately (doc-a#c1)."
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_footnote_reference(self) -> None:
        output = "Escalate.[^1]\n\n[^1]: doc-a#c1"
        assert _extract_grounded_citations(output, _two_items()) == ["doc-a#c1"]

    def test_unknown_raw_reference_ignored(self) -> None:
        output = "See doc-evil#c1 for details."
        assert _extract_grounded_citations(output, _two_items()) == []

    def test_reference_prefix_collision(self) -> None:
        """doc-a#c1 must not match inside a mention of doc-a#c10."""
        items = _two_items() + [_item(document_id="doc-a", content="Extra.", sequence=10)]
        output = "See doc-a#c10."
        assert _extract_grounded_citations(output, items) == ["doc-a#c10"]

    def test_empty_inputs(self) -> None:
        assert _extract_grounded_citations("", _two_items()) == []
        assert _extract_grounded_citations("Escalate [1].", []) == []


class TestNaturalCitationIntegration:
    """End-to-end grounding with a natural-format scripted LLM."""

    async def test_natural_format_answer_cites_approved_items(self):
        class NaturalLlm:
            def complete(self, prompt: str) -> str:
                return "Follow the incident procedure [1] and notify the security team [2]."

        service = UnifiedIntelligenceService(FakeRetrieval(_approved(_two_items())), NaturalLlm())

        answer = await service.answer_query(_context(), "how do we handle incidents?")

        assert answer.citations == ["doc-a#c1", "doc-b#c2"]
        assert answer.context_used is True


class TestContextBudget:
    """Prompt assembly is bounded by a character budget (#217)."""

    def test_budget_caps_total_content_chars(self):
        """Items are included until the budget is exhausted."""
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
        )
        from arc.services.intelligence import UnifiedIntelligenceService

        items = [
            ApprovedContextItem(
                document_id=f"doc-{i}",
                chunk_id=f"chunk-{i}",
                content="x" * 200,
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference=f"doc-{i}#c0",
            )
            for i in range(10)
        ]
        approved = ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="test",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )

        prompt = UnifiedIntelligenceService._build_prompt(
            approved, "test query", context_budget=500
        )

        # Budget is 500 chars. Each item has ~30 chars overhead + 200 content.
        # Should include only a few items before budget is hit.
        assert len(prompt) <= 500 + 200  # small margin for the fixed lines
        assert "...[truncated]" in prompt or prompt.count("[") < 10

    def test_budget_truncates_last_item_content(self):
        """The last item's content is truncated when it overflows the budget."""
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
        )
        from arc.services.intelligence import UnifiedIntelligenceService

        items = [
            ApprovedContextItem(
                document_id="doc-1",
                chunk_id="chunk-1",
                content="ab",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference="doc-1#c0",
            ),
            ApprovedContextItem(
                document_id="doc-2",
                chunk_id="chunk-2",
                content="x" * 500,
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.8,
                citation_reference="doc-2#c0",
            ),
        ]
        approved = ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="test",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )

        # Budget is large enough for first item + citation line of second,
        # but not the full 500-char content of the second item.
        prompt = UnifiedIntelligenceService._build_prompt(
            approved, "test query", context_budget=300
        )

        # First item fits fully
        assert "[1] citation: doc-1#c0" in prompt
        assert "ab" in prompt
        # Second item's citation line fits, content is truncated
        assert "[2] citation: doc-2#c0" in prompt
        assert "...[truncated]" in prompt

    def test_empty_items_produces_valid_prompt(self):
        """Empty approved context still produces a valid prompt."""
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextSecurityMetadata,
            RetrievalMethod,
        )
        from arc.services.intelligence import UnifiedIntelligenceService

        approved = ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="test",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=[],
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )

        prompt = UnifiedIntelligenceService._build_prompt(approved, "test query")

        assert "QUERY: test query" in prompt
        assert "APPROVED CONTEXT:" in prompt

    def test_budget_with_observations_still_works(self):
        """Observations are appended after context, within or beyond budget."""
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
        )
        from arc.services.intelligence import UnifiedIntelligenceService

        items = [
            ApprovedContextItem(
                document_id="doc-1",
                chunk_id="chunk-1",
                content="content",
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference="doc-1#c0",
            ),
        ]
        approved = ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="test",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )

        prompt = UnifiedIntelligenceService._build_prompt(
            approved, "test query", observation={"status": "executed"}, context_budget=100
        )

        assert "TOOL OBSERVATION" in prompt
        assert "QUERY: test query" in prompt


class TestIntelligenceSettings:
    """PROMPT_CONTEXT_MAX_CHARS validation (#217, review follow-up)."""

    def test_default_is_8192(self, monkeypatch) -> None:
        from arc.services.intelligence import get_intelligence_settings

        monkeypatch.delenv("PROMPT_CONTEXT_MAX_CHARS", raising=False)
        assert get_intelligence_settings().prompt_context_max_chars == 8192

    def test_valid_configured_value(self, monkeypatch) -> None:
        from arc.services.intelligence import get_intelligence_settings

        monkeypatch.setenv("PROMPT_CONTEXT_MAX_CHARS", "4096")
        assert get_intelligence_settings().prompt_context_max_chars == 4096

    def test_malformed_value_raises_actionable_error(self, monkeypatch) -> None:
        from arc.services.intelligence import (
            IntelligenceConfigurationError,
            get_intelligence_settings,
        )

        monkeypatch.setenv("PROMPT_CONTEXT_MAX_CHARS", "abc")
        try:
            get_intelligence_settings()
            raise AssertionError("expected IntelligenceConfigurationError")
        except IntelligenceConfigurationError as exc:
            assert "PROMPT_CONTEXT_MAX_CHARS" in str(exc)

    def test_non_positive_value_rejected(self, monkeypatch) -> None:
        from arc.services.intelligence import (
            IntelligenceConfigurationError,
            get_intelligence_settings,
        )

        for bad in ("0", "-5"):
            monkeypatch.setenv("PROMPT_CONTEXT_MAX_CHARS", bad)
            try:
                get_intelligence_settings()
                raise AssertionError(f"expected error for {bad!r}")
            except IntelligenceConfigurationError:
                pass

    def test_malformed_env_fails_service_construction(self, monkeypatch) -> None:
        """Bad configuration fails fast at construction, not per query."""
        from arc.services.intelligence import IntelligenceConfigurationError

        monkeypatch.setenv("PROMPT_CONTEXT_MAX_CHARS", "abc")
        try:
            UnifiedIntelligenceService(FakeRetrieval(_approved([])))
            raise AssertionError("expected IntelligenceConfigurationError")
        except IntelligenceConfigurationError:
            pass


class TestContextBudgetPrecision:
    """Exact budget accounting: suffix reservation and citation identity."""

    def _approved_two(self):
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
        )

        items = [
            ApprovedContextItem(
                document_id="doc-1",
                chunk_id="chunk-1",
                content="y" * 500,
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference="doc-1#c0",
            ),
        ]
        return ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="q",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )

    def test_truncated_content_fits_budget_including_suffix(self) -> None:
        """Truncation reserves the suffix length: no overshoot."""
        from arc.services.intelligence import UnifiedIntelligenceService

        approved = self._approved_two()
        budget = 300
        prompt = UnifiedIntelligenceService._build_prompt(approved, "q", context_budget=budget)

        assert "...[truncated]" in prompt
        # Context block (everything before QUERY:) fits the budget exactly.
        context_block = prompt.split("QUERY:")[0]
        assert len(context_block) <= budget + 1  # +1 trailing newline before QUERY
        # Citation identity untouched by content truncation.
        assert "[1] citation: doc-1#c0" in prompt

    async def test_answer_query_uses_configured_budget(self) -> None:
        """The service wires its configured budget into prompt assembly."""

        class RecordingLlm:
            def __init__(self):
                self.prompts = []

            def complete(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return "answer [1]"

        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
        )

        items = [
            ApprovedContextItem(
                document_id=f"doc-{i}",
                chunk_id=f"chunk-{i}",
                content="z" * 200,
                source=KnowledgeSource.POLICY,
                provenance="p",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference=f"doc-{i}#c0",
            )
            for i in range(5)
        ]
        approved = ApprovedContext(
            request_id="req-1",
            tenant_id="tenant-1",
            principal_id="user-1",
            query="q",
            retrieval_method=RetrievalMethod.HYBRID_RRF,
            items=items,
            security_metadata=ApprovedContextSecurityMetadata(tenant_id="tenant-1"),
        )
        llm = RecordingLlm()
        service = UnifiedIntelligenceService(FakeRetrieval(approved), llm, context_budget=300)

        answer = await service.answer_query(_context(), "budget question")

        assert "...[truncated]" in llm.prompts[0]
        assert llm.prompts[0].count("citation:") < 5
        assert answer.context_used is True
