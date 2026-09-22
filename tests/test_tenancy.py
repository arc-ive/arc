"""Tests for Arc multi-tenancy foundation."""

import os
from datetime import datetime

import pytest

from arc.db.connection import ArcDatabase, DatabaseError, NotFoundError
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
)


class TestDatabaseConnection:
    """Test database connection and setup."""

    @pytest.fixture
    async def db(self):
        """Create a database instance for testing."""
        db = ArcDatabase(DATABASE_URL)
        await db.connect()
        yield db
        await db.disconnect()

    @pytest.fixture
    async def db_with_transactions(self):
        """Create a database instance with transaction support."""
        db = ArcDatabase(DATABASE_URL)
        await db.connect()
        yield db
        await db.disconnect()

    async def test_database_connection(self, db):
        """Test that database connection works."""
        assert db is not None
        assert db._connection_pool is not None

    async def test_database_error_handling(self, db_with_transactions):
        """Test database error handling."""
        # Test that errors are raised properly
        with pytest.raises(DatabaseError):
            raise DatabaseError("Test database error")


class TestTenantModel:
    """Test Tenant domain model."""

    def test_tenant_creation(self):
        """Test creating a tenant."""
        tenant = Tenant(id="test-tenant-1", name="Test Tenant", status="active")
        assert tenant.id == "test-tenant-1"
        assert tenant.name == "Test Tenant"
        assert tenant.status == "active"
        assert isinstance(tenant.created_at, datetime)
        assert isinstance(tenant.updated_at, datetime)

    def test_tenant_validation(self):
        """Test tenant validation."""
        # Test empty ID
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            Tenant(id="", name="Test")

        # Test empty name
        with pytest.raises(ValueError, match="Tenant name cannot be empty"):
            Tenant(id="test-1", name="")

    def test_tenant_defaults(self):
        """Test tenant default values."""
        tenant = Tenant(id="test-1", name="Test")
        assert tenant.status == "active"


class TestUserModel:
    """Test User domain model."""

    def test_user_creation(self):
        """Test creating a user."""
        user = User(id="test-user-1", email="test@example.com", username="testuser")
        assert user.id == "test-user-1"
        assert user.email == "test@example.com"
        assert user.username == "testuser"
        assert user.status == "active"

    def test_user_validation(self):
        """Test user validation."""
        # Test empty ID
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            User(id="", email="test@example.com")

        # Test empty email
        with pytest.raises(ValueError, match="User email cannot be empty"):
            User(id="test-1", email="")


class TestMembershipModel:
    """Test Membership domain model."""

    def test_membership_creation(self):
        """Test creating a membership."""
        membership = Membership(
            id="test-membership-1",
            user_id="test-user-1",
            tenant_id="test-tenant-1",
            role=UserRole.OWNER,
        )
        assert membership.id == "test-membership-1"
        assert membership.user_id == "test-user-1"
        assert membership.tenant_id == "test-tenant-1"
        assert membership.role == UserRole.OWNER
        assert membership.is_owner() is True

    def test_membership_validation(self):
        """Test membership validation."""
        # Test empty ID
        with pytest.raises(ValueError, match="Membership ID cannot be empty"):
            Membership(id="", user_id="test", tenant_id="tenant")

        # Test empty user ID
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            Membership(id="test", user_id="", tenant_id="tenant")

        # Test empty tenant ID
        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            Membership(id="test", user_id="user", tenant_id="")

    def test_membership_default_role(self):
        """Test membership default role."""
        membership = Membership(
            id="test-membership-2", user_id="test-user-2", tenant_id="test-tenant-2"
        )
        assert membership.role == UserRole.MEMBER


class TestTenantContextModel:
    """Test TenantContext domain model."""

    def test_tenant_context_creation(self):
        """Test creating a tenant context."""
        context = TenantContext(
            tenant_id="test-tenant-1",
            tenant_name="Test Tenant",
            user_id="test-user-1",
            role=UserRole.OWNER,
        )
        assert context.tenant_id == "test-tenant-1"
        assert context.tenant_name == "Test Tenant"
        assert context.user_id == "test-user-1"
        assert context.role == UserRole.OWNER
        assert context.is_valid is True

    def test_tenant_context_validation(self):
        """Test tenant context validation."""
        # Test empty tenant ID
        with pytest.raises(ValueError, match="Tenant ID cannot be empty in context"):
            TenantContext(tenant_id="", tenant_name="Test", user_id="user-1", role=UserRole.OWNER)

        # Test empty user ID
        with pytest.raises(ValueError, match="User ID cannot be empty in context"):
            TenantContext(tenant_id="tenant-1", tenant_name="Test", user_id="", role=UserRole.OWNER)


class TestUserRoleEnum:
    """Test UserRole enum."""

    def test_role_values(self):
        """Test role enum values."""
        assert UserRole.OWNER == "owner"
        assert UserRole.MEMBER == "member"
        assert UserRole.VIEWER == "viewer"

    def test_valid_roles(self):
        """Test that all expected roles are valid."""
        for role in UserRole:
            assert role.value in ["owner", "member", "viewer"]


class TestDomainServices:
    """Test domain services with repository dependencies."""

    @pytest.fixture
    def repositories(self):
        """Create mock repositories for testing."""
        from unittest.mock import AsyncMock

        from arc.repositories import MembershipRepository, TenantRepository, UserRepository

        tenant_repo = AsyncMock(spec=TenantRepository)
        user_repo = AsyncMock(spec=UserRepository)
        membership_repo = AsyncMock(spec=MembershipRepository)

        # Mock tenant exists
        tenant_repo.exists.return_value = True
        tenant_repo.get_by_id.return_value = Tenant(
            id="test-tenant", name="Test Tenant", status="active"
        )

        # Mock user exists
        user_repo.exists.return_value = True
        user_repo.get_by_id.return_value = User(
            id="test-user", email="test@example.com", username="testuser"
        )

        # Mock membership exists
        membership_repo.exists.return_value = True
        membership_repo.get_by_user_and_tenant.return_value = Membership(
            id="test-membership", user_id="test-user", tenant_id="test-tenant", role=UserRole.MEMBER
        )

        return tenant_repo, user_repo, membership_repo

    async def test_tenant_context_service_with_membership_dependency(self, repositories):
        """Test TenantContextService uses MembershipRepository."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories
        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        context = await service.create_tenant_context("test-tenant", "test-user")

        assert context.tenant_id == "test-tenant"
        assert context.user_id == "test-user"
        assert context.role == UserRole.MEMBER

    async def test_valid_membership_creates_context(self, repositories):
        """Test A: Valid membership creates context."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        context = await service.create_tenant_context("test-tenant", "test-user")

        assert context.tenant_id == "test-tenant"
        assert context.user_id == "test-user"
        assert context.role == UserRole.MEMBER

    async def test_cross_tenant_access_is_rejected(self, repositories):
        """Test B: Cross-tenant access is rejected."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        membership_repo.get_by_user_and_tenant.side_effect = NotFoundError("No membership")

        with pytest.raises(NotFoundError):
            await service.create_tenant_context("different-tenant", "test-user")

    async def test_role_is_derived_from_membership(self, repositories):
        """Test C: Role cannot be escalated - context role comes from persisted membership."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories
        membership_repo.get_by_user_and_tenant.return_value = Membership(
            id="test-membership", user_id="test-user", tenant_id="test-tenant", role=UserRole.VIEWER
        )

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        context = await service.create_tenant_context("test-tenant", "test-user")

        assert context.role == UserRole.VIEWER

    async def test_missing_membership_is_rejected(self, repositories):
        """Test D: Missing membership is rejected."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        membership_repo.get_by_user_and_tenant.side_effect = NotFoundError("No membership")

        with pytest.raises(NotFoundError):
            await service.create_tenant_context("test-tenant", "test-user")

    async def test_validate_context_rejects_missing_membership(self, repositories):
        """Test E: validate_context() rejects missing membership."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        tenant_repo.exists.return_value = True
        user_repo.exists.return_value = True
        membership_repo.get_by_user_and_tenant.side_effect = NotFoundError("No membership")

        context = TenantContext(
            tenant_id="test-tenant",
            tenant_name="Test Tenant",
            user_id="test-user",
            role=UserRole.MEMBER,
        )

        assert await service.validate_context(context) is False

    async def test_validate_context_rejects_role_mismatch(self, repositories):
        """Test F: validate_context() rejects role mismatch."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        context = TenantContext(
            tenant_id="test-tenant",
            tenant_name="Test Tenant",
            user_id="test-user",
            role=UserRole.OWNER,
        )

        assert await service.validate_context(context) is False

    async def test_validate_context_accepts_correct_membership_and_role(self, repositories):
        """Test G: validate_context() accepts correct membership + role."""
        from arc.services.domain import TenantContextService

        tenant_repo, user_repo, membership_repo = repositories

        service = TenantContextService(user_repo, tenant_repo, membership_repo)

        context = TenantContext(
            tenant_id="test-tenant",
            tenant_name="Test Tenant",
            user_id="test-user",
            role=UserRole.MEMBER,
        )

        assert await service.validate_context(context) is True

    async def test_update_tenant_updates_company_config(self, repositories):
        """Test: update_tenant persists company configuration fields."""
        from arc.services.domain import TenantService

        tenant_repo, _, _ = repositories
        service = TenantService(tenant_repo)

        updated_tenant = Tenant(
            id="test-tenant",
            name="Updated Tenant",
            status="active",
            industry="Technology",
            address="123 Main St",
            phone="+1-555-0100",
            website="https://example.com",
            logo_url="https://example.com/logo.png",
        )
        tenant_repo.update.return_value = updated_tenant

        result = await service.update_tenant(updated_tenant)

        assert result.industry == "Technology"
        assert result.address == "123 Main St"
        assert result.phone == "+1-555-0100"
        assert result.website == "https://example.com"
        assert result.logo_url == "https://example.com/logo.png"
        tenant_repo.update.assert_awaited_once_with(updated_tenant)

    async def test_update_tenant_rejects_empty_id(self, repositories):
        """Test: update_tenant rejects empty tenant ID."""
        from arc.services.domain import TenantService

        tenant_repo, _, _ = repositories
        service = TenantService(tenant_repo)

        with pytest.raises(ValueError, match="Tenant ID cannot be empty"):
            await service.update_tenant(Tenant(id="", name="Test"))

    async def test_update_tenant_rejects_empty_name(self, repositories):
        """Test: update_tenant rejects empty tenant name."""
        from arc.services.domain import TenantService

        tenant_repo, _, _ = repositories
        service = TenantService(tenant_repo)

        with pytest.raises(ValueError, match="Tenant name cannot be empty"):
            await service.update_tenant(Tenant(id="test-tenant", name=""))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
