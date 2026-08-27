"""Domain validation tests for Human Intervention approval requests.

Pins the fail-closed construction contract (exact digest format, TTL
ordering, lifecycle metadata consistency) and the lazy-expiry derivation
that lets reads report EXPIRED without mutating stored state.
"""

from datetime import datetime, timedelta, timezone

import pytest

from arc.domain.models import ApprovalRequest, ApprovalStatus

_T0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _request(**overrides):
    defaults = dict(
        id="appr-1",
        tenant_id="tenant-1",
        requested_by_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary='{"target": "svc"}',
        arguments_digest=_DIGEST,
        status=ApprovalStatus.PENDING,
        created_at=_T0,
        expires_at=_T0 + timedelta(hours=24),
    )
    defaults.update(overrides)
    return ApprovalRequest(**defaults)


class TestConstructionValidation:
    def test_valid_pending_request(self):
        request = _request()
        assert request.status == ApprovalStatus.PENDING
        assert request.decided_at is None and request.consumed_at is None

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError):
            _request(id="")

    def test_oversized_id_rejected(self):
        with pytest.raises(ValueError):
            _request(id="x" * 256)

    def test_empty_tenant_rejected(self):
        with pytest.raises(ValueError):
            _request(tenant_id="")

    def test_empty_requester_rejected(self):
        with pytest.raises(ValueError):
            _request(requested_by_user_id="")

    def test_empty_tool_name_rejected(self):
        with pytest.raises(ValueError):
            _request(tool_name="")

    @pytest.mark.parametrize("digest", ["", "z" * 64, "A" * 64, ("a" * 63), ("ab" * 33)[:65]])
    def test_invalid_digest_shapes_rejected(self, digest):
        with pytest.raises(ValueError):
            _request(arguments_digest=digest)

    def test_expiry_must_be_after_creation(self):
        with pytest.raises(ValueError):
            _request(expires_at=_T0)

    def test_approved_requires_decision_metadata(self):
        with pytest.raises(ValueError):
            _request(status=ApprovalStatus.APPROVED)

    def test_approved_with_decision_metadata_valid(self):
        request = _request(
            status=ApprovalStatus.APPROVED,
            decided_at=_T0 + timedelta(hours=1),
            decided_by_user_id="approver-1",
        )
        assert request.status == ApprovalStatus.APPROVED

    def test_consumed_requires_consumed_at(self):
        with pytest.raises(ValueError):
            _request(
                status=ApprovalStatus.CONSUMED,
                decided_at=_T0 + timedelta(hours=1),
                decided_by_user_id="approver-1",
            )

    def test_pending_must_not_carry_decision_metadata(self):
        with pytest.raises(ValueError):
            _request(decided_at=_T0 + timedelta(hours=1), decided_by_user_id="x")


class TestLazyExpiry:
    def test_pending_before_ttl_reads_pending(self):
        assert _request().effective_status(_T0 + timedelta(hours=23)) == ApprovalStatus.PENDING

    def test_pending_at_ttl_boundary_reads_expired(self):
        assert _request().effective_status(_T0 + timedelta(hours=24)) == ApprovalStatus.EXPIRED

    def test_terminal_states_never_derive_expired(self):
        for status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CONSUMED,
        ):
            request = _request(
                status=status,
                decided_at=_T0 + timedelta(hours=1),
                decided_by_user_id="approver",
                consumed_at=_T0 + timedelta(hours=2) if status == ApprovalStatus.CONSUMED else None,
            )
            assert request.effective_status(_T0 + timedelta(days=30)) == status
