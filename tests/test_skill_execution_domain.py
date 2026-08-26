"""Skill execution domain model tests (validation, fail-closed invariants)."""

from datetime import datetime

import pytest

from arc.domain.models import (
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillExecutionStepOutcome,
    ToolExecutionStatus,
)


def _step(**overrides) -> SkillExecutionStepOutcome:
    """Build a valid successful step outcome with overridable fields."""
    values = {
        "sequence": 0,
        "tool_name": "check_service_health",
        "status": ToolExecutionStatus.SUCCESS,
        "tool_version": "1",
        "output": {"tenant_id": "t1"},
    }
    values.update(overrides)
    return SkillExecutionStepOutcome(**values)


def _result(status=SkillExecutionStatus.SUCCEEDED, **overrides) -> SkillExecutionResult:
    """Build a valid SkillExecutionResult with overridable fields."""
    values = {
        "id": "exec-1",
        "tenant_id": "tenant-1",
        "principal_id": "user-1",
        "skill_id": "skill-1",
        "skill_name": "Service Recovery",
        "skill_version": "1",
        "status": status,
        "steps": [_step()],
        "error_kind": None,
        "created_at": datetime.now(),
    }
    values.update(overrides)
    return SkillExecutionResult(**values)


class TestSkillExecutionStepOutcome:
    """Step outcome construction fails closed on invalid metadata."""

    def test_valid_success_step(self):
        step = _step()
        assert step.status is ToolExecutionStatus.SUCCESS
        assert step.output == {"tenant_id": "t1"}

    def test_valid_failed_step(self):
        step = _step(
            status=ToolExecutionStatus.FAILED,
            tool_version=None,
            output=None,
            error_kind="unknown_tool",
        )
        assert step.error_kind == "unknown_tool"
        assert step.output is None

    def test_negative_sequence_rejected(self):
        with pytest.raises(ValueError, match="sequence"):
            _step(sequence=-1)

    def test_non_integer_sequence_rejected(self):
        with pytest.raises(ValueError, match="sequence"):
            _step(sequence="0")

    def test_empty_tool_name_rejected(self):
        with pytest.raises(ValueError, match="tool name"):
            _step(tool_name="")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="Invalid skill execution step status"):
            _step(status="success")

    def test_success_step_with_error_kind_rejected(self):
        with pytest.raises(ValueError, match="cannot have an error kind"):
            _step(error_kind="unexpected")

    def test_success_step_without_output_rejected(self):
        with pytest.raises(ValueError, match="must carry an output"):
            _step(output=None)

    def test_success_step_without_tool_version_rejected(self):
        with pytest.raises(ValueError, match="tool version"):
            _step(tool_version=None)

    def test_failed_step_without_error_kind_rejected(self):
        with pytest.raises(ValueError, match="require an error kind"):
            _step(
                status=ToolExecutionStatus.FAILED,
                tool_version=None,
                output=None,
                error_kind=None,
            )

    def test_failed_step_with_output_rejected(self):
        with pytest.raises(ValueError, match="cannot carry an output"):
            _step(status=ToolExecutionStatus.FAILED, error_kind="unknown_tool")


class TestSkillExecutionResult:
    """Execution result construction enforces terminal-state invariants."""

    def test_valid_succeeded_result(self):
        result = _result()
        assert result.status is SkillExecutionStatus.SUCCEEDED

    def test_valid_failed_result_with_steps(self):
        result = _result(
            status=SkillExecutionStatus.FAILED,
            steps=[
                _step(),
                _step(
                    sequence=1,
                    tool_name="restart",
                    status=ToolExecutionStatus.FAILED,
                    tool_version=None,
                    output=None,
                    error_kind="unknown_tool",
                ),
            ],
            error_kind="unknown_tool",
        )
        assert result.error_kind == "unknown_tool"
        assert len(result.steps) == 2

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="ID cannot be empty"):
            _result(id="")

    def test_empty_tenant_rejected(self):
        with pytest.raises(ValueError, match="tenant ID"):
            _result(tenant_id="")

    def test_empty_principal_rejected(self):
        with pytest.raises(ValueError, match="principal ID"):
            _result(principal_id="")

    def test_empty_skill_fields_rejected(self):
        with pytest.raises(ValueError, match="skill ID"):
            _result(skill_id="")
        with pytest.raises(ValueError, match="skill name"):
            _result(skill_name="")
        with pytest.raises(ValueError, match="skill version"):
            _result(skill_version="")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="Invalid skill execution status"):
            _result(status="succeeded")

    def test_invalid_steps_container_rejected(self):
        with pytest.raises(ValueError, match="steps must be"):
            _result(steps=["not-a-step"])

    def test_succeeded_with_error_kind_rejected(self):
        with pytest.raises(ValueError, match="cannot have an error kind"):
            _result(error_kind="unexpected")

    def test_succeeded_with_failed_step_rejected(self):
        with pytest.raises(ValueError, match="cannot contain failed steps"):
            _result(
                steps=[
                    _step(),
                    _step(
                        sequence=1,
                        tool_name="other",
                        status=ToolExecutionStatus.FAILED,
                        tool_version=None,
                        output=None,
                        error_kind="unknown_tool",
                    ),
                ]
            )

    @pytest.mark.parametrize(
        "status",
        [SkillExecutionStatus.PRECONDITION_FAILED, SkillExecutionStatus.APPROVAL_REQUIRED],
    )
    def test_blocked_statuses_cannot_record_steps(self, status):
        with pytest.raises(ValueError, match="cannot record steps"):
            _result(status=status)

    @pytest.mark.parametrize(
        "status",
        [SkillExecutionStatus.PRECONDITION_FAILED, SkillExecutionStatus.APPROVAL_REQUIRED],
    )
    def test_blocked_statuses_require_error_kind(self, status):
        with pytest.raises(ValueError, match="require an error kind"):
            _result(status=status, steps=[], error_kind=None)

    def test_denied_requires_error_kind(self):
        with pytest.raises(ValueError, match="requires an error kind"):
            _result(status=SkillExecutionStatus.DENIED, error_kind=None)

    def test_failed_requires_error_kind(self):
        with pytest.raises(ValueError, match="requires an error kind"):
            _result(status=SkillExecutionStatus.FAILED, error_kind=None)
