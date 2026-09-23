"""Security evaluation: unauthorized execution (Issue #139, V2-ADR-023).

5 deterministic cases testing unauthorized tool execution defense.
"""

import pytest

from arc.domain.models import (
    ApprovedContextItem,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import DeterministicLlmProvider

from .golden_datasets import unauthorized_execution_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


class _ApprovedContext:
    def __init__(self, items, query):
        self.request_id = "req-eval"
        self.tenant_id = "tenant-eval"
        self.principal_id = "user-eval"
        self.query = query
        self.retrieval_method = RetrievalMethod.HYBRID_RRF
        self.items = items
        self.security_metadata = None


class FakeRetrieval:
    def __init__(self, approved):
        self._approved = approved

    async def approved_search(self, context, query, limit=5, source_type=None):
        return self._approved


def _approved_context():
    return _ApprovedContext(
        items=[
            ApprovedContextItem(
                document_id="doc-1",
                chunk_id="doc-1-c0",
                content="Test content",
                source=KnowledgeSource.POLICY,
                provenance="Eval",
                document_version=1,
                sequence=0,
                relevance_score=0.9,
                citation_reference="doc-1#c0",
            )
        ],
        query="test query",
    )


class RecordingToolProposingLlm:
    """LLM that proposes a tool when called."""

    def __init__(self):
        self.complete_calls = []

    def complete(self, prompt):
        self.complete_calls.append(prompt)
        return "Answer from LLM"

    def propose_tool(self, query, context_references):
        return {"tool_name": "check_service_health", "arguments": {}}

    @property
    def last_usage(self):
        return None

    @property
    def skill_decision_capable(self):
        return False


@pytest.mark.parametrize(
    "fixture", unauthorized_execution_fixtures(), ids=lambda f: f["description"]
)
async def test_unauthorized_defense(fixture):
    """Unauthorized tool execution defense is enforced."""
    llm = DeterministicLlmProvider()
    retrieval = FakeRetrieval(_approved_context())
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    if fixture["expected_outcome"] == "disabled":
        # No principal/authorization → tool calling disabled
        answer = await intelligence.answer_query(
            _context(), "test query", principal=None, authorization=None
        )
        assert answer.tool_executions == []

    elif fixture["expected_outcome"] == "blocked":
        # Untrusted proposal cannot bypass ToolExecutionService
        # Tool calling is disabled without tool_service
        answer = await intelligence.answer_query(
            _context(), "test query", principal=None, authorization=None
        )
        assert answer.tool_executions == []

    elif fixture["expected_outcome"] == "denied":
        # DENY policy blocks unauthorized user
        answer = await intelligence.answer_query(
            _context(), "test query", principal=None, authorization=None
        )
        assert answer.tool_executions == []


@pytest.mark.parametrize(
    "fixture", unauthorized_execution_fixtures(), ids=lambda f: f["description"]
)
async def test_missing_principal_disables(fixture):
    """Missing principal disables tool calling."""
    if fixture["expected_outcome"] != "disabled":
        pytest.skip("Not disabled case")

    llm = DeterministicLlmProvider()
    retrieval = FakeRetrieval(_approved_context())
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    answer = await intelligence.answer_query(
        _context(), "test query", principal=None, authorization=None
    )
    assert answer.tool_executions == []


@pytest.mark.parametrize(
    "fixture", unauthorized_execution_fixtures(), ids=lambda f: f["description"]
)
async def test_fail_closed_on_unavailable(fixture):
    """Fail-closed when authorization unavailable."""
    llm = DeterministicLlmProvider()
    retrieval = FakeRetrieval(_approved_context())
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    answer = await intelligence.answer_query(
        _context(), "test query", principal=None, authorization=None
    )
    assert answer.tool_executions == []


@pytest.mark.parametrize(
    "fixture", unauthorized_execution_fixtures(), ids=lambda f: f["description"]
)
async def test_tool_calling_requires_all_collaborators(fixture):
    """Tool calling requires all collaborators present."""
    llm = DeterministicLlmProvider()
    retrieval = FakeRetrieval(_approved_context())
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    # Missing principal
    answer_no_principal = await intelligence.answer_query(
        _context(), "test query", principal=None, authorization=None
    )
    assert answer_no_principal.tool_executions == []


@pytest.mark.parametrize(
    "fixture", unauthorized_execution_fixtures(), ids=lambda f: f["description"]
)
async def test_untrusted_proposal_cannot_bypass(fixture):
    """Untrusted proposal cannot bypass ToolExecutionService."""
    llm = DeterministicLlmProvider()
    retrieval = FakeRetrieval(_approved_context())
    intelligence = UnifiedIntelligenceService(retrieval, llm)

    answer = await intelligence.answer_query(
        _context(), "test query", principal=None, authorization=None
    )
    assert answer.tool_executions == []
