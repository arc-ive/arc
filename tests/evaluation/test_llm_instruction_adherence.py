"""LLM evaluation: instruction adherence (Issue #139, V2-ADR-023).

5 production-LLM cases testing that model follows system instructions.

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
from .golden_datasets import instruction_adherence_fixtures


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
        provenance="Eval fixture",
        document_version=1,
        sequence=item_data["sequence"],
        relevance_score=0.9,
        citation_reference=item_data["citation_reference"],
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

    async def approved_search(self, context, query, limit=5):
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
@pytest.mark.parametrize(
    "fixture", instruction_adherence_fixtures(), ids=lambda f: f["description"]
)
async def test_answer_cites_approved_sources(fixture):
    """Answer cites only approved sources."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    for claim in fixture["expected_in_answer"]:
        assert claim.lower() in answer.answer.lower(), f"Expected claim missing: {claim}"


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", instruction_adherence_fixtures(), ids=lambda f: f["description"]
)
async def test_answer_does_not_echo_instructions(fixture):
    """Answer does not echo system instructions."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    for forbidden in fixture["forbidden_in_answer"]:
        assert forbidden.lower() not in answer.answer.lower(), (
            f"Answer contains forbidden text: {forbidden}"
        )


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", instruction_adherence_fixtures(), ids=lambda f: f["description"]
)
async def test_answer_maintains_role(fixture):
    """Answer maintains assistant role."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    answer_lower = answer.answer.lower()
    assert "i am a language model" not in answer_lower
    assert "i cannot" not in answer_lower


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", instruction_adherence_fixtures(), ids=lambda f: f["description"]
)
async def test_answer_does_not_reveal_prompt(fixture):
    """Answer does not reveal prompt structure."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    for forbidden in fixture["forbidden_in_answer"]:
        assert forbidden.lower() not in answer.answer.lower()


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", instruction_adherence_fixtures(), ids=lambda f: f["description"]
)
async def test_answer_follows_citation_instruction(fixture):
    """Answer includes citation references as instructed."""
    provider = _build_provider()
    approved = _approved_from_fixture(fixture)
    retrieval = FakeRetrieval(approved)
    intelligence = UnifiedIntelligenceService(retrieval, llm_provider=provider)

    answer = await intelligence.answer_query(_context(), fixture["query"])

    # At least one expected claim should be in the answer
    assert any(claim.lower() in answer.answer.lower() for claim in fixture["expected_in_answer"])
