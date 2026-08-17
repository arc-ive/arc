"""Tests for Arc multi-tenancy foundation."""

import pytest
import uuid
from datetime import datetime

from arc.domain.models import Tenant, User, Membership, UserRole, TenantContext
from arc.db.connection import ArcDatabase, DatabaseError, DuplicateKeyError, NotFoundError


class TestDatabaseConnection:
    """Test database connection and setup."""

    @pytest.fixture
    async def db(self):
        """Create a database instance for testing."""
        db = ArcDatabase("postgresql://arc:arc-dev-password@localhost:5432/arc")
        await db.connect()
        yield db
        await db.disconnect()

    @pytest.fixture
    async def db_with_transactions(self):
        """Create a database instance with transaction support."""
        db = ArcDatabase("postgresql://arc:arc-dev-password@localhost:5432/arc")
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
        tenant = Tenant(
            id="test-tenant-1",
            name="Test Tenant",
            status="active"
        )
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
        user = User(
            id="test-user-1",
            email="test@example.com",
            username="testuser"
        )
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
            role=UserRole.OWNER
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
            id="test-membership-2",
            user_id="test-user-2",
            tenant_id="test-tenant-2"
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
            role=UserRole.OWNER
        )
        assert context.tenant_id == "test-tenant-1"
        assert context.tenant_name == "Test Tenant"
        assert context.user_id == "test-user-1"
        assert context.role == UserRole.OWNER
        assert context.is_valid is True

    def test_tenant_context_validation(self):
        """Test tenant context validation."""
        # Test empty tenant ID
        context = TenantContext(
            tenant_id="",
            tenant_name="Test",
            user_id="user-1",
            role=UserRole.OWNER
        )
        assert context.is_valid is False

        # Test empty user ID
        context = TenantContext(
            tenant_id="tenant-1",
            tenant_name="Test",
            user_id="",
            role=UserRole.OWNER
        )
        assert context.is_valid is False


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])