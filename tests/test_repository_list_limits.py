"""Repository list bounds (Issue #183, V2-ADR-022).

Proves every repository list method enforces a bounded result:
- the shared ``DEFAULT_LIST_LIMIT`` safety default,
- explicit smaller limits with deterministic newest-first ordering,
- tenant isolation under limits.

Uses real PostgreSQL integration tests following project conventions.
API-layer pagination behavior is covered by ``tests/test_pagination.py``;
these tests cover the repository boundary itself.
"""

import uuid
from datetime import datetime, timedelta, timezone

from arc.domain.models import (
    AgentRunRecord,
    AgentRunRecordStep,
    ConnectorConfig,
    ConnectorCredentialAudit,
    ConnectorProvider,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
    KnowledgeDocument,
    KnowledgeSource,
    Membership,
    Skill,
    SkillExecutionRecord,
    SkillExecutionStatus,
    Tenant,
    User,
    UserRole,
)
from arc.repositories import DEFAULT_LIST_LIMIT
from arc.repositories.capabilities import PostgreSQLCapabilityRepository
from arc.repositories.connector_credentials import PostgreSQLConnectorCredentialRepository
from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.observability import PostgreSQLObservabilityRepository
from arc.repositories.skill_execution import PostgreSQLSkillExecutionRecordRepository
from arc.repositories.skills import PostgreSQLSkillRepository
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)


def _unique(prefix: str) -> str:
    return f"rl-{prefix}-{uuid.uuid4().hex[:10]}"


async def _tenant(db, prefix="tenant"):
    repo = PostgreSQLTenantRepository(db)
    created = await repo.create(Tenant(id=_unique(prefix), name="List Limit Tenant"))
    return repo, created


async def _user(db, tenant_id: str):
    repo = PostgreSQLUserRepository(db)
    created = await repo.create(
        User(
            id=_unique("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="list-user",
        )
    )
    memberships = PostgreSQLMembershipRepository(db)
    await memberships.create(
        Membership(
            id=_unique("membership"),
            user_id=created.id,
            tenant_id=tenant_id,
            role=UserRole.MEMBER,
        )
    )
    return created


class TestDefaultListLimit:
    def test_default_is_bounded_and_reasonable(self):
        assert DEFAULT_LIST_LIMIT == 1000


class TestTenantListLimit:
    async def test_default_returns_all_below_cap(self, db):
        repo, tenant = await _tenant(db)
        try:
            for _ in range(3):
                await repo.create(Tenant(id=_unique("tenant"), name="Extra Tenant"))
            rows = await repo.list_all()
            assert len(rows) >= 4
        finally:
            await repo.delete(tenant.id)

    async def test_explicit_limit_and_order(self, db):
        repo = PostgreSQLTenantRepository(db)
        ids = []
        try:
            for _ in range(3):
                created = await repo.create(Tenant(id=_unique("tenant"), name="Ordered"))
                ids.append(created.id)
            rows = await repo.list_all(limit=2)
            assert len(rows) == 2
            # Newest first, deterministic.
            assert rows[0].created_at >= rows[1].created_at
        finally:
            for tid in ids:
                await repo.delete(tid)

    async def test_default_cap_is_enforced(self, db):
        repo = PostgreSQLTenantRepository(db)
        ids = [f"rl-cap-{uuid.uuid4().hex[:8]}-{i:04d}" for i in range(DEFAULT_LIST_LIMIT + 5)]
        try:
            for tid in ids:
                await repo.create(Tenant(id=tid, name="Cap Tenant"))
            rows = await repo.list_all()
            assert len(rows) == DEFAULT_LIST_LIMIT
        finally:
            for tid in ids:
                await repo.delete(tid)


class TestMembershipListLimits:
    async def test_memberships_bounded_per_user_with_isolation(self, db):
        tenants, user, other = [], None, None
        memberships = PostgreSQLMembershipRepository(db)
        try:
            for _ in range(3):
                _, tenant = await _tenant(db)
                tenants.append(tenant)
            user = await _user(db, tenants[0].id)
            for tenant in tenants[1:]:
                await memberships.create(
                    Membership(
                        id=_unique("membership"),
                        user_id=user.id,
                        tenant_id=tenant.id,
                        role=UserRole.MEMBER,
                    )
                )
            other_tenant_repo, other_tenant = await _tenant(db)
            tenants.append(other_tenant)
            other = await _user(db, other_tenant.id)

            rows = await memberships.get_memberships_for_user(user.id)
            assert len(rows) == 3
            assert {r.tenant_id for r in rows} == {t.id for t in tenants[:3]}

            limited = await memberships.get_memberships_for_user(user.id, limit=2)
            assert len(limited) == 2

            assert await memberships.get_memberships_for_user(other.id) != rows
            assert len(await memberships.get_memberships_for_user(other.id)) == 1

            tenant_rows = await memberships.get_memberships_for_tenant(tenants[0].id)
            assert {r.user_id for r in tenant_rows} == {user.id}
        finally:
            for tenant in tenants:
                await PostgreSQLTenantRepository(db).delete(tenant.id)

    async def test_tenants_for_user_bounded(self, db):
        memberships = PostgreSQLMembershipRepository(db)
        tenant_repo = PostgreSQLTenantRepository(db)
        created = []
        try:
            _, first = await _tenant(db)
            created.append(first)
            user = await _user(db, first.id)
            for _ in range(2):
                _, tenant = await _tenant(db)
                created.append(tenant)
                await memberships.create(
                    Membership(
                        id=_unique("membership"),
                        user_id=user.id,
                        tenant_id=tenant.id,
                        role=UserRole.MEMBER,
                    )
                )
            assert len(await memberships.get_tenants_for_user(user.id)) == 3
            assert len(await memberships.get_tenants_for_user(user.id, limit=2)) == 2
        finally:
            for tenant in created:
                await tenant_repo.delete(tenant.id)


class TestTenantUserListLimits:
    async def test_users_for_tenant_bounded_with_isolation(self, db):
        tenant_repo, tenant = await _tenant(db)
        _, other_tenant = await _tenant(db)
        try:
            await _user(db, tenant.id)
            await _user(db, tenant.id)
            await _user(db, other_tenant.id)

            users = PostgreSQLUserRepository(db)
            rows = await users.get_by_tenant(tenant.id)
            assert len(rows) == 2
            assert all(u.id for u in rows)

            limited = await users.get_by_tenant(tenant.id, limit=1)
            assert len(limited) == 1
        finally:
            await tenant_repo.delete(tenant.id)
            await tenant_repo.delete(other_tenant.id)


class TestSkillsListLimit:
    async def test_bounded_newest_first_with_isolation(self, db):
        tenant_repo, tenant = await _tenant(db)
        _, other = await _tenant(db)
        repo = PostgreSQLSkillRepository(db)
        try:
            for i in range(3):
                await repo.create(
                    Skill(
                        id=_unique("skill"),
                        tenant_id=tenant.id,
                        name=f"Skill {i}",
                        purpose="test",
                    )
                )
            await repo.create(
                Skill(id=_unique("skill"), tenant_id=other.id, name="Other", purpose="test")
            )
            rows = await repo.list_for_tenant(tenant.id)
            assert len(rows) == 3
            assert all(s.tenant_id == tenant.id for s in rows)

            limited = await repo.list_for_tenant(tenant.id, limit=2)
            assert len(limited) == 2
            assert limited[0].created_at >= limited[1].created_at
        finally:
            await tenant_repo.delete(tenant.id)
            await tenant_repo.delete(other.id)


class TestKnowledgeListLimit:
    async def test_bounded_active_only_with_isolation(self, db):
        tenant_repo, tenant = await _tenant(db)
        _, other = await _tenant(db)
        repo = PostgreSQLKnowledgeRepository(db)
        try:
            for i in range(3):
                await repo.create(
                    KnowledgeDocument(
                        id=_unique("doc"),
                        tenant_id=tenant.id,
                        source=KnowledgeSource.POLICY,
                        provenance="handbook",
                        content=f"Policy {i}.",
                    )
                )
            await repo.create(
                KnowledgeDocument(
                    id=_unique("doc"),
                    tenant_id=other.id,
                    source=KnowledgeSource.POLICY,
                    provenance="handbook",
                    content="Other policy.",
                )
            )
            rows = await repo.list_for_tenant(tenant.id)
            assert len(rows) == 3

            limited = await repo.list_for_tenant(tenant.id, limit=2)
            assert len(limited) == 2
            assert limited[0].created_at >= limited[1].created_at
        finally:
            await tenant_repo.delete(tenant.id)
            await tenant_repo.delete(other.id)


class TestConnectorListLimits:
    async def test_configs_and_sync_bounded(self, db):
        tenant_repo, tenant = await _tenant(db)
        configs = PostgreSQLConnectorRepository(db)
        sync = PostgreSQLConnectorSyncRepository(db)
        try:
            for i in range(3):
                config = await configs.create(
                    ConnectorConfig(
                        id=_unique("conn"),
                        tenant_id=tenant.id,
                        provider=ConnectorProvider.GITHUB,
                        name=f"conn-{i}",
                    )
                )
                await sync.create_record(
                    ConnectorSyncRecord(
                        id=_unique("sync"),
                        tenant_id=tenant.id,
                        connector_id=config.id,
                        provider=ConnectorProvider.GITHUB,
                        status=ConnectorSyncStatus.SUCCESS,
                        items_fetched=i,
                    )
                )
            assert len(await configs.list_for_tenant(tenant.id)) == 3
            assert len(await configs.list_for_tenant(tenant.id, limit=2)) == 2
            assert len(await sync.list_for_tenant(tenant.id)) == 3
            assert len(await sync.list_for_tenant(tenant.id, limit=2)) == 2
        finally:
            await tenant_repo.delete(tenant.id)


class TestConnectorAuditListLimit:
    async def test_audit_bounded_with_provider_filter(self, db):
        tenant_repo, tenant = await _tenant(db)
        repo = PostgreSQLConnectorCredentialRepository(db)
        try:
            for i in range(3):
                await repo.create_audit(
                    ConnectorCredentialAudit(
                        id=_unique("audit"),
                        tenant_id=tenant.id,
                        provider=ConnectorProvider.GITHUB,
                        operation="create",
                        actor_user_id=f"user-{i}",
                    )
                )
            rows = await repo.list_audit_for_tenant(tenant.id)
            assert len(rows) == 3

            limited = await repo.list_audit_for_tenant(tenant.id, limit=2)
            assert len(limited) == 2
            assert limited[0].created_at >= limited[1].created_at

            filtered = await repo.list_audit_for_tenant(tenant.id, provider="github", limit=2)
            assert len(filtered) == 2
        finally:
            await tenant_repo.delete(tenant.id)


class TestAgentRunRecordsLimit:
    async def test_bounded_newest_first(self, db):
        tenant_repo, tenant = await _tenant(db)
        repo = PostgreSQLObservabilityRepository(db)
        try:
            for i in range(3):
                await repo.create_agent_run_record(
                    AgentRunRecord(
                        id=_unique("run"),
                        tenant_id=tenant.id,
                        principal_id="u-1",
                        goal=f"Goal {i}",
                        status="succeeded",
                        created_at=datetime.now(timezone.utc),
                        steps=[
                            AgentRunRecordStep(
                                sequence=0,
                                skill_id="sk-1",
                                skill_name="Echo",
                                status="succeeded",
                            )
                        ],
                    )
                )
            rows = await repo.list_agent_run_records(tenant.id, hours=1)
            assert len(rows) == 3

            limited = await repo.list_agent_run_records(tenant.id, hours=1, limit=2)
            assert len(limited) == 2
            assert limited[0].created_at >= limited[1].created_at
        finally:
            await tenant_repo.delete(tenant.id)


class TestCapabilitiesListLimit:
    async def test_platform_and_tenant_lists_bounded(self, db):
        tenant_repo, tenant = await _tenant(db)
        repo = PostgreSQLCapabilityRepository(db)
        try:
            await repo.set_platform_capability("agent_execution", True)
            await repo.set_platform_capability("connector_sync", False)
            await repo.set_tenant_capability(tenant.id, "agent_execution", True)
            await repo.set_tenant_capability(tenant.id, "connector_sync", False)

            assert len(await repo.list_platform_capabilities()) == 2
            assert len(await repo.list_platform_capabilities(limit=1)) == 1
            assert len(await repo.list_tenant_capabilities(tenant.id)) == 2
            assert len(await repo.list_tenant_capabilities(tenant.id, limit=1)) == 1
        finally:
            await tenant_repo.delete(tenant.id)


class TestSkillExecutionAgentRunLimit:
    async def test_bounded_by_agent_run(self, db):
        tenant_repo, tenant = await _tenant(db)
        skills = PostgreSQLSkillRepository(db)
        skill = await skills.create(
            Skill(id=_unique("skill"), tenant_id=tenant.id, name="S", purpose="P")
        )
        repo = PostgreSQLSkillExecutionRecordRepository(db)
        run_id = _unique("run")
        try:
            for i in range(3):
                await repo.create_record(
                    SkillExecutionRecord(
                        id=_unique("rec"),
                        tenant_id=tenant.id,
                        skill_id=skill.id,
                        skill_version="1.0",
                        principal_id="u-1",
                        agent_run_id=run_id,
                        status=SkillExecutionStatus.SUCCEEDED,
                        created_at=datetime.now(timezone.utc) + timedelta(seconds=i),
                    )
                )
            rows = await repo.list_for_agent_run(run_id, tenant.id)
            assert len(rows) == 3

            limited = await repo.list_for_agent_run(run_id, tenant.id, limit=2)
            assert len(limited) == 2
        finally:
            await tenant_repo.delete(tenant.id)
