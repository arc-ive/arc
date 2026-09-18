"""API-level tests for the Human Intervention approval gate (V1).

Covers authentication, the centralized RBAC matrix (platform/company
admins read+decide; operations user and employees denied), trusted tenant
scoping with path-consistency 403, lifecycle exposure (including lazy
expiry), decision terminality, and response minimization (never raw
arguments, never the internal digest).
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


async def _seed(db, tenant_id, *, status=ApprovalStatus.PENDING, arguments_digest=_DIGEST):
    repo = PostgreSQLApprovalRequestRepository(db)
    request = ApprovalRequest(
        id=f"appr-{uuid.uuid4().hex[:14]}",
        tenant_id=tenant_id,
        requester_user_id="requester-1",
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

    async def test_operations_user_cannot_read_or_decide(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        assert _authed(client, "get", _url(tenant.id), token).status_code == 403
        assert (
            _authed(
                client,
                "post",
                _url(tenant.id, f"/{_unique('appr')}/decisions"),
                token,
                json={"decision": "approve"},
            ).status_code
            == 403
        )

    @pytest.mark.parametrize("assign_role", [None, ApplicationRole.EMPLOYEE])
    async def test_employee_and_unassigned_denied(
        self, client, seeded, make_token, authorization_override, assign_role
    ):
        tenant, user, _ = seeded
        authorization_override({} if assign_role is None else {user.id: assign_role})
        token = make_token(user.id)
        assert _authed(client, "get", _url(tenant.id), token).status_code == 403


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
