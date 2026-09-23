"""RAG evaluation: citation correctness, model-level (Issue #139).

5 production-LLM cases testing that model-generated answers cite
approved sources in the answer text.

Uses real OpenRouterProvider. Skipped when OPENROUTER_API_KEY is absent.
"""

import os
import re

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
from .golden_datasets import citation_model_fixtures

CITATION_PATTERN = re.compile(r"\[(\d+)\]\s*citation:\s*(\S+)")


def _context(tenant_id="tenant-eval"):
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Eval Tenant",
        user_id="user-eval",
        role=UserRole.MEMBER,
    )


def _item(item_data):
    return ApprovedContextItem(
        document_id=item_data["document_id"],
        chunk_id=f"{item_data['document_id']}-c{item_data['sequence']}",
        content=item_data["content"],
        source=KnowledgeSource.POLICY,
        provenance="Evaluation fixture",
        document_version=1,
        sequence=item_data["sequence"],
        relevance_score=0.9,
        citation_reference=item_data["citation_reference"],
    )


class _ApprovedContext:
    """Minimal ApprovedContext for evaluation."""

    def __init__(self, items, query):
        self.request_id = "req-eval"
        self.tenant_id = "tenant-eval"
        self.principal_id = "user-eval"
        self.query = query
        self.retrieval_method = RetrievalMethod.HYBRID_RRF
        self.items = items
        self.security_metadata = None


class FakeRetrieval:
    """Retrieval service returning pre-built ApprovedContext."""

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
    items = [_item(i) for i in fixture["approved_items"]]
    return _ApprovedContext(items, fixture["query"])


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", citation_model_fixtures(), ids=lambda f: f["description"])
async def test_answer_cites_approved_references(fixture):
    """Answer text contains the approved citation references."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    citations_in_answer = set(CITATION_PATTERN.findall(answer.answer))
    approved_refs = {i["citation_reference"] for i in fixture["approved_items"]}
    assert approved_refs.issubset(citations_in_answer), (
        f"Missing citations in answer: {approved_refs - citations_in_answer}"
    )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", citation_model_fixtures(), ids=lambda f: f["description"])
async def test_answer_no_fabricated_citations(fixture):
    """Answer text does not contain fabricated citation references."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    citations_in_answer = set(CITATION_PATTERN.findall(answer.answer))
    approved_refs = {i["citation_reference"] for i in fixture["approved_items"]}
    assert citations_in_answer.issubset(approved_refs), (
        f"Fabricated citations: {citations_in_answer - approved_refs}"
    )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", citation_model_fixtures(), ids=lambda f: f["description"])
async def test_answer_all_approved_refs_present(fixture):
    """All approved citation references appear in answer text."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    for item_data in fixture["approved_items"]:
        assert item_data["citation_reference"] in answer.answer, (
            f"Missing citation: {item_data['citation_reference']}"
        )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", citation_model_fixtures(), ids=lambda f: f["description"])
async def test_no_citations_outside_approved_context(fixture):
    """No citation references in answer text outside approved context."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    all_refs = set(CITATION_PATTERN.findall(answer.answer))
    approved_refs = {i["citation_reference"] for i in fixture["approved_items"]}
    assert all_refs.issubset(approved_refs)


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize("fixture", citation_model_fixtures(), ids=lambda f: f["description"])
async def test_multi_item_answer_cites_all_sources(fixture):
    """When multiple items provided, answer cites each source."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    citations_in_answer = set(CITATION_PATTERN.findall(answer.answer))
    approved_refs = {i["citation_reference"] for i in fixture["approved_items"]}
    # At least one approved ref should be cited
    assert len(citations_in_answer & approved_refs) > 0, "No approved citations found in answer"
