"""Integration regression for Issue #212: platform enable must not disable tenants.

Uses real PostgreSQL via ``PostgreSQLCapabilityRepository`` — not a
fake — so the full persistence + service path is exercised.
"""

import uuid

import pytest

from arc.domain.models import Tenant
from arc.repositories.capabilities import PostgreSQLCapabilityRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.services.capabilities import CapabilityService


def _unique(prefix: str) -> str:
    return f"issue212-{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def real_capability_service(db):
    repo = PostgreSQLCapabilityRepository(db)
    svc = CapabilityService(repo)
    return svc, repo


class TestPlatformEnableRegressionIntegration:
    async def test_platform_enable_preserves_tenant_without_override(
        self, db, real_capability_service
    ):
        """Platform absent -> enabled, platform true + tenant absent -> still enabled."""
        svc, repo = real_capability_service
        cap = "skill_execution"
        tenant_id = _unique("tenant")
        tenants = PostgreSQLTenantRepository(db)
        await tenants.create(Tenant(id=tenant_id, name="Issue212 Tenant"))

        # Snapshot original platform state so we can restore it.
        orig_platform = await repo.get_platform_capability(cap)
        orig_enabled = orig_platform.enabled if orig_platform else None

        # Ensure clean slate for this test: remove any existing rows for this
        # capability/tenant combination.
        async with db._connection_pool.acquire() as conn:
            await conn.execute("DELETE FROM tenant_capabilities WHERE tenant_id = $1", tenant_id)
            await conn.execute("DELETE FROM platform_capabilities WHERE capability_id = $1", cap)

        try:
            # 1. No platform row -> effective True (no ceiling)
            assert await svc.is_enabled(tenant_id, cap) is True

            # 2. Enable platform, leave tenant absent -> still True (the bug gave False)
            await svc.set_platform(cap, True)
            assert await svc.is_enabled(tenant_id, cap) is True

            # 3. Hard ceiling: disable platform -> False
            await svc.set_platform(cap, False)
            assert await svc.is_enabled(tenant_id, cap) is False

            # 4. Even tenant True cannot override hard ceiling
            await repo.set_tenant_capability(tenant_id, cap, True)
            assert await svc.is_enabled(tenant_id, cap) is False
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenant_capabilities WHERE tenant_id = $1", tenant_id
                )
                if orig_enabled is None:
                    await conn.execute(
                        "DELETE FROM platform_capabilities WHERE capability_id = $1", cap
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO platform_capabilities (capability_id, enabled, updated_at)
                        VALUES ($1, $2, NOW())
                        ON CONFLICT (capability_id) DO UPDATE SET enabled = $2, updated_at = NOW()
                        """,
                        cap,
                        orig_enabled,
                    )
            await tenants.delete(tenant_id)

    async def test_tenant_isolation_with_real_db(self, db, real_capability_service):
        """Tenant A absent vs tenant B disabled after platform enable."""
        svc, repo = real_capability_service
        cap = "tool_execution"
        tenant_a = _unique("tenant-a")
        tenant_b = _unique("tenant-b")
        tenants = PostgreSQLTenantRepository(db)
        await tenants.create(Tenant(id=tenant_a, name="Tenant A"))
        await tenants.create(Tenant(id=tenant_b, name="Tenant B"))

        orig_platform = await repo.get_platform_capability(cap)
        orig_enabled = orig_platform.enabled if orig_platform else None

        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM tenant_capabilities WHERE tenant_id IN ($1, $2)", tenant_a, tenant_b
            )
            await conn.execute("DELETE FROM platform_capabilities WHERE capability_id = $1", cap)

        try:
            await svc.set_platform(cap, True)
            assert await svc.is_enabled(tenant_a, cap) is True
            await svc.set_tenant(tenant_b, cap, False)
            assert await svc.is_enabled(tenant_b, cap) is False
            # Tenant A still enabled
            assert await svc.is_enabled(tenant_a, cap) is True
            # Hard ceiling disables both
            await svc.set_platform(cap, False)
            assert await svc.is_enabled(tenant_a, cap) is False
            assert await svc.is_enabled(tenant_b, cap) is False
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenant_capabilities WHERE tenant_id IN ($1, $2)",
                    tenant_a,
                    tenant_b,
                )
                if orig_enabled is None:
                    await conn.execute(
                        "DELETE FROM platform_capabilities WHERE capability_id = $1", cap
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO platform_capabilities (capability_id, enabled, updated_at)
                        VALUES ($1, $2, NOW())
                        ON CONFLICT (capability_id) DO UPDATE SET enabled = $2, updated_at = NOW()
                        """,
                        cap,
                        orig_enabled,
                    )
            await tenants.delete(tenant_a)
            await tenants.delete(tenant_b)

    async def test_nine_state_matrix_via_service_with_real_db(self, db, real_capability_service):
        """All nine combinations via real persistence."""
        svc, repo = real_capability_service
        cap = "agent_execution"
        tenant_id = _unique("tenant")
        tenants = PostgreSQLTenantRepository(db)
        await tenants.create(Tenant(id=tenant_id, name="Matrix Tenant"))

        orig_platform = await repo.get_platform_capability(cap)
        orig_enabled = orig_platform.enabled if orig_platform else None

        async def _set_platform(val):
            async with db._connection_pool.acquire() as conn:
                if val is None:
                    await conn.execute(
                        "DELETE FROM platform_capabilities WHERE capability_id = $1", cap
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO platform_capabilities (capability_id, enabled, updated_at)
                        VALUES ($1, $2, NOW())
                        ON CONFLICT (capability_id) DO UPDATE SET enabled = $2, updated_at = NOW()
                        """,
                        cap,
                        val,
                    )

        async def _set_tenant(val):
            async with db._connection_pool.acquire() as conn:
                if val is None:
                    await conn.execute(
                        "DELETE FROM tenant_capabilities WHERE tenant_id = $1 AND capability_id = $2",  # noqa: E501
                        tenant_id,
                        cap,
                    )
                else:
                    await conn.execute(
                        """
INSERT INTO tenant_capabilities (tenant_id, capability_id, enabled, updated_at)
VALUES ($1, $2, $3, NOW())
ON CONFLICT (tenant_id, capability_id) DO UPDATE SET enabled = $3, updated_at = NOW()
                        """,
                        tenant_id,
                        cap,
                        val,
                    )

        # Note: platform None + tenant True/False is not representable in
        # the real schema due to FK fk_tenant_cap_platform. Those two
        # combinations are covered by the static is_effective unit test;
        # here we test the seven representable states.
        matrix = [
            (None, None, True),
            (True, None, True),
            (True, True, True),
            (True, False, False),
            (False, None, False),
            (False, True, False),
            (False, False, False),
        ]

        try:
            for platform, tenant, expected in matrix:
                await _set_platform(platform)
                # Tenant rows require a platform row (FK). When platform
                # is None we must keep tenant None as well.
                if platform is None and tenant is not None:
                    continue
                await _set_tenant(tenant)
                assert await svc.is_enabled(tenant_id, cap) is expected, (
                    f"platform={platform!r} tenant={tenant!r} expected {expected!r}"
                )
        finally:
            async with db._connection_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tenant_capabilities WHERE tenant_id = $1", tenant_id
                )
                if orig_enabled is None:
                    await conn.execute(
                        "DELETE FROM platform_capabilities WHERE capability_id = $1", cap
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO platform_capabilities (capability_id, enabled, updated_at)
                        VALUES ($1, $2, NOW())
                        ON CONFLICT (capability_id) DO UPDATE SET enabled = $2, updated_at = NOW()
                        """,
                        cap,
                        orig_enabled,
                    )
            await tenants.delete(tenant_id)
