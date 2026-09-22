"""Integration tests for the PostgreSQL repository contract.

These tests exercise the concrete PostgreSQL repositories through the
service-facing Protocol method names against a real PostgreSQL database.
They verify the repository contract end-to-end instead of relying on mocks.
"""

import os
import uuid
from pathlib import Path

import pytest

from arc.db.connection import ArcDatabase, NotFoundError
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.services.domain import ServiceFactory

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"it-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def db():
    """Connect to PostgreSQL and ensure the tenancy schema exists."""
    database = ArcDatabase(DATABASE_URL)
    await database.connect()
    async with database._connection_pool.acquire() as conn:
        schema = SCHEMA_PATH.read_text()
        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)
    yield database
    await database.disconnect()


@pytest.fixture
async def repositories(db):
    """Create the three concrete repository instances over one database."""
    tenant_repo = PostgreSQLTenantRepository(db)
    user_repo = PostgreSQLUserRepository(db)
    membership_repo = PostgreSQLMembershipRepository(db)
    return tenant_repo, user_repo, membership_repo


@pytest.fixture
async def seeded(repositories):
    """Create a tenant, a user, and a MEMBER membership; clean up afterwards."""
    tenant_repo, user_repo, membership_repo = repositories

    tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Integration Tenant"))
    user = await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="it-user")
    )
    membership = await membership_repo.create(
        Membership(
            id=_unique("membership"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )

    yield tenant, user, membership

    await membership_repo.delete(membership.id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant.id)


class TestTenantRepositoryContract:
    """Verify the TenantRepository Protocol methods against PostgreSQL."""

    async def test_create_get_exists_delete(self, db):
        repo = PostgreSQLTenantRepository(db)
        tenant_id = _unique("tenant")
        await repo.create(Tenant(id=tenant_id, name="Contract Tenant"))

        fetched = await repo.get_by_id(tenant_id)
        assert fetched.id == tenant_id
        assert fetched.name == "Contract Tenant"

        assert await repo.exists(tenant_id) is True
        assert await repo.exists("missing-tenant") is False

        await repo.delete(tenant_id)
        assert await repo.exists(tenant_id) is False


class TestUserRepositoryContract:
    """Verify the UserRepository Protocol methods against PostgreSQL."""

    async def test_create_get_exists_delete(self, db):
        repo = PostgreSQLUserRepository(db)
        user_id = _unique("user")
        email = f"{uuid.uuid4().hex}@example.com"
        await repo.create(User(id=user_id, email=email, username="contract-user"))

        fetched = await repo.get_by_id(user_id)
        assert fetched.id == user_id
        assert fetched.email == email

        by_email = await repo.get_by_email(email)
        assert by_email.id == user_id

        assert await repo.exists(user_id) is True
        assert await repo.exists("missing-user") is False

        await repo.delete(user_id)
        assert await repo.exists(user_id) is False


class TestMembershipRepositoryContract:
    """Verify the MembershipRepository Protocol methods against PostgreSQL."""

    async def test_create_get_exists_delete(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, user, membership = seeded

        fetched = await membership_repo.get_by_user_and_tenant(user.id, tenant.id)
        assert fetched.id == membership.id
        assert fetched.role == UserRole.MEMBER

        assert await membership_repo.exists(user.id, tenant.id) is True
        assert await membership_repo.exists(user.id, "missing-tenant") is False

        tenants = await membership_repo.get_tenants_for_user(user.id)
        assert any(t.id == tenant.id for t in tenants)

        users = await membership_repo.get_users_for_tenant(tenant.id)
        assert any(u.id == user.id for u in users)

        memberships = await membership_repo.get_memberships_for_user(user.id)
        assert any(m.id == membership.id for m in memberships)

        tenant_memberships = await membership_repo.get_memberships_for_tenant(tenant.id)
        assert any(m.id == membership.id for m in tenant_memberships)

    async def test_user_repo_get_by_tenant(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, user, _ = seeded

        users = await user_repo.get_by_tenant(tenant.id)
        assert any(u.id == user.id for u in users)


class TestTenantContextServiceWithPostgres:
    """End-to-end tenant-context boundary against real PostgreSQL."""

    async def test_valid_membership_creates_trusted_context(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, user, _ = seeded
        services = ServiceFactory.create_domain_services([tenant_repo, user_repo, membership_repo])
        context_service = services["tenant_context_service"]

        context = await context_service.create_tenant_context(tenant.id, user.id)

        assert context.tenant_id == tenant.id
        assert context.tenant_name == tenant.name
        assert context.user_id == user.id
        assert context.role == UserRole.MEMBER

    async def test_role_is_derived_from_persisted_membership(self, repositories):
        tenant_repo, user_repo, membership_repo = repositories

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Role Tenant"))
        user = await user_repo.create(
            User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="role-user")
        )
        membership = await membership_repo.create(
            Membership(
                id=_unique("membership"),
                user_id=user.id,
                tenant_id=tenant.id,
                role=UserRole.VIEWER,
            )
        )
        try:
            services = ServiceFactory.create_domain_services(
                [tenant_repo, user_repo, membership_repo]
            )
            context_service = services["tenant_context_service"]

            context = await context_service.create_tenant_context(tenant.id, user.id)

            assert context.role == UserRole.VIEWER
        finally:
            await membership_repo.delete(membership.id)
            await user_repo.delete(user.id)
            await tenant_repo.delete(tenant.id)

    async def test_cross_tenant_access_is_rejected(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        _, user, _ = seeded
        other_tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Other Tenant"))
        try:
            services = ServiceFactory.create_domain_services(
                [tenant_repo, user_repo, membership_repo]
            )
            context_service = services["tenant_context_service"]

            with pytest.raises(NotFoundError):
                await context_service.create_tenant_context(other_tenant.id, user.id)
        finally:
            await tenant_repo.delete(other_tenant.id)

    async def test_missing_membership_is_rejected(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, _, _ = seeded
        orphan = await user_repo.create(
            User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="orphan")
        )
        try:
            services = ServiceFactory.create_domain_services(
                [tenant_repo, user_repo, membership_repo]
            )
            context_service = services["tenant_context_service"]

            with pytest.raises(NotFoundError):
                await context_service.create_tenant_context(tenant.id, orphan.id)
        finally:
            await user_repo.delete(orphan.id)

    async def test_validate_context_with_postgres(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, user, _ = seeded
        services = ServiceFactory.create_domain_services([tenant_repo, user_repo, membership_repo])
        context_service = services["tenant_context_service"]

        valid_context = TenantContext(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        assert await context_service.validate_context(valid_context) is True

        role_mismatch = TenantContext(
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            user_id=user.id,
            role=UserRole.OWNER,
        )
        assert await context_service.validate_context(role_mismatch) is False

    async def test_validate_context_rejects_missing_membership(self, repositories, seeded):
        tenant_repo, user_repo, membership_repo = repositories
        tenant, _, _ = seeded
        orphan = await user_repo.create(
            User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="orphan2")
        )
        try:
            services = ServiceFactory.create_domain_services(
                [tenant_repo, user_repo, membership_repo]
            )
            context_service = services["tenant_context_service"]

            context = TenantContext(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                user_id=orphan.id,
                role=UserRole.MEMBER,
            )
            assert await context_service.validate_context(context) is False
        finally:
            await user_repo.delete(orphan.id)
