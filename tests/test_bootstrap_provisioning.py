"""Tests for idempotent reference data provisioning.

The reference data provisioning must create a production-like
multi-tenant environment on application startup. These tests verify
that provisioning is idempotent and creates the expected data.
"""

from arc.setup.reference_data import seed_reference_data


async def _seed(db):
    """Run reference data provisioning."""
    async with db._connection_pool.acquire() as conn:
        await seed_reference_data(conn)


async def test_reference_tenants_exist(db):
    """After provisioning, all 4 reference tenants must exist."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, status FROM tenants WHERE id LIKE 'ref-%' ORDER BY id"
        )
    tenant_ids = [r["id"] for r in rows]
    assert "ref-acme-technologies" in tenant_ids
    assert "ref-nova-systems" in tenant_ids
    assert "ref-vertex-solutions" in tenant_ids
    assert "ref-northstar-digital" in tenant_ids
    assert len(rows) == 4


async def test_reference_users_exist(db):
    """After provisioning, all 17 reference users must exist."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, status FROM users WHERE id LIKE 'ref-%' ORDER BY id"
        )
    user_ids = [r["id"] for r in rows]
    assert "ref-platform-admin" in user_ids
    assert "ref-acme-technologies-company-admin" in user_ids
    assert "ref-acme-technologies-ops-user" in user_ids
    assert "ref-acme-technologies-employee-1" in user_ids
    assert "ref-acme-technologies-employee-2" in user_ids
    # Same pattern for other tenants
    assert "ref-nova-systems-company-admin" in user_ids
    assert "ref-vertex-solutions-company-admin" in user_ids
    assert "ref-northstar-digital-company-admin" in user_ids
    assert len(rows) == 17


async def test_reference_memberships_exist(db):
    """After provisioning, all 16 tenant memberships must exist."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, tenant_id, role FROM memberships "
            "WHERE user_id LIKE 'ref-%' ORDER BY id"
        )
    # 16 tenant memberships (4 tenants x 4 users each)
    assert len(rows) == 16

    # Verify roles
    memberships_by_tenant = {}
    for r in rows:
        tenant = r["tenant_id"]
        if tenant not in memberships_by_tenant:
            memberships_by_tenant[tenant] = []
        memberships_by_tenant[tenant].append((r["user_id"], r["role"]))

    for tenant_id, members in memberships_by_tenant.items():
        assert len(members) == 4
        roles = {role for _, role in members}
        assert "owner" in roles
        assert "member" in roles
        assert "viewer" in roles


async def test_reference_connectors_exist(db):
    """After provisioning, connectors must exist for each tenant."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, tenant_id, provider, name FROM connector_configs "
            "WHERE tenant_id LIKE 'ref-%' ORDER BY tenant_id, provider"
        )
    # 4 tenants x 2 connectors each = 8
    assert len(rows) == 8

    # Each tenant should have github and slack
    by_tenant = {}
    for r in rows:
        by_tenant.setdefault(r["tenant_id"], set()).add(r["provider"])
    for tenant_id, providers in by_tenant.items():
        assert "github" in providers
        assert "slack" in providers


async def test_reference_knowledge_documents_exist(db):
    """After provisioning, knowledge documents must exist for each tenant."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, tenant_id, source, external_id FROM knowledge_documents "
            "WHERE tenant_id LIKE 'ref-%' ORDER BY tenant_id, source"
        )
    # 4 tenants x 2 documents each = 8
    assert len(rows) == 8


async def test_reference_skills_exist(db):
    """After provisioning, skills must exist for each tenant."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, tenant_id, name, status FROM skills "
            "WHERE tenant_id LIKE 'ref-%' ORDER BY tenant_id"
        )
    # 4 tenants x 1 skill each = 4
    assert len(rows) == 4
    for r in rows:
        assert r["status"] == "active"


async def test_provisioning_is_idempotent(db):
    """Running provisioning twice must not create duplicate rows."""
    await _seed(db)
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        tenant_count = await conn.fetchval("SELECT COUNT(*) FROM tenants WHERE id LIKE 'ref-%'")
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id LIKE 'ref-%'")
        membership_count = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships WHERE user_id LIKE 'ref-%'"
        )
        connector_count = await conn.fetchval(
            "SELECT COUNT(*) FROM connector_configs WHERE tenant_id LIKE 'ref-%'"
        )
        knowledge_count = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_documents WHERE tenant_id LIKE 'ref-%'"
        )
        skill_count = await conn.fetchval(
            "SELECT COUNT(*) FROM skills WHERE tenant_id LIKE 'ref-%'"
        )

    assert tenant_count == 4
    assert user_count == 17
    assert membership_count == 16
    assert connector_count == 8
    assert knowledge_count == 8
    assert skill_count == 4


async def test_provisioning_preserves_existing_data(db):
    """Provisioning must not overwrite pre-existing data."""
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
    assert row is not None
    assert row["email"] == "existing@example.com"

    async with db._connection_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE id = $1", "existing-user")


async def test_platform_admin_has_no_membership(db):
    """Platform administrator must not have a tenant membership."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships WHERE user_id = $1",
            "ref-platform-admin",
        )
    assert count == 0


async def test_demo_records_not_created(db):
    """Provisioning must not create obsolete demo records."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        demo_tenant = await conn.fetchval(
            "SELECT COUNT(*) FROM tenants WHERE id = $1", "demo-tenant"
        )
        demo_user = await conn.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", "demo-user")
        demo_membership = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships WHERE id = $1", "demo-membership"
        )
    assert demo_tenant == 0
    assert demo_user == 0
    assert demo_membership == 0


async def test_referential_integrity(db):
    """All memberships must reference valid users and tenants."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        # Check all membership user_ids exist in users
        orphan_memberships = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships m "
            "WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = m.user_id)"
        )
        assert orphan_memberships == 0

        # Check all membership tenant_ids exist in tenants
        orphan_memberships = await conn.fetchval(
            "SELECT COUNT(*) FROM memberships m "
            "WHERE NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = m.tenant_id)"
        )
        assert orphan_memberships == 0

        # Check all connector tenant_ids exist
        orphan_connectors = await conn.fetchval(
            "SELECT COUNT(*) FROM connector_configs c "
            "WHERE NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = c.tenant_id)"
        )
        assert orphan_connectors == 0

        # Check all knowledge tenant_ids exist
        orphan_knowledge = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_documents k "
            "WHERE NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = k.tenant_id)"
        )
        assert orphan_knowledge == 0

        # Check all skill tenant_ids exist
        orphan_skills = await conn.fetchval(
            "SELECT COUNT(*) FROM skills s "
            "WHERE NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = s.tenant_id)"
        )
        assert orphan_skills == 0


async def test_no_cross_tenant_resource_ownership(db):
    """Each resource must belong to exactly one tenant."""
    await _seed(db)

    async with db._connection_pool.acquire() as conn:
        # Each connector belongs to exactly one tenant
        connector_tenants = await conn.fetchval(
            "SELECT COUNT(DISTINCT tenant_id) FROM connector_configs WHERE tenant_id LIKE 'ref-%'"
        )
        assert connector_tenants == 4

        # Each knowledge doc belongs to exactly one tenant
        knowledge_tenants = await conn.fetchval(
            "SELECT COUNT(DISTINCT tenant_id) FROM knowledge_documents WHERE tenant_id LIKE 'ref-%'"
        )
        assert knowledge_tenants == 4

        # Each skill belongs to exactly one tenant
        skill_tenants = await conn.fetchval(
            "SELECT COUNT(DISTINCT tenant_id) FROM skills WHERE tenant_id LIKE 'ref-%'"
        )
        assert skill_tenants == 4
