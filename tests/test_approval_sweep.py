"""Tests for the background approval expiry sweep (PRD §15).

Covers:
- Repository: atomic bulk expire_stale_approvals
- Service: sweep_expired_approvals delegates to repository
- Background runner: start/stop lifecycle, sweep loop, error resilience
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from arc.domain.models import ApprovalRequest, ApprovalStatus
from arc.services.approval_sweep import ApprovalSweepRunner, _sweep_loop
from arc.services.approvals import HumanApprovalService

_T0 = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _request(tenant_id="tenant-1", **overrides):
    defaults = dict(
        id=f"appr-{uuid.uuid4().hex[:14]}",
        tenant_id=tenant_id,
        requester_user_id="user-1",
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


class FakeApprovalRepository:
    """In-memory fake that supports the sweep interface."""

    def __init__(self, clock=None):
        self.rows = {}
        self.fail_writes = False
        self._clock = clock

    async def expire_stale_approvals(self):
        if self.fail_writes:
            raise RuntimeError("database unavailable")
        now = self._clock() if self._clock else datetime.now(timezone.utc)
        count = 0
        for row in list(self.rows.values()):
            if row.status == ApprovalStatus.PENDING and now >= row.expires_at:
                self.rows[row.id] = ApprovalRequest(
                    **{**row.__dict__, "status": ApprovalStatus.EXPIRED}
                )
                count += 1
        return count

    # Stubs for methods the service calls indirectly
    async def create(self, request):
        self.rows[request.id] = request
        return request

    async def get_by_id(self, approval_id, tenant_id):
        from arc.db.connection import NotFoundError

        row = self.rows.get(approval_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFoundError("not found")
        return row

    async def list_for_tenant(self, tenant_id, limit=100):
        return [r for r in self.rows.values() if r.tenant_id == tenant_id]

    async def find_open(self, tenant_id, tool_name, tool_version, arguments_digest):
        return None

    async def expire_if_due(self, approval_id, tenant_id):
        return False

    async def decide(self, approval_id, tenant_id, decision, decider_user_id):
        return False

    async def consume(self, approval_id, tenant_id, tool_name, tool_version, arguments_digest):
        return False


def _clock_at(offset_hours=0.0):
    state = {"hours": offset_hours}

    def _now():
        return _T0 + timedelta(hours=state["hours"])

    def _advance(hours):
        state["hours"] += hours

    return _now, _advance


def _service(clock_offset=0.0):
    now_fn, advance = _clock_at(clock_offset)
    repo = FakeApprovalRepository(clock=now_fn)
    svc = HumanApprovalService(repository=repo, clock=now_fn)
    svc._test_advance = advance
    return svc, repo


# -------------------------------------------------------------------
# Service sweep
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_expired_approvals_delegates_to_repository():
    svc, repo = _service()
    # Create two requests: one past-due, one fresh
    await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_b",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="b" * 64,
    )
    # Advance past TTL so both are stale
    svc._test_advance(25.0)
    count = await svc.sweep_expired_approvals()
    assert count == 2
    for row in repo.rows.values():
        assert row.status == ApprovalStatus.EXPIRED


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_nothing_stale():
    svc, repo = _service()
    await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    # Still within TTL
    count = await svc.sweep_expired_approvals()
    assert count == 0
    row = list(repo.rows.values())[0]
    assert row.status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_sweep_does_not_expire_non_expired_pending_rows():
    """Pending rows with future expiry must survive the sweep."""
    svc, repo = _service()
    pending_id = await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    # Advance but NOT past the 24h TTL (only 12 hours)
    svc._test_advance(12.0)
    count = await svc.sweep_expired_approvals()
    assert count == 0
    assert repo.rows[pending_id].status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_sweep_does_not_affect_non_pending_rows():
    svc, repo = _service()
    approval_id = await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    # Approve it manually (bypass lazy expiry check)
    repo.rows[approval_id] = ApprovalRequest(
        **{
            **repo.rows[approval_id].__dict__,
            "status": ApprovalStatus.APPROVED,
            "decided_at": _T0 + timedelta(minutes=5),
            "decided_by_user_id": "approver-1",
        }
    )
    svc._test_advance(25.0)
    count = await svc.sweep_expired_approvals()
    assert count == 0
    assert repo.rows[approval_id].status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_sweep_is_idempotent():
    svc, repo = _service()
    await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    svc._test_advance(25.0)
    count1 = await svc.sweep_expired_approvals()
    assert count1 == 1
    # Second sweep finds nothing to expire
    count2 = await svc.sweep_expired_approvals()
    assert count2 == 0


@pytest.mark.asyncio
async def test_sweep_across_multiple_tenants():
    svc, repo = _service()
    for tenant in ("t1", "t2", "t3"):
        await svc.record_required_approval(
            tenant_id=tenant,
            requester_user_id="u1",
            tool_name="tool_a",
            tool_version="1",
            risk_level="high",
            input_summary="{}",
            arguments_digest="a" * 64,
        )
    svc._test_advance(25.0)
    count = await svc.sweep_expired_approvals()
    assert count == 3
    for row in repo.rows.values():
        assert row.status == ApprovalStatus.EXPIRED


# -------------------------------------------------------------------
# Background runner
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_start_stop_lifecycle():
    svc, _ = _service()
    runner = ApprovalSweepRunner(svc, interval_seconds=1)
    await runner.start()
    assert runner._task is not None
    assert not runner._task.done()
    await runner.stop()
    assert runner._task is None


@pytest.mark.asyncio
async def test_runner_start_is_idempotent():
    svc, _ = _service()
    runner = ApprovalSweepRunner(svc, interval_seconds=60)
    await runner.start()
    task1 = runner._task
    await runner.start()  # second call should be no-op
    assert runner._task is task1
    await runner.stop()


@pytest.mark.asyncio
async def test_runner_stop_is_idempotent():
    svc, _ = _service()
    runner = ApprovalSweepRunner(svc, interval_seconds=60)
    await runner.start()
    await runner.stop()
    await runner.stop()  # should not raise


@pytest.mark.asyncio
async def test_runner_stop_cancels_running_task():
    """stop() must cancel the asyncio task so no orphaned task remains."""
    svc, _ = _service()
    runner = ApprovalSweepRunner(svc, interval_seconds=60)
    await runner.start()
    task = runner._task
    assert task is not None
    assert not task.done()
    await runner.stop()
    assert runner._task is None
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_runner_executes_sweep_on_tick():
    svc, repo = _service()
    await svc.record_required_approval(
        tenant_id="t1",
        requester_user_id="u1",
        tool_name="tool_a",
        tool_version="1",
        risk_level="high",
        input_summary="{}",
        arguments_digest="a" * 64,
    )
    svc._test_advance(25.0)
    runner = ApprovalSweepRunner(svc, interval_seconds=0.1)
    await runner.start()
    # Wait for at least one sweep cycle
    await asyncio.sleep(0.3)
    await runner.stop()
    for row in repo.rows.values():
        assert row.status == ApprovalStatus.EXPIRED


@pytest.mark.asyncio
async def test_runner_continues_after_repository_error():
    """Sweep loop must not die on transient DB errors."""
    svc, repo = _service()
    runner = ApprovalSweepRunner(svc, interval_seconds=0.05)

    # Make the repository fail once, then succeed
    call_count = 0
    original = repo.expire_stale_approvals

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient DB error")
        return await original()

    repo.expire_stale_approvals = flaky

    await runner.start()
    await asyncio.sleep(0.2)
    # Loop is still running (not crashed by the error)
    assert not runner._task.done()
    await runner.stop()
    assert call_count >= 2


@pytest.mark.asyncio
async def test_sweep_loop_responds_to_stop_event():
    """_sweep_loop terminates promptly when stop_event is set."""
    svc, _ = _service()
    stop_event = asyncio.Event()
    call_count = 0
    original_sweep = svc.sweep_expired_approvals

    async def counting_sweep():
        nonlocal call_count
        call_count += 1
        return await original_sweep()

    svc.sweep_expired_approvals = counting_sweep

    loop_task = asyncio.create_task(_sweep_loop(svc, interval_seconds=0.05, stop_event=stop_event))
    await asyncio.sleep(0.15)
    assert not loop_task.done()  # loop is still running
    stop_event.set()
    await asyncio.wait_for(loop_task, timeout=2)
    assert loop_task.done()  # loop has terminated
    # Should have run at least once before stopping
    assert call_count >= 1
