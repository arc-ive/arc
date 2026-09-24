"""API-level tests for the Human Intervention approval gate (V1).

Covers authentication, the centralized RBAC matrix (platform/company
admins read the whole tenant and decide; everyone else reads only their
own requests and decides nothing -- ADR-012), trusted tenant scoping with
path-consistency 403, lifecycle exposure (including lazy expiry),
decision terminality, and response minimization (never raw arguments,
never the internal digest).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from arc.domain.models import ApprovalRequest, ApprovalStatus, Membership, Tenant, User, UserRole
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.security.models import ApplicationRole

_NOW = datetime.now(timezone.utc)
_DIGEST = "f" * 64


def _unique(prefix):
    return f"apig-{prefix}-{uuid.uuid4().hex[:8]}"


def _digest(seed):
    """A distinct 64-char digest per row.

    A pending request is unique on
    ``(tenant_id, tool_name, tool_version, arguments_digest)``, so tests
    that seed several rows in one tenant must vary this.
    """
    return f"{seed:064x}"


async def _seed(
    db,
    tenant_id,
    *,
    status=ApprovalStatus.PENDING,
    arguments_digest=_DIGEST,
    requester_user_id="requester-1",
):
    repo = PostgreSQLApprovalRequestRepository(db)
    request = ApprovalRequest(
        id=f"appr-{uuid.uuid4().hex[:14]}",
        tenant_id=tenant_id,
        requester_user_id=requester_user_id,
        tool_name="restart_service",
        tool_version="1",
        risk_level="high",
        input_summary='{"target": "svc"}',
        arguments_digest=arguments_digest,
        status=status,
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
        decided_at=None if status == ApprovalStatus.PENDING else _NOW + timedelta(minutes=5),
        decided_by_user_id=None if status == ApprovalStatus.PENDING else "approver-1",
        consumed_at=_NOW + timedelta(minutes=6) if status == ApprovalStatus.CONSUMED else None,
    )
    await repo.create(request)
    return request


async def _member_tenant_with_user(db, role=UserRole.MEMBER):
    """A fresh tenant plus a provisioned member user (X-10 boundary)."""
    tenants = PostgreSQLTenantRepository(db)
    users = PostgreSQLUserRepository(db)
    memberships = PostgreSQLMembershipRepository(db)
    tenant = await tenants.create(Tenant(id=_unique("tenant"), name="Approval"))
    user = await users.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="approvals")
    )
    await memberships.create(
        Membership(id=_unique("membership"), user_id=user.id, tenant_id=tenant.id, role=role)
    )
    return tenant, user


def _url(tenant_id, suffix=""):
    return f"/tenants/{tenant_id}/approvals{suffix}"


def _authed(client, method, url, token, **kwargs):
    return getattr(client, method)(url, headers={"Authorization": f"Bearer {token}"}, **kwargs)


class TestAuthenticationAndRbac:
    async def test_list_requires_authentication(self, client, seeded):
        tenant, _, _ = seeded
        assert client.get(_url(tenant.id)).status_code == 401

    async def test_decide_requires_authentication(self, client, seeded):
        tenant, _, _ = seeded
        response = client.post(
            _url(tenant.id, f"/{_unique('appr')}/decisions"),
            json={"decision": "approve"},
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "assign_role",
        [None, ApplicationRole.EMPLOYEE, ApplicationRole.OPERATIONS_USER],
    )
    async def test_caller_without_approval_read_sees_no_one_elses_request(
        self, client, seeded, make_token, authorization_override, db, assign_role
    ):
        """ADR-012 narrows these callers; it does not widen them.

        The listing succeeds now, but over the caller's OWN rows only.
        A colleague's pending request is seeded here and must not appear,
        and ``total`` must not count it.
        """
        tenant, user, _ = seeded
        await _seed(db, tenant.id, requester_user_id="somebody-else")
        authorization_override({} if assign_role is None else {user.id: assign_role})
        token = make_token(user.id)

        listing = _authed(client, "get", _url(tenant.id), token)
        assert listing.status_code == 200
        assert listing.json()["items"] == []
        assert listing.json()["total"] == 0

    @pytest.mark.parametrize(
        "assign_role",
        [None, ApplicationRole.EMPLOYEE, ApplicationRole.OPERATIONS_USER],
    )
    async def test_caller_without_approval_decide_cannot_decide(
        self, client, seeded, make_token, authorization_override, db, assign_role
    ):
        """Reading your own request never became deciding it (ADR-012)."""
        tenant, user, _ = seeded
        own = await _seed(db, tenant.id, requester_user_id=user.id)
        authorization_override({} if assign_role is None else {user.id: assign_role})
        token = make_token(user.id)

        for approval_id in (own.id, _unique("appr")):
            assert (
                _authed(
                    client,
                    "post",
                    _url(tenant.id, f"/{approval_id}/decisions"),
                    token,
                    json={"decision": "approve"},
                ).status_code
                == 403
            )


class TestDecisionsAndLifecycle:
    @pytest.mark.parametrize(
        "role",
        [ApplicationRole.PLATFORM_ADMINISTRATOR, ApplicationRole.COMPANY_ADMINISTRATOR],
    )
    async def test_admin_roles_can_list_and_decide(
        self, client, seeded, make_token, authorization_override, db, role
    ):
        tenant, user, _ = seeded
        request_row = await _seed(db, tenant.id)
        authorization_override({user.id: role})
        token = make_token(user.id)

        listing = _authed(client, "get", _url(tenant.id), token)
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 1

        decision = _authed(
            client,
            "post",
            _url(tenant.id, f"/{request_row.id}/decisions"),
            token,
            json={"decision": "approve"},
        )
        assert decision.status_code == 200
        body = decision.json()
        assert body["status"] == "approved"
        assert body["decided_by_user_id"] == user.id

        second = _authed(
            client,
            "post",
            _url(tenant.id, f"/{request_row.id}/decisions"),
            token,
            json={"decision": "reject"},
        )
        assert second.status_code == 409

    async def test_reject_decision_terminal(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        request_row = await _seed(db, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        decision = _authed(
            client,
            "post",
            _url(tenant.id, f"/{request_row.id}/decisions"),
            token,
            json={"decision": "reject"},
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "rejected"

    async def test_invalid_decision_body_400(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        await _seed(db, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed(
            client,
            "post",
            _url(tenant.id, f"/{_unique('appr')}/decisions"),
            token,
            json={"decision": "maybe"},
        )
        assert response.status_code == 422

    async def test_unknown_approval_404(self, client, seeded, make_token, authorization_override):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        assert (
            _authed(client, "get", _url(tenant.id, f"/{_unique('appr')}"), token).status_code == 404
        )

    async def test_path_tenant_without_membership_403(
        self, client, seeded, make_token, authorization_override, db
    ):
        """Fail-closed: no X-10 membership in the path tenant => 403."""
        foreign_tenant = await PostgreSQLTenantRepository(db).create(
            Tenant(id=_unique("foreign"), name="Foreign")
        )
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        assert _authed(client, "get", _url(foreign_tenant.id), token).status_code == 403


class TestExpiredLifecycleExposure:
    async def test_past_due_pending_reads_expired_and_cannot_be_approved(
        self, client, seeded, make_token, authorization_override, db
    ):
        repo = PostgreSQLApprovalRequestRepository(db)
        tenant, user, _ = seeded
        request = await _seed(db, tenant.id)
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approval_requests
                SET created_at = NOW() - INTERVAL '25 hours',
                    expires_at = NOW() - INTERVAL '1 hour'
                WHERE id = $1
                """,
                request.id,
            )

        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        listing = _authed(client, "get", _url(tenant.id), token).json()["items"]
        assert listing[0]["status"] == "expired"

        detail = _authed(client, "get", _url(tenant.id, f"/{request.id}"), token)
        assert detail.json()["status"] == "expired"

        decision = _authed(
            client,
            "post",
            _url(tenant.id, f"/{request.id}/decisions"),
            token,
            json={"decision": "approve"},
        )
        assert decision.status_code == 409
        assert decision.json()["detail"].startswith("Approval")

        after = await repo.get_by_id(request.id, tenant.id)
        assert after.status == ApprovalStatus.EXPIRED


class TestResponseMinimizationAndIsolation:
    async def test_response_never_contains_digest_or_raw_arguments(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        request_row = await _seed(db, tenant.id)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        body = _authed(client, "get", _url(tenant.id, f"/{request_row.id}"), token).json()
        assert set(body) == {
            "id",
            "tool_name",
            "tool_version",
            "risk_level",
            "status",
            "requester_user_id",
            "input_summary",
            "created_at",
            "expires_at",
            "decided_at",
            "decided_by_user_id",
            "consumed_at",
        }
        serialized = str(body)
        assert _DIGEST not in serialized
        assert "arguments" not in serialized

    async def test_cross_tenant_request_is_invisible(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        # The foreign row must satisfy its own tenant FK: create a real
        # second tenant, then prove our tenant cannot see its approvals.
        foreign_tenant = await PostgreSQLTenantRepository(db).create(
            Tenant(id=_unique("foreign-tenant"), name="Foreign")
        )
        other_request = await _seed(db, foreign_tenant.id)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        assert (
            _authed(client, "get", _url(tenant.id, f"/{other_request.id}"), token).status_code
            == 404
        )
        assert _authed(client, "get", _url(foreign_tenant.id), token).status_code == 403


class TestEmptyListingAndFieldMapping:
    async def test_empty_listing_returns_200_and_empty_list(
        self, client, seeded, make_token, authorization_override
    ):
        """GET /tenants/{id}/approvals with no records returns 200 and []."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed(client, "get", _url(tenant.id), token)
        assert response.status_code == 200
        assert response.json()["items"] == []

    async def test_listing_maps_requester_user_id_correctly(
        self, client, seeded, make_token, authorization_override, db
    ):
        """The requester_user_id field is mapped from the database column."""
        tenant, user, _ = seeded
        await _seed(db, tenant.id)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        body = _authed(client, "get", _url(tenant.id), token).json()["items"]
        assert len(body) == 1
        assert body[0]["requester_user_id"] == "requester-1"

    async def test_status_filter_returns_matching_approvals(
        self, client, seeded, make_token, authorization_override, db
    ):
        """Status filtering continues to work after the column rename."""
        tenant, user, _ = seeded
        await _seed(db, tenant.id)
        await _seed(db, tenant.id, arguments_digest="a" * 64)
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        all_approvals = _authed(client, "get", _url(tenant.id), token).json()["items"]
        assert len(all_approvals) == 2

        pending = _authed(client, "get", _url(tenant.id) + "?status=pending", token).json()["items"]
        assert len(pending) == 2
        assert all(a["status"] == "pending" for a in pending)

        rejected_url = _url(tenant.id) + "?status=rejected"
        rejected = _authed(client, "get", rejected_url, token).json()["items"]
        assert len(rejected) == 0


class TestCorruptRowControlledError:
    """Issue #239: a corrupt persisted row is a controlled 500, never an unhandled one."""

    def _install_failing_service(self, method, exc):
        from unittest.mock import AsyncMock

        from arc.api.controllers import app_context

        mock = AsyncMock()
        setattr(mock, method, AsyncMock(side_effect=exc))
        previous = app_context.services._services.get("human_approval_service")
        app_context.services.register("human_approval_service", mock)
        return previous

    def _restore_service(self, previous):
        from arc.api.controllers import app_context

        if previous is None:
            app_context.services._services.pop("human_approval_service", None)
        else:
            app_context.services.register("human_approval_service", previous)

    async def test_corrupt_row_on_detail_is_controlled_500(
        self, client, seeded, make_token, authorization_override
    ):
        from arc.services.approvals import ApprovalCorruptError

        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        previous = self._install_failing_service("get_request", ApprovalCorruptError("unreadable"))
        try:
            response = _authed(client, "get", _url(tenant.id, "/appr-corrupt"), token)
        finally:
            self._restore_service(previous)
        assert response.status_code == 500
        body = response.json()
        assert body == {"detail": "Approval request data is invalid"}
        assert "Traceback" not in response.text
        assert "approval_requests" not in response.text

    async def test_corrupt_row_on_list_is_controlled_500(
        self, client, seeded, make_token, authorization_override
    ):
        from arc.services.approvals import ApprovalCorruptError

        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        previous = self._install_failing_service(
            "list_requests_paginated", ApprovalCorruptError("unreadable")
        )
        try:
            response = _authed(client, "get", _url(tenant.id), token)
        finally:
            self._restore_service(previous)
        assert response.status_code == 500
        assert response.json() == {"detail": "Approval request data is invalid"}

    async def test_corrupt_row_on_decide_is_controlled_500(
        self, client, seeded, make_token, authorization_override
    ):
        from arc.services.approvals import ApprovalCorruptError

        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        previous = self._install_failing_service(
            "decide_request", ApprovalCorruptError("unreadable")
        )
        try:
            response = _authed(
                client,
                "post",
                _url(tenant.id, "/appr-corrupt/decisions"),
                token,
                json={"decision": "approve"},
            )
        finally:
            self._restore_service(previous)
        assert response.status_code == 500
        assert response.json() == {"detail": "Approval decision failed"}


class TestSelfScopedRead:
    """ADR-012: a requester may always read the requests they raised.

    The role under test is ``OPERATIONS_USER`` because that is the real
    case: it holds ``tool:execute`` and not ``approval:read``, so it is
    the role that produces approval requests it could not previously see
    -- which left the resume path ("Run it now") unreachable for the
    people most likely to need it.

    Every test here seeds MORE rows in the tenant than the caller
    authored, so a narrowing applied after fetching a page would show up
    either in ``items`` or in ``total``.
    """

    async def test_requester_sees_own_request_and_not_a_colleagues(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        mine = await _seed(db, tenant.id, requester_user_id=user.id)
        for index in range(6):
            await _seed(
                db,
                tenant.id,
                requester_user_id=f"colleague-{index % 2}",
                arguments_digest=_digest(index),
            )
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        body = _authed(client, "get", _url(tenant.id), token).json()

        assert [item["id"] for item in body["items"]] == [mine.id]
        # Not just the page: the count is scoped too, so the caller never
        # learns how much approval traffic the tenant carries.
        assert body["total"] == 1

    async def test_permission_holder_still_reads_the_whole_tenant(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        await _seed(db, tenant.id, requester_user_id=user.id)
        await _seed(db, tenant.id, requester_user_id="colleague-1", arguments_digest=_digest(1))
        await _seed(db, tenant.id, requester_user_id="colleague-2", arguments_digest=_digest(2))
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        body = _authed(client, "get", _url(tenant.id), token).json()

        assert len(body["items"]) == 3
        assert body["total"] == 3

    async def test_scoped_pagination_pages_over_the_scoped_set(
        self, client, seeded, make_token, authorization_override, db
    ):
        """LIMIT/OFFSET must bind to the scoped query, not an unscoped one."""
        tenant, user, _ = seeded
        for index in range(3):
            await _seed(db, tenant.id, requester_user_id=user.id, arguments_digest=_digest(index))
        for index in range(3, 5):
            await _seed(
                db, tenant.id, requester_user_id="colleague-1", arguments_digest=_digest(index)
            )
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        first = _authed(client, "get", _url(tenant.id) + "?limit=2&offset=0", token).json()
        second = _authed(client, "get", _url(tenant.id) + "?limit=2&offset=2", token).json()

        assert first["total"] == 3 and second["total"] == 3
        assert len(first["items"]) == 2
        assert len(second["items"]) == 1
        seen = {item["id"] for item in first["items"] + second["items"]}
        assert len(seen) == 3
        assert all(item["requester_user_id"] == user.id for item in first["items"])

    async def test_self_scope_does_not_reach_across_tenants(
        self, client, seeded, make_token, authorization_override, db
    ):
        """The requester predicate is an extra AND, never a replacement.

        The SAME user authors a request in another tenant. Listing the
        tenant they are a member of must not surface it.
        """
        tenant, user, _ = seeded
        other_tenant, _ = await _member_tenant_with_user(db)
        mine_here = await _seed(db, tenant.id, requester_user_id=user.id)
        await _seed(db, other_tenant.id, requester_user_id=user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        body = _authed(client, "get", _url(tenant.id), token).json()

        assert [item["id"] for item in body["items"]] == [mine_here.id]
        assert body["total"] == 1
        # And the tenant they have no membership in is still refused
        # outright by the X-10 boundary, scope or no scope.
        assert _authed(client, "get", _url(other_tenant.id), token).status_code == 403

    async def test_requester_can_read_own_approval_by_id(
        self, client, seeded, make_token, authorization_override, db
    ):
        tenant, user, _ = seeded
        mine = await _seed(db, tenant.id, requester_user_id=user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = _authed(client, "get", _url(tenant.id, f"/{mine.id}"), token)

        assert response.status_code == 200
        assert response.json()["id"] == mine.id

    async def test_reading_someone_elses_approval_by_id_is_404_not_403(
        self, client, seeded, make_token, authorization_override, db
    ):
        """An unreadable row must not confirm that it exists."""
        tenant, user, _ = seeded
        theirs = await _seed(db, tenant.id, requester_user_id="colleague-1")
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = _authed(client, "get", _url(tenant.id, f"/{theirs.id}"), token)

        assert response.status_code == 404
        unknown = _authed(client, "get", _url(tenant.id, f"/{_unique('appr')}"), token)
        assert response.json() == unknown.json()

    async def test_requester_still_cannot_decide_their_own_request(
        self, client, seeded, make_token, authorization_override, db
    ):
        """Read scope did not become decide scope."""
        tenant, user, _ = seeded
        mine = await _seed(db, tenant.id, requester_user_id=user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = _authed(
            client,
            "post",
            _url(tenant.id, f"/{mine.id}/decisions"),
            token,
            json={"decision": "approve"},
        )

        assert response.status_code == 403
        # The row is untouched: still pending, still undecided.
        after = _authed(client, "get", _url(tenant.id, f"/{mine.id}"), token).json()
        assert after["status"] == "pending"
        assert after["decided_by_user_id"] is None

    async def test_scoped_read_still_redacts(
        self, client, seeded, make_token, authorization_override, db
    ):
        """Response minimization is not relaxed for the owner of the row."""
        tenant, user, _ = seeded
        await _seed(db, tenant.id, requester_user_id=user.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        item = _authed(client, "get", _url(tenant.id), token).json()["items"][0]

        assert "arguments_digest" not in item
        assert "encrypted_input" not in item
        assert "input_key_version" not in item
