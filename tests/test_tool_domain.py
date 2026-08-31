"""AI Tools domain model tests.

Covers the tenant-scoped ``ToolExecutionRecord`` audit model and the
``ToolRiskLevel`` / ``ToolExecutionStatus`` / ``ToolAuthorizationOutcome``
enums (PRD 15, TRD 14.2). The audit contract is explicit: who
(``user_id``), which tenant, which tool and version, the authorization
decision, the risk level, the status, and the execution identifier.
"""

import uuid

import pytest

from arc.domain.models import (
    ToolAuthorizationOutcome,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolRiskLevel,
)


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"tool-domain-{prefix}-{uuid.uuid4().hex[:10]}"


def _record(**overrides) -> ToolExecutionRecord:
    """Return a valid ToolExecutionRecord with overridable fields."""
    values = {
        "id": _unique("record"),
        "tenant_id": _unique("tenant"),
        "user_id": _unique("user"),
        "tool_name": "check_service_health",
        "tool_version": "1",
        "status": ToolExecutionStatus.SUCCESS,
        "risk_level": ToolRiskLevel.LOW,
        "input_summary": "{}",
    }
    values.update(overrides)
    return ToolExecutionRecord(**values)


def test_risk_level_values():
    """The documented risk taxonomy has exactly three levels (PRD 15)."""
    assert {level.value for level in ToolRiskLevel} == {"low", "medium", "high"}


def test_execution_status_values():
    """A record has exactly one terminal status (TRD 14.2)."""
    assert {status.value for status in ToolExecutionStatus} == {"success", "failed"}


def test_authorization_outcome_values():
    """The audit contract records the fail-closed authorization decision."""
    assert {outcome.value for outcome in ToolAuthorizationOutcome} == {"granted", "denied"}


def test_valid_success_record():
    record = _record()
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.risk_level == ToolRiskLevel.LOW
    assert record.authorization_outcome == ToolAuthorizationOutcome.GRANTED
    assert record.output_summary is None
    assert record.error_kind is None


def test_denied_record():
    record = _record(
        status=ToolExecutionStatus.FAILED,
        authorization_outcome=ToolAuthorizationOutcome.DENIED,
        error_kind="authorization_denied",
    )
    assert record.status == ToolExecutionStatus.FAILED
    assert record.authorization_outcome == ToolAuthorizationOutcome.DENIED
    assert record.error_kind == "authorization_denied"


def test_valid_failed_record_with_error_kind():
    record = _record(status=ToolExecutionStatus.FAILED, error_kind="execution_error")
    assert record.status == ToolExecutionStatus.FAILED
    assert record.error_kind == "execution_error"


def test_requires_id():
    with pytest.raises(ValueError):
        _record(id="")


def test_requires_tenant_id():
    with pytest.raises(ValueError):
        _record(tenant_id="")


def test_requires_user_id():
    with pytest.raises(ValueError):
        _record(user_id="")


def test_requires_tool_name():
    with pytest.raises(ValueError):
        _record(tool_name="")


def test_requires_tool_version():
    with pytest.raises(ValueError):
        _record(tool_version="")


def test_requires_input_summary():
    with pytest.raises(ValueError):
        _record(input_summary="")


def test_rejects_invalid_status():
    with pytest.raises(ValueError):
        _record(status="pending")


def test_rejects_invalid_authorization_outcome():
    with pytest.raises(ValueError):
        _record(authorization_outcome="maybe")


def test_rejects_invalid_risk_level():
    with pytest.raises(ValueError):
        _record(risk_level="extreme")


def test_output_summary_and_error_kind_are_optional():
    record = _record(output_summary='{"tenant_id": "t"}')
    assert record.output_summary == '{"tenant_id": "t"}'
    assert record.error_kind is None
