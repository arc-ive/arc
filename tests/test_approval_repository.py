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
        requester_user_id="user-1",
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
        due = _request(two_tenants[0].id, arguments_digest="b" * 64)
        future = _request(
            two_tenants[0].id,
            arguments_digest="c" * 64,
            expires_at=_NOW + timedelta(hours=48),
        )
        past_not_pending = _request(
            two_tenants[0].id,
            arguments_digest="d" * 64,
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


class TestRaceSafeCreation:
    """Unique partial index on (tenant, tool, version, digest) WHERE
    status='pending' enforces at most one open approval per binding."""

    async def test_concurrent_create_exactly_one_open(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)

        async def _create():
            r = _request(two_tenants[0].id)
            return await repo.create(r)

        results = await asyncio.gather(*[_create() for _ in range(4)])
        # All four should succeed (the index catches races and returns the
        # existing row via the DuplicateKeyError handler).
        assert len(results) == 4
        # Exactly one distinct ID among the returned rows.
        ids = {r.id for r in results}
        assert len(ids) == 1

        # Exactly one pending row in the database for this binding.
        rows = await repo.list_for_tenant(two_tenants[0].id)
        pending = [r for r in rows if r.status == ApprovalStatus.PENDING]
        assert len(pending) == 1

    async def test_different_tenants_create_independently(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        r_a = _request(two_tenants[0].id)
        r_b = _request(two_tenants[1].id)
        await repo.create(r_a)
        await repo.create(r_b)
        assert len(await repo.list_for_tenant(two_tenants[0].id)) == 1
        assert len(await repo.list_for_tenant(two_tenants[1].id)) == 1

    async def test_different_bindings_create_independently(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        r1 = _request(two_tenants[0].id, tool_name="tool_a")
        r2 = _request(two_tenants[0].id, tool_name="tool_b")
        await repo.create(r1)
        await repo.create(r2)
        rows = await repo.list_for_tenant(two_tenants[0].id)
        assert len(rows) == 2


class TestBulkExpiry:
    async def test_expire_stale_approvals_transitions_past_due_pending(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        due = _request(two_tenants[0].id, arguments_digest="e" * 64)
        future = _request(
            two_tenants[0].id,
            arguments_digest="f" * 64,
            expires_at=_NOW + timedelta(hours=48),
        )
        for r in (due, future):
            await repo.create(r)

        # Force due request to be past-due
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

        count = await repo.expire_stale_approvals()
        assert count == 1

        due_row = await repo.get_by_id(due.id, two_tenants[0].id)
        assert due_row.status == ApprovalStatus.EXPIRED
        future_row = await repo.get_by_id(future.id, two_tenants[0].id)
        assert future_row.status == ApprovalStatus.PENDING

        # Approved row is not affected by the sweep
        approved_id = f"appr-approved-{uuid.uuid4().hex[:10]}"
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO approval_requests
                    (id, tenant_id, requester_user_id, tool_name, tool_version,
                     risk_level, input_summary, arguments_digest, status,
                     created_at, expires_at, decided_at, decided_by_user_id)
                VALUES ($1, $2, 'u1', 'tool_a', '1', 'high', '{}', $3,
                        'approved', NOW() - INTERVAL '2 hours',
                        NOW() + INTERVAL '22 hours', NOW() - INTERVAL '1 hour',
                        'approver-1')
                """,
                approved_id,
                two_tenants[0].id,
                "a1" * 32,
            )
        approved_row = await repo.get_by_id(approved_id, two_tenants[0].id)
        assert approved_row.status == ApprovalStatus.APPROVED

    async def test_expire_stale_approvals_is_idempotent(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        due = _request(two_tenants[0].id, arguments_digest="a2" * 32)
        await repo.create(due)
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
        count1 = await repo.expire_stale_approvals()
        assert count1 == 1
        count2 = await repo.expire_stale_approvals()
        assert count2 == 0

    async def test_expire_stale_approvals_cross_tenant(self, db, two_tenants):
        repo = PostgreSQLApprovalRequestRepository(db)
        digests = ["a3" * 32, "a4" * 32]
        requests = []
        for tenant, digest in zip(two_tenants, digests):
            requests.append(await repo.create(_request(tenant.id, arguments_digest=digest)))
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approval_requests
                SET created_at = NOW() - INTERVAL '25 hours',
                    expires_at = NOW() - INTERVAL '1 hour'
                WHERE id = $1 OR id = $2
                """,
                requests[0].id,
                requests[1].id,
            )
        count = await repo.expire_stale_approvals()
        assert count == 2
        for tenant in two_tenants:
            rows = await repo.list_for_tenant(tenant.id)
            assert all(r.status == ApprovalStatus.EXPIRED for r in rows)
