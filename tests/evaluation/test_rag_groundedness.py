"""RAG evaluation: groundedness (Issue #139, V2-ADR-023).

5 production-LLM cases testing that answers are grounded in approved
context and do not contain fabricated claims.

Uses real OpenRouterProvider. Skipped when OPENROUTER_API_KEY is absent.
"""

import os

import pytest

from arc.domain.models import (
    ApprovedContextItem,
    KnowledgeSource,
    RetrievalMethod,
    TenantContext,
    UserRole,
)
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import OpenRouterProvider

from .conftest import EVAL_FREE_MODEL
from .golden_datasets import grounding_fixtures


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _item(index, fact):
    return ApprovedContextItem(
        document_id=f"doc-g-{index}",
        chunk_id=f"doc-g-{index}-c0",
        content=fact,
        source=KnowledgeSource.POLICY,
        provenance="Evaluation fixture",
        document_version=1,
        sequence=0,
        relevance_score=0.9,
        citation_reference=f"doc-g-{index}#c0",
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


def _build_provider():
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenRouterProvider(api_key=api_key, model=EVAL_FREE_MODEL)


def _approved_from_fixture(fixture):
    items = [_item(i, fact) for i, fact in enumerate(fixture["approved_facts"])]
    return _ApprovedContext(items, fixture["query"])


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", grounding_fixtures(), ids=lambda f: f["description"])
async def test_expected_supported_claims_present(fixture):
    """Expected supported claims are present or faithfully represented in answer."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])
    answer_lower = answer.answer.lower()

    for claim in fixture["expected_supported_claims"]:
        assert claim.lower() in answer_lower, (
            f"Expected supported claim missing: {claim}\nAnswer: {answer.answer}"
        )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", grounding_fixtures(), ids=lambda f: f["description"])
async def test_forbidden_claims_absent(fixture):
    """Forbidden fabricated claims are absent from answer."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])
    answer_lower = answer.answer.lower()

    for claim in fixture["forbidden_claims"]:
        assert claim.lower() not in answer_lower, (
            f"Forbidden claim present: {claim}\nAnswer: {answer.answer}"
        )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", grounding_fixtures(), ids=lambda f: f["description"])
async def test_answer_does_not_invent_facts(fixture):
    """Answer does not invent facts beyond what is in approved context."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    # At least one forbidden claim must exist in fixture (sanity check)
    assert len(fixture["forbidden_claims"]) > 0, "Fixture must include forbidden claims"
    # The forbidden claims test above already validates this; this is a structural assertion
    answer_lower = answer.answer.lower()
    for claim in fixture["forbidden_claims"]:
        assert claim.lower() not in answer_lower


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", grounding_fixtures(), ids=lambda f: f["description"])
async def test_answer_reflects_context_not_query(fixture):
    """Answer contains information from context, not just the query text."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    # Answer should contain at least one expected claim not in the query
    query_lower = fixture["query"].lower()
    answer_lower = answer.answer.lower()
    found_context_only = False
    for claim in fixture["expected_supported_claims"]:
        if claim.lower() in answer_lower and claim.lower() not in query_lower:
            found_context_only = True
            break
    assert found_context_only, (
        "Answer does not contain context-specific information beyond the query"
    )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", grounding_fixtures(), ids=lambda f: f["description"])
async def test_multi_item_context_grounding(fixture):
    """Multi-item context: answer references claims from multiple items."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])
    answer_lower = answer.answer.lower()

    # If fixture has multiple expected claims, at least 2 should be present
    present = [c for c in fixture["expected_supported_claims"] if c.lower() in answer_lower]
    assert len(present) >= min(2, len(fixture["expected_supported_claims"])), (
        f"Expected at least 2 claims present, got {len(present)}: {present}"
    )
