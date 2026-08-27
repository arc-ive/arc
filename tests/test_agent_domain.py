"""Agent domain model tests (strict decision parsing, fail-closed invariants)."""

import pytest

from arc.domain.models import (
    AgentDecision,
    AgentExecutionResult,
    AgentRunStatus,
    AgentStepOutcome,
    SkillExecutionStatus,
)


def _step(**overrides) -> AgentStepOutcome:
    values = {
        "sequence": 0,
        "skill_id": "skill-1",
        "skill_name": "Recovery",
        "status": SkillExecutionStatus.SUCCEEDED,
        "error_kind": None,
    }
    values.update(overrides)
    return AgentStepOutcome(**values)


def _result(status=AgentRunStatus.SUCCEEDED, **overrides) -> AgentExecutionResult:
    values = {
        "id": "run-1",
        "tenant_id": "tenant-1",
        "principal_id": "user-1",
        "goal": "recover the payment service",
        "status": status,
        "steps": [_step()],
        "error_kind": None,
    }
    values.update(overrides)
    return AgentExecutionResult(**values)


class TestAgentDecisionParsing:
    def test_valid_decision_parses(self):
        decision = AgentDecision.parse(
            {
                "skill_id": "skill-1",
                "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                "satisfied_preconditions": ["health_degraded"],
            }
        )
        assert decision is not None
        assert decision.skill_id == "skill-1"
        assert decision.tool_calls == [{"tool_name": "check_service_health", "input": {}}]
        assert decision.satisfied_preconditions == ["health_degraded"]

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "skill-1",
            42,
            {},
            {"skill_id": "s", "tool_calls": []},
            {"skill_id": "s", "satisfied_preconditions": []},
            {"tool_calls": [{"tool_name": "t"}], "satisfied_preconditions": []},
            {
                "skill_id": "s",
                "tool_calls": [],
                "satisfied_preconditions": [],
                "reason": "injected",
            },
            {"skill_id": "", "tool_calls": [{"tool_name": "t"}], "satisfied_preconditions": []},
            {
                "skill_id": "   ",
                "tool_calls": [{"tool_name": "t"}],
                "satisfied_preconditions": [],
            },
            {"skill_id": 7, "tool_calls": [{"tool_name": "t"}], "satisfied_preconditions": []},
            {
                "skill_id": "x" * 256,
                "tool_calls": [{"tool_name": "t"}],
                "satisfied_preconditions": [],
            },
            {"skill_id": "s", "tool_calls": {}, "satisfied_preconditions": []},
            {"skill_id": "s", "tool_calls": [], "satisfied_preconditions": []},
            {"skill_id": "s", "tool_calls": ["call"], "satisfied_preconditions": []},
            {"skill_id": "s", "tool_calls": [None], "satisfied_preconditions": []},
            {"skill_id": "s", "tool_calls": [{"tool_name": "t"}], "satisfied_preconditions": "ok"},
            {
                "skill_id": "s",
                "tool_calls": [{"tool_name": "t"}],
                "satisfied_preconditions": [42],
            },
        ],
    )
    def test_malformed_decisions_fail_closed_to_none(self, raw):
        assert AgentDecision.parse(raw) is None


class TestAgentStepOutcome:
    def test_valid_succeeded_step(self):
        step = _step()
        assert step.status is SkillExecutionStatus.SUCCEEDED
        assert step.error_kind is None

    def test_valid_failed_step(self):
        step = _step(status=SkillExecutionStatus.FAILED, error_kind="unknown_tool")
        assert step.error_kind == "unknown_tool"

    def test_negative_sequence_rejected(self):
        with pytest.raises(ValueError, match="sequence"):
            _step(sequence=-1)

    def test_non_integer_sequence_rejected(self):
        with pytest.raises(ValueError, match="sequence"):
            _step(sequence="0")

    def test_empty_skill_id_rejected(self):
        with pytest.raises(ValueError, match="skill ID"):
            _step(skill_id="")

    def test_empty_skill_name_rejected(self):
        with pytest.raises(ValueError, match="skill name"):
            _step(skill_name="")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="Invalid agent step status"):
            _step(status="succeeded")

    def test_succeeded_step_with_error_kind_rejected(self):
        with pytest.raises(ValueError, match="cannot have an error kind"):
            _step(error_kind="unexpected")

    def test_non_succeeded_step_without_error_kind_rejected(self):
        with pytest.raises(ValueError, match="require an error kind"):
            _step(status=SkillExecutionStatus.FAILED, error_kind=None)


class TestAgentExecutionResult:
    def test_valid_succeeded_result(self):
        result = _result()
        assert result.status is AgentRunStatus.SUCCEEDED

    def test_failed_result_preserves_prefix_steps(self):
        result = _result(
            status=AgentRunStatus.FAILED,
            steps=[
                _step(),
                _step(
                    sequence=1,
                    skill_id="s2",
                    status=SkillExecutionStatus.FAILED,
                    error_kind="inactive_skill",
                ),
            ],
            error_kind="inactive_skill",
        )
        assert len(result.steps) == 2
        assert result.error_kind == "inactive_skill"

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="ID cannot be empty"):
            _result(id="")

    def test_empty_tenant_rejected(self):
        with pytest.raises(ValueError, match="tenant ID"):
            _result(tenant_id="")

    def test_empty_principal_rejected(self):
        with pytest.raises(ValueError, match="principal ID"):
            _result(principal_id="")

    def test_empty_goal_rejected(self):
        with pytest.raises(ValueError, match="goal cannot be empty"):
            _result(goal="   ")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="Invalid agent run status"):
            _result(status="succeeded")

    def test_invalid_steps_container_rejected(self):
        with pytest.raises(ValueError, match="steps must be"):
            _result(steps=["not-a-step"])

    def test_succeeded_with_error_kind_rejected(self):
        with pytest.raises(ValueError, match="cannot have an error kind"):
            _result(error_kind="unexpected")

    def test_succeeded_with_zero_steps_rejected(self):
        with pytest.raises(ValueError, match="at least one step"):
            _result(steps=[])

    def test_succeeded_with_unsuccessful_step_rejected(self):
        with pytest.raises(ValueError, match="cannot contain unsuccessful steps"):
            _result(
                steps=[
                    _step(),
                    _step(
                        sequence=1,
                        skill_id="s2",
                        status=SkillExecutionStatus.FAILED,
                        error_kind="unknown_tool",
                    ),
                ]
            )

    @pytest.mark.parametrize(
        "status",
        [AgentRunStatus.FAILED, AgentRunStatus.APPROVAL_REQUIRED, AgentRunStatus.MAX_STEPS_REACHED],
    )
    def test_non_succeeded_statuses_require_error_kind(self, status):
        with pytest.raises(ValueError, match="requires an error kind"):
            _result(status=status, error_kind=None)
