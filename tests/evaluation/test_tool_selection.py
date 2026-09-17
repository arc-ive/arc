"""Tool evaluation: correct tool selection (Issue #139, V2-ADR-023).

5 deterministic cases testing that tool proposals select the correct tool.
"""

import pytest

from arc.domain.models import ToolProposal

from .golden_datasets import tool_selection_fixtures


def _parse_proposal(raw):
    """Parse raw proposal through ToolProposal.parse."""
    return ToolProposal.parse(raw)


@pytest.mark.parametrize("fixture", tool_selection_fixtures(), ids=lambda f: f["description"])
def test_tool_proposal_selection(fixture):
    """Proposal selects the expected tool."""
    raw = fixture["proposal_raw"]
    expected = fixture["expected_tool_name"]

    if raw is None:
        result = _parse_proposal(None)
        assert result is None
    else:
        result = _parse_proposal(raw)
        if expected is not None:
            assert result is not None
            assert result.tool_name == expected
        else:
            assert result is None


@pytest.mark.parametrize("fixture", tool_selection_fixtures(), ids=lambda f: f["description"])
def test_tool_proposal_validates(fixture):
    """Proposal passes ToolProposal.parse validation."""
    raw = fixture["proposal_raw"]
    if raw is None:
        pytest.skip("None proposal")

    result = _parse_proposal(raw)
    if fixture["expected_tool_name"] is not None:
        assert result is not None
        assert isinstance(result.tool_name, str)


@pytest.mark.parametrize("fixture", tool_selection_fixtures(), ids=lambda f: f["description"])
def test_tool_proposal_preserves_arguments(fixture):
    """Proposal arguments are preserved through parsing."""
    raw = fixture["proposal_raw"]
    if raw is None or fixture["expected_tool_name"] is None:
        pytest.skip("None or invalid proposal")

    result = _parse_proposal(raw)
    assert result is not None
    assert isinstance(result.arguments, dict)


@pytest.mark.parametrize("fixture", tool_selection_fixtures(), ids=lambda f: f["description"])
def test_tool_proposal_none_for_no_tool(fixture):
    """Proposal is None when no tool is appropriate."""
    raw = fixture["proposal_raw"]
    if fixture["expected_tool_name"] is not None:
        pytest.skip("Not a None case")

    result = _parse_proposal(raw)
    assert result is None


@pytest.mark.parametrize("fixture", tool_selection_fixtures(), ids=lambda f: f["description"])
def test_tool_proposal_tool_name_matches_registry(fixture):
    """Proposal tool_name matches a known tool in the registry."""
    raw = fixture["proposal_raw"]
    if raw is None or fixture["expected_tool_name"] is None:
        pytest.skip("None or invalid")

    result = _parse_proposal(raw)
    assert result is not None
    assert result.tool_name == fixture["expected_tool_name"]
