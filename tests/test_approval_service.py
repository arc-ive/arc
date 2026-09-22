"""Unit tests for the HumanApprovalService lifecycle rules (V1 gate).

Uses fake repositories and an injected clock to prove: idempotent
creation, best-effort creation semantics, lazy-expiry derivation on
reads, terminal decisions with audit metadata, precise consumption error
classification, and the strict separation that the approval service
never touches tool execution.
"""

from datetime import datetime, timedelta, timezone

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import ApprovalRequest, ApprovalStatus, TenantContext, UserRole
from arc.services.approvals import (
    ApprovalBindingError,
    ApprovalConsumedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalSelfDecisionError,
    ApprovalStateError,
    HumanApprovalService,
)

_T0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_DIGEST = "d" * 64


class FakeApprovalRepository:
    def __init__(self):
        self.rows = {}
        self.fail_writes = False

    async def create(self, request):
        if self.fail_writes:
            raise RuntimeError("database unavailable")
        self.rows[request.id] = request
        return request

    async def get_by_id(self, approval_id, tenant_id):
        row = self.rows.get(approval_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFoundError(f"Approval {approval_id} not found")
        return row

    async def list_for_tenant(self, tenant_id, limit=100):
        return [r for r in self.rows.values() if r.tenant_id == tenant_id]

    async def find_open(self, tenant_id, tool_name, tool_version, arguments_digest):
        for row in self.rows.values():
            if (
                row.tenant_id == tenant_id
                and row.tool_name == tool_name
                and row.tool_version == tool_version
                and row.arguments_digest == arguments_digest
                and row.status == ApprovalStatus.PENDING
            ):
                return row
        return None

    async def expire_if_due(self, approval_id, tenant_id):
        row = await self.get_by_id(approval_id, tenant_id)
        if row.status == ApprovalStatus.PENDING:
            self.rows[approval_id] = ApprovalRequest(
                **{**row.__dict__, "status": ApprovalStatus.EXPIRED}
            )
            return True
        return False

    async def decide(self, approval_id, tenant_id, decision, decider_user_id):
        row = await self.get_by_id(approval_id, tenant_id)
        if row.status != ApprovalStatus.PENDING:
            return False
        self.rows[approval_id] = ApprovalRequest(
            **{
                **row.__dict__,
                "status": decision,
                "decided_at": _T0 + timedelta(minutes=1),
                "decided_by_user_id": decider_user_id,
            }
        )
        return True

    async def consume(self, approval_id, tenant_id, tool_name, tool_version, arguments_digest):
        row = await self.get_by_id(approval_id, tenant_id)
        if (
            row.status == ApprovalStatus.APPROVED
            and row.tool_name == tool_name
            and row.tool_version == tool_version
            and row.arguments_digest == arguments_digest
        ):
            self.rows[approval_id] = ApprovalRequest(
                **{
                    **row.__dict__,
                    "status": ApprovalStatus.CONSUMED,
                    "consumed_at": _T0 + timedelta(hours=2),
                }
            )
            return True
        return False


def _clock_at(offset_hours: float = 0.0):
    state = {"hours": offset_hours}

    def _now():
        return _T0 + timedelta(hours=state["hours"])

    def _advance(hours: float):
        state["hours"] += hours

    return _now, _advance


def _service(repo=None, clock_offset=0.0):
    repo = repo or FakeApprovalRepository()
    now_fn, advance = _clock_at(clock_offset)
    service = HumanApprovalService(repository=repo, clock=now_fn)
    service._test_advance = advance
    return service, repo


def _context(tenant_id="tenant-1"):
    return TenantContext(
        tenant_id=tenant_id, tenant_name="T", user_id="user-1", role=UserRole.MEMBER
    )


@pytest.mark.asyncio
async def test_record_creates_pending_request_with_24h_ttl():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-9",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary='{"target": "svc"}',
        arguments_digest=_DIGEST,
    )
    assert approval_id is not None
    stored = repo.rows[approval_id]
    assert stored.status == ApprovalStatus.PENDING
    assert stored.expires_at - stored.created_at == timedelta(hours=24)
    assert stored.requester_user_id == "user-9"


@pytest.mark.asyncio
async def test_record_is_idempotent_per_exact_binding():
    service, repo = _service()
    kwargs = dict(
        tenant_id="tenant-1",
        requester_user_id="user-9",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary='{"target": "svc"}',
        arguments_digest=_DIGEST,
    )
    first = await service.record_required_approval(**kwargs)
    second = await service.record_required_approval(**kwargs)
    assert first == second
    assert len([r for r in repo.rows.values() if r.status == ApprovalStatus.PENDING]) == 1


@pytest.mark.asyncio
async def test_creation_failure_is_best_effort_and_logged():
    service, repo = _service()
    repo.fail_writes = True
    result = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-9",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    assert result is None


@pytest.mark.asyncio
async def test_reads_derive_expired_without_mutating():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    service._test_advance(25.0)  # past the 24h TTL
    context = _context()
    fetched = await service.get_request(context, approval_id)
    assert fetched.status == ApprovalStatus.EXPIRED
    # Physical row untouched by the read.
    assert repo.rows[approval_id].status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_decision_on_expired_request_transitions_to_terminal_expired():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    service._test_advance(25.0)  # past the 24h TTL
    with pytest.raises(ApprovalExpiredError):
        await service.decide_request(_context(), "approver-1", approval_id, ApprovalStatus.APPROVED)
    assert repo.rows[approval_id].status == ApprovalStatus.EXPIRED
    # Expiry is a system transition: no human decider is recorded.
    assert repo.rows[approval_id].decided_by_user_id is None


@pytest.mark.asyncio
async def test_approve_then_consume_happy_path():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    decided = await service.decide_request(
        _context(), "approver-7", approval_id, ApprovalStatus.APPROVED
    )
    assert decided.status == ApprovalStatus.APPROVED
    consumed = await service.consume_approval(
        _context(), approval_id, "restart_service", "1", _DIGEST
    )
    assert consumed.status == ApprovalStatus.CONSUMED

    with pytest.raises(ApprovalConsumedError):
        await service.consume_approval(_context(), approval_id, "restart_service", "1", _DIGEST)


@pytest.mark.asyncio
async def test_consume_binding_mismatch_classified():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    await service.decide_request(_context(), "approver-1", approval_id, ApprovalStatus.APPROVED)
    with pytest.raises(ApprovalBindingError):
        await service.consume_approval(_context(), approval_id, "other_tool", "1", _DIGEST)


@pytest.mark.asyncio
async def test_consume_before_decision_is_state_error():
    service, _ = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    with pytest.raises(ApprovalStateError):
        await service.consume_approval(_context(), approval_id, "restart_service", "1", _DIGEST)


@pytest.mark.asyncio
async def test_unknown_id_raises_not_found():
    service, _ = _service()
    with pytest.raises(ApprovalNotFoundError):
        await service.get_request(_context(), "missing")
    with pytest.raises(ApprovalNotFoundError):
        await service.consume_approval(_context(), "missing", "restart_service", "1", _DIGEST)
    with pytest.raises(ApprovalNotFoundError):
        await service.decide_request(_context(), "user-1", "missing", ApprovalStatus.APPROVED)


@pytest.mark.asyncio
async def test_listing_filters_by_effective_status():
    service, repo = _service()
    expired_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    service._test_advance(25.0)  # first request ages past its TTL
    fresh_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="send_notification",
        tool_version="1",
        risk_level="medium",
        input_summary="{}",
        arguments_digest="e" * 64,
    )
    listing = await service.list_requests(_context())
    by_status = {r.id: r.status for r in listing}
    assert by_status[expired_id] == ApprovalStatus.EXPIRED
    assert by_status[fresh_id] == ApprovalStatus.PENDING

    pending_only = await service.list_requests(_context(), ApprovalStatus.PENDING)
    assert [r.id for r in pending_only] == [fresh_id]


@pytest.mark.asyncio
async def test_service_never_touches_tool_execution():
    """The approval service surface exposes no execution capability."""
    public_methods = {
        name
        for name in dir(HumanApprovalService)
        if not name.startswith("_") and callable(getattr(HumanApprovalService, name))
    }
    forbidden = {"execute_tool", "execute", "run_handler", "authorize"}
    assert public_methods.isdisjoint(forbidden)


# -------------------------------------------------------------------
# Self-approval prevention
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requester_cannot_approve_own_request():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    with pytest.raises(ApprovalSelfDecisionError):
        await service.decide_request(
            _context("tenant-1"), "user-1", approval_id, ApprovalStatus.APPROVED
        )
    # Approval must remain unchanged after rejected self-decision.
    row = repo.rows[approval_id]
    assert row.status == ApprovalStatus.PENDING
    assert row.decided_by_user_id is None
    assert row.decided_at is None


@pytest.mark.asyncio
async def test_requester_cannot_reject_own_request():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    with pytest.raises(ApprovalSelfDecisionError):
        await service.decide_request(
            _context("tenant-1"), "user-1", approval_id, ApprovalStatus.REJECTED
        )
    row = repo.rows[approval_id]
    assert row.status == ApprovalStatus.PENDING
    assert row.decided_by_user_id is None


@pytest.mark.asyncio
async def test_different_user_can_approve():
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    decided = await service.decide_request(
        _context("tenant-1"), "approver-1", approval_id, ApprovalStatus.APPROVED
    )
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by_user_id == "approver-1"


@pytest.mark.asyncio
async def test_requester_can_consume_approved_request_by_another():
    """Per ADR-004: requester ≠ approver is enforced for
    DECISION, but the original requester may CONSUME an approved request
    if all other binding/authorization conditions are met."""
    service, repo = _service()
    approval_id = await service.record_required_approval(
        tenant_id="tenant-1",
        requester_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest=_DIGEST,
    )
    await service.decide_request(
        _context("tenant-1"), "approver-1", approval_id, ApprovalStatus.APPROVED
    )
    consumed = await service.consume_approval(
        _context("tenant-1"), approval_id, "restart_service", "1", _DIGEST
    )
    assert consumed.status == ApprovalStatus.CONSUMED


class CorruptApprovalRepository(FakeApprovalRepository):
    """Fake whose reads surface a corrupt persisted row (Issue #239)."""

    async def get_by_id(self, approval_id, tenant_id):
        from arc.db.connection import CorruptDataError

        raise CorruptDataError(f"Stored approval request '{approval_id}' violates an invariant")

    async def list_for_tenant(self, tenant_id, limit=100):
        from arc.db.connection import CorruptDataError

        raise CorruptDataError("Stored approval request violates an invariant")

    async def list_for_tenant_paginated(self, tenant_id, limit, offset):
        from arc.db.connection import CorruptDataError

        raise CorruptDataError("Stored approval request violates an invariant")


@pytest.mark.asyncio
async def test_corrupt_row_on_read_surfaces_controlled_error():
    from arc.services.approvals import ApprovalCorruptError

    service, _ = _service(CorruptApprovalRepository())
    with pytest.raises(ApprovalCorruptError):
        await service.get_request(_context("tenant-1"), "appr-corrupt")


@pytest.mark.asyncio
async def test_corrupt_row_on_list_surfaces_controlled_error():
    from arc.services.approvals import ApprovalCorruptError

    service, _ = _service(CorruptApprovalRepository())
    with pytest.raises(ApprovalCorruptError):
        await service.list_requests(_context("tenant-1"))
    with pytest.raises(ApprovalCorruptError):
        await service.list_requests_paginated(_context("tenant-1"), 10, 0)


@pytest.mark.asyncio
async def test_corrupt_row_on_decide_surfaces_controlled_error():
    from arc.services.approvals import ApprovalCorruptError

    service, _ = _service(CorruptApprovalRepository())
    with pytest.raises(ApprovalCorruptError):
        await service.decide_request(
            _context("tenant-1"), "approver-1", "appr-corrupt", ApprovalStatus.APPROVED
        )


@pytest.mark.asyncio
async def test_corrupt_error_is_a_controlled_approval_error():
    from arc.services.approvals import ApprovalCorruptError, ApprovalError

    assert issubclass(ApprovalCorruptError, ApprovalError)
