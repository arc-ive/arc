"""API-level tests for tenant company configuration (Issue #70).

Covers authorization (401, 403 matrix), tenant boundary enforcement,
successful update with company config fields, field persistence, and
sensitive-material absence.
"""

import uuid

import pytest

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"cfg-{prefix}-{uuid.uuid4().hex[:8]}"


def _authed_request(http_client, method, url, token, json=None):
    kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
    if json is not None:
        kwargs["json"] = json
    return getattr(http_client, method)(url, **kwargs)


COMPANY_PROFILE = {
    "industry": "Technology",
    "address": "1 Market Street",
    "phone": "+1-555-0400",
    "website": "https://acme.example.com",
    "logo_url": "https://acme.example.com/logo.png",
}

TENANT_RESPONSE_KEYS = {
    "id",
    "name",
    "status",
    "industry",
    "address",
    "phone",
    "website",
    "logo_url",
    "created_at",
    "updated_at",
}


@pytest.fixture
async def seeded(db):
    """Provision a tenant, user, and membership for testing."""
    tenants = PostgreSQLTenantRepository(db)
    users = PostgreSQLUserRepository(db)
    memberships = PostgreSQLMembershipRepository(db)

    tenant_id = _unique("t")
    user_id = _unique("u")
    tenant = await tenants.create(Tenant(id=tenant_id, name="Config Test Tenant", status="active"))
    user = await users.create(
        User(id=user_id, email=f"{_unique('e')}@example.com", username="cfguser")
    )
    await memberships.create(
        Membership(
            id=_unique("m"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )
    yield tenant, user
    async with db._connection_pool.acquire() as conn:
        await conn.execute("DELETE FROM memberships WHERE tenant_id = $1", tenant.id)
        await conn.execute("DELETE FROM users WHERE id = $1", user.id)
        await conn.execute("DELETE FROM tenants WHERE id = $1", tenant.id)


class TestAuthenticationAndAuthorization:
    async def test_update_requires_authentication(self, client, seeded):
        tenant, _ = seeded
        response = client.put(f"/tenants/{tenant.id}", json={"name": "X"})
        assert response.status_code == 401

    async def test_employee_denied_update(self, client, seeded, make_token, authorization_override):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "X"})
        assert response.status_code == 403

    async def test_operations_user_denied_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "X"})
        assert response.status_code == 403

    async def test_company_administrator_allowed_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Updated Name"}
        )
        assert response.status_code == 200

    async def test_platform_administrator_allowed_update(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Updated Name"}
        )
        assert response.status_code == 200


class TestTenantBoundary:
    async def test_cross_tenant_update_denied(
        self, client, seeded, db, make_token, authorization_override
    ):
        tenant_a, user_a = seeded
        # Create a second tenant the user is NOT a member of
        tenants = PostgreSQLTenantRepository(db)
        tenant_b = await tenants.create(
            Tenant(id=_unique("b"), name="Other Tenant", status="active")
        )
        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user_a.id)
        response = _authed_request(
            client, "put", f"/tenants/{tenant_b.id}", token, {"name": "Hacked"}
        )
        assert response.status_code == 403
        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_b.id)


class TestUpdateCompanyConfig:
    async def test_update_persists_company_fields(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        payload = {
            "name": "Updated Tenant",
            "industry": "Healthcare",
            "address": "456 Hospital Ave",
            "phone": "+1-555-0200",
            "website": "https://health.example.com",
            "logo_url": "https://health.example.com/logo.png",
        }
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, payload)
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Updated Tenant"
        assert body["industry"] == "Healthcare"
        assert body["address"] == "456 Hospital Ave"
        assert body["phone"] == "+1-555-0200"
        assert body["website"] == "https://health.example.com"
        assert body["logo_url"] == "https://health.example.com/logo.png"

    async def test_update_returns_full_tenant_shape(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(client, "put", f"/tenants/{tenant.id}", token, {"name": "Test"})
        body = response.json()
        assert set(body) == {
            "id",
            "name",
            "status",
            "industry",
            "address",
            "phone",
            "website",
            "logo_url",
            "created_at",
            "updated_at",
        }

    async def test_get_tenant_returns_company_fields(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # First update
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "Finance", "phone": "+1-555-0300"},
        )
        # Then GET
        response = _authed_request(client, "get", f"/tenants/{tenant.id}", token)
        assert response.status_code == 200
        body = response.json()
        assert body["industry"] == "Finance"
        assert body["phone"] == "+1-555-0300"

    async def test_update_preserves_existing_fields_when_not_provided(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # First update with full payload
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"name": "Full Update", "industry": "Tech", "phone": "123"},
        )
        # Second update with partial payload
        response = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, {"name": "Partial Update"}
        )
        body = response.json()
        assert body["name"] == "Partial Update"
        assert body["industry"] == "Tech"
        assert body["phone"] == "123"

    async def test_update_clears_fields_with_empty_strings(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # Set fields
        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "Tech", "phone": "123"},
        )
        # Clear fields
        response = _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"industry": "", "phone": ""},
        )
        body = response.json()
        assert body["industry"] == ""
        assert body["phone"] == ""

    async def test_status_mutation_is_rejected(
        self, client, seeded, db, make_token, authorization_override
    ):
        """Client-supplied status must not modify tenant.status.

        The intent of this test is unchanged and the guarantee is
        stronger. The expected status code moved from 200 to 422
        deliberately (issue #295): the request was previously accepted
        and the field silently dropped, so a caller attempting to suspend
        a tenant was told it had worked. A refusal is the honest answer to
        a change the endpoint cannot make, and it matches what issue #236
        established for tool execution, where a wrong key had to fail
        rather than silently execute.

        Note this also rejects the request WHOLESALE: the valid ``name``
        alongside the invalid ``status`` is not applied either. That is
        the point -- a partially-applied update is the ambiguity this
        removes.
        """
        tenant, user = seeded
        original_status = tenant.status
        original_name = tenant.name
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        # Attempt to mutate status via company configuration endpoint
        response = _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"name": "Should Not Change Status", "status": "deleted"},
        )
        assert response.status_code == 422
        # Persisted database row retains BOTH original values: nothing in
        # a rejected request is applied.
        tenants = PostgreSQLTenantRepository(db)
        persisted = await tenants.get_by_id(tenant.id)
        assert persisted.status == original_status
        assert persisted.name == original_name

    async def test_updated_at_is_refreshed_on_update(
        self, client, seeded, db, make_token, authorization_override
    ):
        """Successful update must generate a new updated_at timestamp."""
        tenant, user = seeded
        original_updated_at = tenant.updated_at
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        response = _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"name": "Timestamp Test"},
        )
        assert response.status_code == 200
        body = response.json()
        # updated_at must differ from the original
        assert body["updated_at"] != original_updated_at.isoformat()
        # Persisted database row must match the API response
        tenants = PostgreSQLTenantRepository(db)
        persisted = await tenants.get_by_id(tenant.id)
        assert persisted.updated_at.isoformat() == body["updated_at"]
        # created_at must not change.  Compare the API response value
        # against the persisted DB value (both timezone-aware) because the
        # seeded fixture uses a naive datetime that may differ from how
        # PostgreSQL interprets and returns it.
        from datetime import datetime

        body_created = datetime.fromisoformat(body["created_at"])
        assert body_created == persisted.created_at


class TestUserTenantListCompanyFields:
    """Issue #128: the tenant list endpoint must carry company profile fields.

    ``GET /users/{user_id}/tenants`` publishes the same profile keys as
    ``GET /tenants/{tenant_id}``.  It previously selected only five columns,
    so every profile field was served as ``null`` for data that existed.
    """

    async def test_list_returns_stored_profile_values(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        update = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, dict(COMPANY_PROFILE)
        )
        assert update.status_code == 200

        response = _authed_request(client, "get", f"/users/{user.id}/tenants", token)
        assert response.status_code == 200
        entry = next(item for item in response.json()["items"] if item["id"] == tenant.id)
        for field, expected in COMPANY_PROFILE.items():
            assert entry[field] == expected, f"{field} was {entry[field]!r}"

    async def test_list_profile_matches_single_tenant_endpoint(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        update = _authed_request(
            client, "put", f"/tenants/{tenant.id}", token, dict(COMPANY_PROFILE)
        )
        assert update.status_code == 200

        listed = next(
            item
            for item in _authed_request(client, "get", f"/users/{user.id}/tenants", token).json()[
                "items"
            ]
            if item["id"] == tenant.id
        )
        single = _authed_request(client, "get", f"/tenants/{tenant.id}", token).json()
        for field in COMPANY_PROFILE:
            # Assert the value is really there: two nulls would compare equal
            # and the parity check would hold vacuously.
            assert single[field] == COMPANY_PROFILE[field]
            assert listed[field] == single[field], f"{field} differs between endpoints"

    async def test_list_entry_shape_is_unchanged(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = _authed_request(client, "get", f"/users/{user.id}/tenants", token)
        assert response.status_code == 200
        entry = next(item for item in response.json()["items"] if item["id"] == tenant.id)
        assert set(entry) == TENANT_RESPONSE_KEYS

    async def test_list_returns_null_profile_when_unset(
        self, client, seeded, make_token, authorization_override
    ):
        """An unpopulated profile still reports null — absence is not invented."""
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = _authed_request(client, "get", f"/users/{user.id}/tenants", token)
        entry = next(item for item in response.json()["items"] if item["id"] == tenant.id)
        for field in COMPANY_PROFILE:
            assert entry[field] is None

    async def test_platform_listing_carries_profile_fields(
        self, client, db, seeded, make_token, authorization_override
    ):
        """The platform-wide listing must carry the profile too.

        ``/platform/tenants`` publishes a narrower key set today, so this is
        asserted at the repository boundary: the omission would otherwise stay
        invisible until someone widens that endpoint.
        """
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        _authed_request(client, "put", f"/tenants/{tenant.id}", token, dict(COMPANY_PROFILE))

        listed = await PostgreSQLTenantRepository(db).list_all()
        found = next(item for item in listed if item.id == tenant.id)
        for field, expected in COMPANY_PROFILE.items():
            assert getattr(found, field) == expected, f"{field} was {getattr(found, field)!r}"

    async def test_paginated_listings_carry_profile_fields(
        self, client, db, seeded, make_token, authorization_override
    ):
        """The paginated queries must carry the profile too.

        Pagination (Issue #129) introduced a second query for each listing.
        Those queries selected their own narrower column set, which reopened
        this issue on the endpoints that now use them.
        """
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        _authed_request(client, "put", f"/tenants/{tenant.id}", token, dict(COMPANY_PROFILE))

        repository = PostgreSQLTenantRepository(db)
        memberships = PostgreSQLMembershipRepository(db)
        listings = {
            "list_all_paginated": (await repository.list_all_paginated(100, 0))[0],
            "get_tenants_for_user_paginated": (
                await memberships.get_tenants_for_user_paginated(user.id, 100, 0)
            )[0],
        }
        for source, tenants in listings.items():
            found = next(item for item in tenants if item.id == tenant.id)
            for field, expected in COMPANY_PROFILE.items():
                actual = getattr(found, field)
                assert actual == expected, f"{source}: {field} was {actual!r}"


class TestTenantSuspension:
    """POST /tenants/{tenant_id}/status (ADR-011).

    tenants.status existed but nothing consulted it at any authorization
    boundary, so a suspended tenant behaved exactly like an active one.
    Writing the value without enforcing it would have been theatre: the
    UI reporting a customer as stopped while all their users kept
    working.
    """

    @staticmethod
    def _url(tenant_id):
        return f"/tenants/{tenant_id}/status"

    async def test_platform_administrator_can_suspend_and_restore(
        self, client, seeded, db, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        suspended = _authed_request(
            client, "post", self._url(tenant.id), token, {"status": "suspended"}
        )
        assert suspended.status_code == 200
        assert suspended.json()["status"] == "suspended"

        restored = _authed_request(
            client, "post", self._url(tenant.id), token, {"status": "active"}
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "active"

        # Lossless: the record is intact after the round trip.
        tenants = PostgreSQLTenantRepository(db)
        persisted = await tenants.get_by_id(tenant.id)
        assert persisted.status == "active"
        assert persisted.name == tenant.name

    async def test_a_company_administrator_cannot_suspend_their_own_tenant(
        self, client, seeded, make_token, authorization_override
    ):
        """A customer cannot suspend or un-suspend themselves.

        The endpoint needs the GLOBAL tenant:update; a company
        administrator holds it scoped to their own tenant for profile
        fields only.
        """
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})

        response = _authed_request(
            client,
            "post",
            self._url(tenant.id),
            make_token(user.id),
            {"status": "suspended"},
        )

        assert response.status_code == 403

    async def test_an_unknown_status_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

        response = _authed_request(
            client,
            "post",
            self._url(tenant.id),
            make_token(user.id),
            {"status": "deleted"},
        )

        assert response.status_code == 422

    async def test_suspension_denies_tenant_scoped_access(
        self, client, seeded, make_token, authorization_override
    ):
        """The point of the whole change.

        Enforced in TenantContextService, where every tenant-scoped route
        already converges, so this covers routes that do not exist yet.
        """
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        before = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert before.status_code == 200

        _authed_request(client, "post", self._url(tenant.id), token, {"status": "suspended"})

        after = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert after.status_code == 403
        # The message does not distinguish suspension from non-membership:
        # telling a customer their company was suspended is the operator's
        # news to deliver, not an error message's.
        assert "denied" in after.json()["detail"].lower()

    async def test_restoring_returns_access(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        _authed_request(client, "post", self._url(tenant.id), token, {"status": "suspended"})
        _authed_request(client, "post", self._url(tenant.id), token, {"status": "active"})

        response = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    async def test_profile_update_still_cannot_change_status(
        self, client, seeded, make_token, authorization_override
    ):
        """ADR-011 adds an endpoint; it does not loosen the other one."""
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

        response = _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            make_token(user.id),
            {"status": "suspended"},
        )

        assert response.status_code == 422

    async def test_a_stale_profile_write_cannot_revert_a_suspension(self, seeded, db):
        """The lost-update this fix exists to prevent.

        update_tenant wrote EVERY column, including status. A profile
        edit that read the row while the tenant was active, and wrote
        after a suspension committed in between, carried the stale
        "active" value back over the suspension. The operator would
        believe a customer was stopped when they were not, with nothing
        to indicate it.

        The race is real but not reachable through two sequential HTTP
        calls, because a suspended tenant's routes are refused -- so the
        second call would 403 rather than revert. It is reachable when a
        slow profile edit STRADDLES the suspension: the read is allowed,
        the write lands after. This reproduces exactly that ordering
        deterministically, by holding the stale object across the
        suspension.
        """
        tenant, _ = seeded
        tenants = PostgreSQLTenantRepository(db)

        # A profile edit reads the row while the tenant is still active.
        stale = await tenants.get_by_id(tenant.id)
        assert stale.status == "active"

        # A platform operator suspends it in between.
        await tenants.set_status(tenant.id, "suspended")

        # The in-flight edit now writes, carrying status="active".
        stale.name = "Renamed Mid-Flight"
        await tenants.update(stale)

        persisted = await tenants.get_by_id(tenant.id)
        assert persisted.name == "Renamed Mid-Flight", "the rename was lost"
        assert persisted.status == "suspended", (
            "a stale profile write silently reverted the suspension"
        )

    async def test_setting_status_leaves_every_other_field_untouched(
        self, client, seeded, db, make_token, authorization_override
    ):
        """A targeted write must not blank the columns it does not set."""
        tenant, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        _authed_request(
            client,
            "put",
            f"/tenants/{tenant.id}",
            token,
            {"name": "Acme Co", "industry": "Logistics", "phone": "+44 117 000 0000"},
        )
        _authed_request(
            client, "post", f"/tenants/{tenant.id}/status", token, {"status": "suspended"}
        )

        tenants = PostgreSQLTenantRepository(db)
        persisted = await tenants.get_by_id(tenant.id)
        assert persisted.status == "suspended"
        assert persisted.name == "Acme Co"
        assert persisted.industry == "Logistics"
        assert persisted.phone == "+44 117 000 0000"

    async def test_setting_status_on_an_unknown_tenant_is_not_found(
        self, client, seeded, make_token, authorization_override
    ):
        _, user = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})

        response = _authed_request(
            client,
            "post",
            "/tenants/no-such-tenant/status",
            make_token(user.id),
            {"status": "suspended"},
        )

        assert response.status_code == 404
