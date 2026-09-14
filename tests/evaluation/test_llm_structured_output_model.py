"""LLM evaluation: structured output, model-level (Issue #139).

5 production-LLM cases testing that the model produces structurally
valid output for tool/skill proposals.

Uses real OpenRouterProvider. Skipped when OPENROUTER_API_KEY is absent.
"""

import os

import pytest

from arc.services.llm import OpenRouterProvider, _validate_skill_proposal, _validate_tool_proposal

from .conftest import EVAL_FREE_MODEL
from .golden_datasets import structured_output_model_fixtures


def _build_provider():
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return OpenRouterProvider(api_key=api_key, model=EVAL_FREE_MODEL)


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", structured_output_model_fixtures(), ids=lambda f: f["description"]
)
def test_model_tool_proposal_structure(fixture):
    """Model returns valid JSON structure for tool proposal."""
    provider = _build_provider()

    result = provider.propose_tool(fixture["query"], fixture["context"])

    if fixture["expected_valid"] is True:
        assert result is not None, "Expected a tool proposal, got None"
        assert isinstance(result, dict)
        assert _validate_tool_proposal(result)
    elif fixture["expected_valid"] is None:
        assert result is None, f"Expected None, got {result}"


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", structured_output_model_fixtures(), ids=lambda f: f["description"]
)
def test_model_tool_proposal_keys(fixture):
    """Model tool proposal contains required keys."""
    provider = _build_provider()

    result = provider.propose_tool(fixture["query"], fixture["context"])

    if result is not None:
        assert "tool_name" in result
        assert "arguments" in result
        assert isinstance(result["tool_name"], str)
        assert isinstance(result["arguments"], dict)


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", structured_output_model_fixtures(), ids=lambda f: f["description"]
)
def test_model_skill_proposal_structure(fixture):
    """Model returns valid JSON structure for skill proposal."""
    provider = _build_provider()

    if "catalog" not in fixture:
        pytest.skip("No catalog in fixture")

    result = provider.propose_skill(fixture["goal"], fixture["catalog"])

    if fixture["expected_valid"] is True:
        assert result is not None
        assert isinstance(result, dict)
        assert _validate_skill_proposal(result)
    elif fixture["expected_valid"] is None:
        assert result is None


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", structured_output_model_fixtures(), ids=lambda f: f["description"]
)
def test_model_output_passes_validation(fixture):
    """Model output passes _validate_tool_proposal check."""
    provider = _build_provider()

    result = provider.propose_tool(fixture["query"], fixture["context"])

    if result is not None:
        assert _validate_tool_proposal(result)


@pytest.mark.evaluation_real_llm
@pytest.mark.parametrize(
    "fixture", structured_output_model_fixtures(), ids=lambda f: f["description"]
)
def test_model_returns_none_when_no_tool(fixture):
    """Model returns NONE when no tool is appropriate."""
    provider = _build_provider()

    result = provider.propose_tool(fixture["query"], fixture["context"])

    if fixture["expected_valid"] is None:
        assert result is None
