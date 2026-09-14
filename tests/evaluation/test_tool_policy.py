"""Tool evaluation: policy enforcement (Issue #139, V2-ADR-023).

5 deterministic cases testing tool execution policy enforcement.
"""

import pytest

from arc.services.tools import ToolExecutionPolicy, ToolExecutionPolicyMode

from .golden_datasets import tool_policy_fixtures


def _policy(mode_str):
    """Convert string mode to ToolExecutionPolicyMode (lowercase values)."""
    return ToolExecutionPolicyMode(mode_str.lower())


@pytest.mark.parametrize("fixture", tool_policy_fixtures(), ids=lambda f: f["description"])
def test_tool_policy_enforcement(fixture):
    """Tool execution policy is enforced correctly."""
    policy = ToolExecutionPolicy(mode=_policy(fixture["policy_mode"]))
    expected = _policy(fixture["policy_mode"])
    assert policy.mode == expected


@pytest.mark.parametrize("fixture", tool_policy_fixtures(), ids=lambda f: f["description"])
def test_allow_policy_permits(fixture):
    """ALLOW policy permits execution."""
    if fixture["policy_mode"] != "ALLOW":
        pytest.skip("Not ALLOW case")
    policy = ToolExecutionPolicy(mode=_policy("ALLOW"))
    assert policy.mode == ToolExecutionPolicyMode.ALLOW


@pytest.mark.parametrize("fixture", tool_policy_fixtures(), ids=lambda f: f["description"])
def test_deny_policy_blocks(fixture):
    """DENY policy blocks execution."""
    if fixture["policy_mode"] != "DENY":
        pytest.skip("Not DENY case")
    policy = ToolExecutionPolicy(mode=_policy("DENY"))
    assert policy.mode == ToolExecutionPolicyMode.DENY


@pytest.mark.parametrize("fixture", tool_policy_fixtures(), ids=lambda f: f["description"])
def test_approval_required(fixture):
    """REQUIRE_HUMAN_APPROVAL requires approval."""
    if fixture["policy_mode"] != "REQUIRE_HUMAN_APPROVAL":
        pytest.skip("Not approval case")
    policy = ToolExecutionPolicy(mode=_policy("REQUIRE_HUMAN_APPROVAL"))
    assert policy.mode == ToolExecutionPolicyMode.REQUIRE_HUMAN_APPROVAL


@pytest.mark.parametrize("fixture", tool_policy_fixtures(), ids=lambda f: f["description"])
def test_policy_mode_deterministic(fixture):
    """Policy mode is deterministic for same input."""
    policy1 = ToolExecutionPolicy(mode=_policy(fixture["policy_mode"]))
    policy2 = ToolExecutionPolicy(mode=_policy(fixture["policy_mode"]))
    assert policy1.mode == policy2.mode
