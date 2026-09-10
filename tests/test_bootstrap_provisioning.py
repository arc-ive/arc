"""Regression tests for idempotent bootstrap provisioning (Issue #119).

The bootstrap seed data (demo-user, demo-tenant, demo-membership) must
exist after application startup so that the documented demo identity can
authenticate and create tenants.

These tests exercise the bootstrap SQL directly against the database
without requiring full app startup, avoiding coupling to the installed
package version.
"""

SEED_SQL = [
    (
        "INSERT INTO users (id, email, username, status, created_at, updated_at) "
        "SELECT 'demo-user', 'demo@example.com', 'demo_user', 'active', NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = 'demo-user')"
    ),
    (
        "INSERT INTO tenants (id, name, status, created_at, updated_at) "
        "SELECT 'demo-tenant', 'Demo Tenant', 'active', NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = 'demo-tenant')"
    ),
    (
        "INSERT INTO memberships (id, user_id, tenant_id, role, created_at, updated_at) "
        "SELECT 'demo-membership', 'demo-user', 'demo-tenant', 'owner', NOW(), NOW() "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM memberships WHERE user_id = 'demo-user' AND tenant_id = 'demo-tenant'"
        ")"
    ),
]


async def _seed(db):
    """Run bootstrap seed SQL."""
    async with db._connection_pool.acquire() as conn:
        for sql in SEED_SQL:
            await conn.execute(sql)


async def test_demo_user_exists_after_bootstrap(db):
    """After bootstrap, demo-user must exist in the users table."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, username, status FROM users WHERE id = $1",
            "demo-user",
        )
    assert row is not None
    assert row["id"] == "demo-user"
    assert row["email"] == "demo@example.com"
    assert row["status"] == "active"


async def test_demo_tenant_exists_after_bootstrap(db):
    """After bootstrap, demo-tenant must exist in the tenants table."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, status FROM tenants WHERE id = $1",
            "demo-tenant",
        )
    assert row is not None
    assert row["id"] == "demo-tenant"
    assert row["name"] == "Demo Tenant"
    assert row["status"] == "active"


async def test_demo_membership_exists_after_bootstrap(db):
    """After bootstrap, demo-membership links demo-user to demo-tenant."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, tenant_id, role FROM memberships "
            "WHERE user_id = $1 AND tenant_id = $2",
            "demo-user",
            "demo-tenant",
        )
    assert row is not None
    assert row["user_id"] == "demo-user"
    assert row["tenant_id"] == "demo-tenant"
    assert row["role"] == "owner"


async def test_bootstrap_is_idempotent(db):
    """Running bootstrap twice must not create duplicate rows."""
    await _seed(db)
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", "demo-user")
        tenant_count = await conn.fetchval(
            "SELECT COUNT(*) FROM tenants WHERE id = $1", "demo-tenant"
        )
        membership_count = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships WHERE user_id = $1 AND tenant_id = $2",
            "demo-user",
            "demo-tenant",
        )
    assert user_count == 1
    assert tenant_count == 1
    assert membership_count == 1


async def test_bootstrap_preserves_existing_data(db):
    """Bootstrap must not overwrite pre-existing data."""
    async with db._connection_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, email, username, status, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING",
            "existing-user",
            "existing@example.com",
            "existing_user",
            "active",
        )

    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, email FROM users WHERE id = $1", "existing-user")
        demo = await conn.fetchrow("SELECT id, email FROM users WHERE id = $1", "demo-user")

    assert row is not None
    assert row["email"] == "existing@example.com"
    assert demo is not None
    assert demo["email"] == "demo@example.com"

    async with db._connection_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE id = $1", "existing-user")
