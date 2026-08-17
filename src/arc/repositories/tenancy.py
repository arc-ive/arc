"""PostgreSQL implementation of tenancy repositories."""

from typing import List

from arc.db.connection import ArcDatabase, DatabaseError, DuplicateKeyError, NotFoundError
from arc.domain.models import Tenant, User, Membership, UserRole, TenantContext
from arc.repositories import TenantRepository, UserRepository, MembershipRepository


class PostgreSQLTenancyRepository:
    """PostgreSQL implementation of tenancy repositories."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        return await self.db.create_tenant(tenant)

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        return await self.db.get_tenant(tenant_id)

    async def tenant_exists(self, tenant_id: str) -> bool:
        """Check if tenant exists."""
        try:
            await self.db.get_tenant(tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete_tenant(self, tenant_id: str) -> None:
        """Delete tenant."""
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        return await self.db.create_user(user)

    async def get_user(self, user_id: str) -> User:
        """Get user by ID."""
        return await self.db.get_user(user_id)

    async def get_user_by_email(self, email: str) -> User:
        """Get user by email."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, username, status, created_at, updated_at FROM users WHERE email = $1",
                email
            )
            if not row:
                raise NotFoundError(f"User with email {email} not found")
            return User(
                id=row['id'],
                email=row['email'],
                username=row['username'],
                status=row['status'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )

    async def user_exists(self, user_id: str) -> bool:
        """Check if user exists."""
        try:
            await self.db.get_user(user_id)
            return True
        except NotFoundError:
            return False

    async def delete_user(self, user_id: str) -> None:
        """Delete user."""
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)

    async def create_membership(self, membership: Membership) -> Membership:
        """Create a new membership."""
        return await self.db.create_membership(membership)

    async def get_membership(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        return await self.db.get_membership(user_id, tenant_id)

    async def membership_exists(self, user_id: str, tenant_id: str) -> bool:
        """Check if membership exists."""
        try:
            await self.db.get_membership(user_id, tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete_membership(self, membership_id: str) -> None:
        """Delete membership."""
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM memberships WHERE id = $1", membership_id)

    async def get_tenants_for_user(self, user_id: str) -> List[Tenant]:
        """Get all tenants for a user."""
        return await self.db.get_tenants_for_user(user_id)

    async def get_users_for_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        return await self.db.get_users_for_tenant(tenant_id)

    async def get_memberships_for_user(self, user_id: str) -> List[Membership]:
        """Get all memberships for a user."""
        return await self.db.get_memberships_for_user(user_id)

    async def get_memberships_for_tenant(self, tenant_id: str) -> List[Membership]:
        """Get all memberships for a tenant."""
        return await self.db.get_memberships_for_tenant(tenant_id)


# Export types for backward compatibility
__all__ = [
    'TenantRepository',
    'UserRepository',
    'MembershipRepository',
    'PostgreSQLTenancyRepository',
]