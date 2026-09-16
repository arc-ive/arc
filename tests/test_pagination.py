"""Pagination tests for Arc list endpoints.

Verifies that limit/offset parameters produce correct page slicing
and that the V2 paginated response contract (items, total, page,
page_size) is honored across all affected list endpoints.

Uses real PostgreSQL integration tests following the existing
test conventions.
"""

import uuid

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"pg-{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# PaginationParams unit tests
# ---------------------------------------------------------------------------


class TestPaginationParams:
    def test_defaults(self):
        from arc.api.pagination import PaginationParams

        p = PaginationParams.from_query(None, None)
        assert p.limit == 20
        assert p.offset == 0

    def test_positive_values(self):
        from arc.api.pagination import PaginationParams

        p = PaginationParams.from_query(10, 5)
        assert p.limit == 10
        assert p.offset == 5

    def test_limit_clamped_to_max(self):
        from arc.api.pagination import MAX_PAGE_SIZE, PaginationParams

        p = PaginationParams.from_query(999, 0)
        assert p.limit == MAX_PAGE_SIZE

    def test_negative_offset_defaults_to_zero(self):
        from arc.api.pagination import PaginationParams

        p = PaginationParams.from_query(10, -1)
        assert p.offset == 0

    def test_zero_limit_uses_default(self):
        from arc.api.pagination import DEFAULT_PAGE_SIZE, PaginationParams

        p = PaginationParams.from_query(0, 0)
        assert p.limit == DEFAULT_PAGE_SIZE


# ---------------------------------------------------------------------------
# paginate() unit tests
# ---------------------------------------------------------------------------


class TestPaginate:
    def test_basic_response_shape(self):
        from arc.api.pagination import PaginationParams, paginate

        params = PaginationParams(limit=10, offset=0)
        result = paginate([1, 2, 3], total=5, params=params)
        assert result["items"] == [1, 2, 3]
        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 10

    def test_page_calculation(self):
        from arc.api.pagination import PaginationParams, paginate

        params = PaginationParams(limit=10, offset=20)
        result = paginate([], total=50, params=params)
        assert result["page"] == 3

    def test_empty_page(self):
        from arc.api.pagination import PaginationParams, paginate

        params = PaginationParams(limit=10, offset=100)
        result = paginate([], total=5, params=params)
        assert result["items"] == []
        assert result["total"] == 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_knowledge(client, tenant, token, count):
    """Create *count* knowledge documents for a tenant."""
    for i in range(count):
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            json={
                "source": "policy",
                "provenance": f"Doc {i}",
                "content": f"Content {i}",
            },
            headers={"Authorization": f"Bearer {token}"},
        )


async def _seed_tenant_with_admin(repositories):
    """Create a tenant + admin user + membership and return helpers."""
    tenant_repo, user_repo, membership_repo = repositories
    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="PG Tenant"))
    user = await user_repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="pg-user",
        )
    )
    membership = await membership_repo.create(
        Membership(
            id=_unique("mem"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )
    )
    return tenant, user, membership


async def _cleanup_tenant(repositories, tenant, user, membership):
    tenant_repo, user_repo, membership_repo = repositories
    await membership_repo.delete(membership.id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant.id)


# ---------------------------------------------------------------------------
# Integration tests — Knowledge list pagination
# ---------------------------------------------------------------------------


class TestKnowledgeListPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /tenants/{id}/knowledge?limit=1 returns at most 1 item."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        await _seed_knowledge(client, tenant, token, 3)

        resp = client.get(
            f"/tenants/{tenant.id}/knowledge?limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert len(body["items"]) == 1
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 1

        # Second page
        resp2 = client.get(
            f"/tenants/{tenant.id}/knowledge?limit=1&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 1
        assert body2["page"] == 2
        assert body2["items"][0]["id"] != body["items"][0]["id"]

        await _cleanup_tenant(repositories, tenant, user, membership)

    async def test_limit_larger_than_total(
        self, client, repositories, make_token, authorization_override
    ):
        """limit > total returns all items."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        await _seed_knowledge(client, tenant, token, 2)

        resp = client.get(
            f"/tenants/{tenant.id}/knowledge?limit=100&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 2

        await _cleanup_tenant(repositories, tenant, user, membership)

    async def test_offset_beyond_total(
        self, client, repositories, make_token, authorization_override
    ):
        """offset > total returns empty items."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        await _seed_knowledge(client, tenant, token, 1)

        resp = client.get(
            f"/tenants/{tenant.id}/knowledge?limit=10&offset=100",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 1

        await _cleanup_tenant(repositories, tenant, user, membership)

    async def test_omitted_params_returns_default_page(
        self, client, repositories, make_token, authorization_override
    ):
        """No limit/offset returns default page (20 items)."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        await _seed_knowledge(client, tenant, token, 1)

        resp = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page_size"] == 20
        assert body["page"] == 1
        assert len(body["items"]) == 1

        await _cleanup_tenant(repositories, tenant, user, membership)


# ---------------------------------------------------------------------------
# Integration tests — Users list pagination
# ---------------------------------------------------------------------------


class TestUserListPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /tenants/{id}/users?limit=1 returns at most 1 user."""
        tenant_repo, user_repo, membership_repo = repositories
        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="PG Tenant"))
        users_created = []
        memberships_created = []
        for i in range(3):
            u = await user_repo.create(
                User(
                    id=_unique("user"),
                    email=f"{uuid.uuid4().hex}@example.com",
                    username=f"pg-user-{i}",
                )
            )
            users_created.append(u)
            m = await membership_repo.create(
                Membership(
                    id=_unique("mem"),
                    user_id=u.id,
                    tenant_id=tenant.id,
                    role=UserRole.MEMBER,
                )
            )
            memberships_created.append(m)

        admin_user = users_created[0]
        authorization_override({admin_user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(admin_user.id)

        resp = client.get(
            f"/tenants/{tenant.id}/users?limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["total"] == 3
        assert body["page_size"] == 1

        # Second page
        resp2 = client.get(
            f"/tenants/{tenant.id}/users?limit=1&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        body2 = resp2.json()
        assert len(body2["items"]) == 1
        assert body2["items"][0]["id"] != body["items"][0]["id"]

        for m in memberships_created:
            await membership_repo.delete(m.id)
        for u in users_created:
            await user_repo.delete(u.id)
        await tenant_repo.delete(tenant.id)


# ---------------------------------------------------------------------------
# Integration tests — Skills list pagination
# ---------------------------------------------------------------------------


class TestSkillListPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /skills?tenant_id=X&limit=1 returns at most 1 skill."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        # Create 3 skills
        for i in range(3):
            client.post(
                f"/skills?tenant_id={tenant.id}",
                json={
                    "name": f"skill-{i}",
                    "version": "1.0",
                    "purpose": f"Purpose {i}",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = client.get(
            f"/skills?tenant_id={tenant.id}&limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["total"] == 3

        await _cleanup_tenant(repositories, tenant, user, membership)


# ---------------------------------------------------------------------------
# Integration tests — Connectors list pagination
# ---------------------------------------------------------------------------


class TestConnectorListPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /tenants/{id}/connectors?limit=1 returns at most 1."""
        tenant, user, membership = await _seed_tenant_with_admin(repositories)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        for i in range(2):
            client.post(
                f"/tenants/{tenant.id}/connectors",
                json={
                    "provider": "github",
                    "name": f"conn-{i}",
                    "target": f"https://example.com/{i}",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        resp = client.get(
            f"/tenants/{tenant.id}/connectors?limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["total"] == 2

        await _cleanup_tenant(repositories, tenant, user, membership)


# ---------------------------------------------------------------------------
# Integration tests — Platform tenants pagination
# ---------------------------------------------------------------------------


class TestPlatformTenantPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /platform/tenants?limit=1 returns at most 1 tenant."""
        tenant_repo, _, _ = repositories
        tenants = []
        for i in range(3):
            t = await tenant_repo.create(Tenant(id=_unique("tenant"), name=f"Tenant {i}"))
            tenants.append(t)

        authorization_override({"platform-admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token("platform-admin")

        resp = client.get(
            "/platform/tenants?limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["total"] >= 3
        assert body["page_size"] == 1

        # Second page
        resp2 = client.get(
            "/platform/tenants?limit=1&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        body2 = resp2.json()
        assert len(body2["items"]) == 1
        assert body2["items"][0]["id"] != body["items"][0]["id"]

        for t in tenants:
            await tenant_repo.delete(t.id)


# ---------------------------------------------------------------------------
# Integration tests — Platform users pagination
# ---------------------------------------------------------------------------


class TestPlatformUserPagination:
    async def test_limit_returns_subset(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /platform/users?limit=1 returns at most 1 user."""
        _, user_repo, _ = repositories
        users = []
        for i in range(3):
            u = await user_repo.create(
                User(
                    id=_unique("user"),
                    email=f"{uuid.uuid4().hex}@example.com",
                    username=f"pg-user-{i}",
                )
            )
            users.append(u)

        authorization_override({"platform-admin": ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token("platform-admin")

        resp = client.get(
            "/platform/users?limit=1&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["total"] >= 3

        for u in users:
            await user_repo.delete(u.id)


# ---------------------------------------------------------------------------
# Integration tests — Tenant isolation with pagination
# ---------------------------------------------------------------------------


class TestPaginationTenantIsolation:
    async def test_pagination_does_not_leak_across_tenants(
        self, client, repositories, make_token, authorization_override
    ):
        """Paginated results for tenant A must not include B's data."""
        tenant_repo, user_repo, membership_repo = repositories

        tenant_a = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant A"))
        tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Tenant B"))
        user_a = await user_repo.create(
            User(
                id=_unique("user"),
                email=f"{uuid.uuid4().hex}@example.com",
                username="user-a",
            )
        )
        user_b = await user_repo.create(
            User(
                id=_unique("user"),
                email=f"{uuid.uuid4().hex}@example.com",
                username="user-b",
            )
        )
        mem_a = await membership_repo.create(
            Membership(
                id=_unique("mem"),
                user_id=user_a.id,
                tenant_id=tenant_a.id,
                role=UserRole.OWNER,
            )
        )
        mem_b = await membership_repo.create(
            Membership(
                id=_unique("mem"),
                user_id=user_b.id,
                tenant_id=tenant_b.id,
                role=UserRole.OWNER,
            )
        )

        authorization_override(
            {
                user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR,
                user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )
        token_a = make_token(user_a.id)
        token_b = make_token(user_b.id)

        # Create knowledge for tenant A
        await _seed_knowledge(client, tenant_a, token_a, 3)

        # Create knowledge for tenant B
        client.post(
            f"/tenants/{tenant_b.id}/knowledge",
            json={
                "source": "policy",
                "provenance": "Doc B",
                "content": "Content B",
            },
            headers={"Authorization": f"Bearer {token_b}"},
        )

        # Tenant A sees only its docs
        resp_a = client.get(
            f"/tenants/{tenant_a.id}/knowledge?limit=10&offset=0",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        body_a = resp_a.json()
        assert body_a["total"] == 3
        assert all(item["tenant_id"] == tenant_a.id for item in body_a["items"])

        # Tenant B sees only its doc
        resp_b = client.get(
            f"/tenants/{tenant_b.id}/knowledge?limit=10&offset=0",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        body_b = resp_b.json()
        assert body_b["total"] == 1

        # Cleanup
        await membership_repo.delete(mem_a.id)
        await membership_repo.delete(mem_b.id)
        await user_repo.delete(user_a.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_a.id)
        await tenant_repo.delete(tenant_b.id)
