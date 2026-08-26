"""Real-PostgreSQL tests for the ApprovalRequestRepository contract.

Proves tenant isolation at the SQL level, terminal-state immutability,
exact-binding single-use consumption (including a true concurrent-consume
race over one pool), and lazy expiry transitions. Raw arguments never
exist in this layer: only the redacted summary and digest are persisted.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import ApprovalRequest, ApprovalStatus, Tenant
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository

_NOW = datetime.now(timezone.utc)
_DIGEST = "b" * 64


def _request(tenant_id, **overrides):
    defaults = dict(
        id=f"appr-{uuid.uuid4().hex[:14]}",
        tenant_id=tenant_id,
        requested_by_user_id="user-1",
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary='{"target": "svc"}',
        arguments_digest=_DIGEST,
        status=ApprovalStatus.PENDING,
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )
    defaults.update(overrides)
    return ApprovalRequest(**defaults)


@pytest.fixture
async def two_tenants(db):
    tenants = PostgreSQLTenantRepository(db)
    created = [
        await tenants.create(Tenant(id=f"appr-{label}-{uuid.uuid4().hex[:8]}", name=label))
        for label in ("A", "B")
    ]
    yield created
    for tenant in created:
        await tenants.delete(tenant.id)


class TestPersistenceAndIsolation:
    async def test_create_and_get_round_trip(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        fetched = await repo.get_by_id(request.id, two_tenants[0].id)
        assert fetched.arguments_digest == _DIGEST
        assert fetched.status == ApprovalStatus.PENDING

    async def test_get_by_id_is_tenant_scoped(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(request.id, two_tenants[1].id)

    async def test_list_is_tenant_scoped(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        await repo.create(_request(two_tenants[0].id))
        await repo.create(_request(two_tenants[1].id))
        assert len(await repo.list_for_tenant(two_tenants[0].id)) == 1
        assert len(await repo.list_for_tenant(two_tenants[1].id)) == 1


class TestDecideTransitions:
    async def test_approve_transitions_pending_to_approved(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        performed = await repo.decide(
            request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-1"
        )
        assert performed is True
        fetched = await repo.get_by_id(request.id, request.tenant_id)
        assert fetched.status == ApprovalStatus.APPROVED
        assert fetched.decided_by_user_id == "approver-1"
        assert fetched.decided_at is not None

    async def test_terminal_states_are_immutable(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        assert await repo.decide(
            request.id, request.tenant_id, ApprovalStatus.REJECTED, "approver-1"
        )
        # rejected -> approved must not fire; rejected stays rejected
        assert (
            await repo.decide(request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-2")
            is False
        )
        rejected_row = await repo.get_by_id(request.id, request.tenant_id)
        assert rejected_row.status == ApprovalStatus.REJECTED

    async def test_decide_cross_tenant_cannot_transition(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        assert (
            await repo.decide(request.id, two_tenants[1].id, ApprovalStatus.APPROVED, "attacker")
            is False
        )
        pending_row = await repo.get_by_id(request.id, request.tenant_id)
        assert pending_row.status == ApprovalStatus.PENDING


class TestLazyExpiry:
    async def test_expire_if_due_only_transitions_past_due_rows(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        due = _request(two_tenants[0].id)
        future = _request(two_tenants[0].id, expires_at=_NOW + timedelta(hours=48))
        past_not_pending = _request(
            two_tenants[0].id,
            status=ApprovalStatus.REJECTED,
            decided_at=_NOW + timedelta(minutes=5),
            decided_by_user_id="approver",
        )
        for request in (due, future, past_not_pending):
            await repo.create(request)

        # The physical rows keep wall-clock expiry from creation defaults;
        # force `due` to be past-due relative to DB now().
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approval_requests
                SET created_at = NOW() - INTERVAL '25 hours',
                    expires_at = NOW() - INTERVAL '1 hour'
                WHERE id = $1
                """,
                due.id,
            )

        assert await repo.expire_if_due(due.id, two_tenants[0].id) is True
        assert await repo.expire_if_due(due.id, two_tenants[0].id) is False
        assert await repo.expire_if_due(future.id, two_tenants[0].id) is False
        due_row = await repo.get_by_id(due.id, two_tenants[0].id)
        assert due_row.status == ApprovalStatus.EXPIRED
        future_row = await repo.get_by_id(future.id, two_tenants[0].id)
        assert future_row.status == ApprovalStatus.PENDING


class TestSingleUseConsumption:
    async def test_consume_requires_approved_state(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)  # still pending
        await repo.create(request)
        assert (
            await repo.consume(request.id, request.tenant_id, "restart_service", "1", _DIGEST)
            is False
        )

    async def test_consume_exact_binding_single_use(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        await repo.decide(request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-1")

        assert (
            await repo.consume(request.id, request.tenant_id, "restart_service", "1", _DIGEST)
            is True
        )
        consumed = await repo.get_by_id(request.id, request.tenant_id)
        assert consumed.status == ApprovalStatus.CONSUMED
        assert consumed.consumed_at is not None

        # Replay fails.
        assert (
            await repo.consume(request.id, request.tenant_id, "restart_service", "1", _DIGEST)
            is False
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"tool_name": "other_tool"},
            {"tool_version": "2"},
            {"arguments_digest": "c" * 64},
        ],
    )
    async def test_consume_binding_mismatches_fail(self, db, two_tenants, kwargs):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        await repo.decide(request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-1")
        binding = {
            "tool_name": "restart_service",
            "tool_version": "1",
            "arguments_digest": _DIGEST,
        }
        binding.update(kwargs)
        assert await repo.consume(request.id, request.tenant_id, **binding) is False

    async def test_consume_cross_tenant_fails(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        await repo.decide(request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-1")
        assert (
            await repo.consume(request.id, two_tenants[1].id, "restart_service", "1", _DIGEST)
            is False
        )

    async def test_concurrent_consumers_exactly_one_succeeds(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        request = _request(two_tenants[0].id)
        await repo.create(request)
        await repo.decide(request.id, request.tenant_id, ApprovalStatus.APPROVED, "approver-1")

        results = await asyncio.gather(
            *[
                repo.consume(request.id, request.tenant_id, "restart_service", "1", _DIGEST)
                for _ in range(2)
            ]
        )
        assert sorted(results, reverse=True) == [True, False]
        consumed = await repo.get_by_id(request.id, request.tenant_id)
        assert consumed.status == ApprovalStatus.CONSUMED
