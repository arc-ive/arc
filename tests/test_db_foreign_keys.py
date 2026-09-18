"""Foreign key constraint on tenant_capabilities.capability_id (Issue #188).

The column referenced platform_capabilities with nothing enforcing that the
capability exists, so removing one left tenant rows pointing at nothing and
joins on it silently dropped rows.

The tests exercise the constraint's behaviour — what actually happens to the
referencing row when its target is deleted — rather than asserting that a
constraint by some name exists, which would pass even if the ON DELETE action
were wrong.

Issue #188 also asked for foreign keys on two agent_run_id columns and on
tool_execution_records.user_id. Those cannot be added as specified; see the
pull request for why.
"""

import uuid

import pytest

from arc.domain.models import Tenant
from arc.repositories.tenancy import PostgreSQLTenantRepository


def _uid(prefix: str) -> str:
    return f"fk-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def tenant(db):
    """A tenant to hang the referencing rows from."""
    repo = PostgreSQLTenantRepository(db)
    created = await repo.create(Tenant(id=_uid("t"), name="FK Test Tenant"))
    yield created
    async with db._connection_pool.acquire() as conn:
        await conn.execute("DELETE FROM tenants WHERE id = $1", created.id)


class TestTenantCapabilityFollowsItsPlatformCapability:
    """A tenant's flag is meaningless once the capability itself is gone."""

    async def test_deleting_platform_capability_cascades(self, db, tenant):
        capability_id = _uid("cap")[:100]
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO platform_capabilities (capability_id) VALUES ($1)", capability_id
            )
            await conn.execute(
                """INSERT INTO tenant_capabilities (tenant_id, capability_id, enabled)
                   VALUES ($1, $2, TRUE)""",
                tenant.id,
                capability_id,
            )

            await conn.execute(
                "DELETE FROM platform_capabilities WHERE capability_id = $1", capability_id
            )

            remaining = await conn.fetchval(
                "SELECT COUNT(*) FROM tenant_capabilities WHERE capability_id = $1", capability_id
            )
        assert remaining == 0

    async def test_unknown_capability_is_rejected(self, db, tenant):
        """The reference must point at a capability the platform defines."""
        import asyncpg

        async with db._connection_pool.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    """INSERT INTO tenant_capabilities (tenant_id, capability_id, enabled)
                       VALUES ($1, 'no-such-capability', TRUE)""",
                    tenant.id,
                )
