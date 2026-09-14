"""Tool evaluation: invalid argument rejection (Issue #139, V2-ADR-023).

5 deterministic cases testing that malformed proposals are rejected.
"""

import pytest

from arc.domain.models import ToolProposal

from .golden_datasets import tool_rejection_fixtures


@pytest.mark.parametrize("fixture", tool_rejection_fixtures(), ids=lambda f: f["description"])
def test_invalid_proposal_rejected(fixture):
    """Invalid proposals are rejected by ToolProposal.parse."""
    raw = fixture["proposal_raw"]
    result = ToolProposal.parse(raw)
    assert result is None


@pytest.mark.parametrize("fixture", tool_rejection_fixtures(), ids=lambda f: f["description"])
def test_missing_tool_name_rejected(fixture):
    """Missing tool_name is rejected."""
    raw = fixture["proposal_raw"]
    if raw and "tool_name" in raw and raw["tool_name"]:
        pytest.skip("Has tool_name")
    result = ToolProposal.parse(raw)
    assert result is None


@pytest.mark.parametrize("fixture", tool_rejection_fixtures(), ids=lambda f: f["description"])
def test_empty_tool_name_rejected(fixture):
    """Empty tool_name is rejected."""
    raw = fixture["proposal_raw"]
    if not raw or raw.get("tool_name", "") != "":
        pytest.skip("Not empty tool_name case")
    result = ToolProposal.parse(raw)
    assert result is None


@pytest.mark.parametrize("fixture", tool_rejection_fixtures(), ids=lambda f: f["description"])
def test_non_dict_arguments_rejected(fixture):
    """Non-dict arguments is rejected."""
    raw = fixture["proposal_raw"]
    if raw and isinstance(raw.get("arguments"), dict):
        pytest.skip("Has dict arguments")
    result = ToolProposal.parse(raw)
    assert result is None


@pytest.mark.parametrize("fixture", tool_rejection_fixtures(), ids=lambda f: f["description"])
def test_extra_fields_rejected(fixture):
    """Extra fields are rejected."""
    raw = fixture["proposal_raw"]
    if not raw or len(raw.keys()) == 2:
        pytest.skip("No extra fields")
    result = ToolProposal.parse(raw)
    assert result is None
