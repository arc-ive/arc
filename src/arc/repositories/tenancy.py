"""PostgreSQL implementations of tenancy repositories.

Each class implements exactly one repository Protocol from
``arc.repositories``. They are split into three classes because the three
protocols define colliding generic method names (``create``, ``get_by_id``,
``exists``, ``delete``) that a single shared class cannot satisfy cleanly.
"""

from typing import List

from arc.db.connection import ArcDatabase, NotFoundError
from arc.domain.models import Membership, Tenant, User


class PostgreSQLTenantRepository:
    """PostgreSQL implementation of the TenantRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        return await self.db.create_tenant(tenant)

    async def get_by_id(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        return await self.db.get_tenant(tenant_id)

    async def exists(self, tenant_id: str) -> bool:
        """Check if tenant exists."""
        try:
            await self.db.get_tenant(tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete(self, tenant_id: str) -> None:
        """Delete tenant."""
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)


class PostgreSQLUserRepository:
    """PostgreSQL implementation of the UserRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, user: User) -> User:
        """Create a new user."""
        return await self.db.create_user(user)

    async def get_by_id(self, user_id: str) -> User:
        """Get user by ID."""
        return await self.db.get_user(user_id)

    async def get_by_email(self, email: str) -> User:
        """Get user by email."""
        async with self.db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, username, status, created_at, updated_at "
                "FROM users WHERE email = $1",
                email,
            )
            if not row:
                raise NotFoundError(f"User with email {email} not found")
            return User(
                id=row["id"],
                email=row["email"],
                username=row["username"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def get_by_tenant(self, tenant_id: str) -> List[User]:
        """Get all users for a tenant."""
        return await self.db.get_users_for_tenant(tenant_id)

    async def exists(self, user_id: str) -> bool:
        """Check if user exists."""
        try:
            await self.db.get_user(user_id)
            return True
        except NotFoundError:
            return False

    async def delete(self, user_id: str) -> None:
        """Delete user."""
        async with self.db.transaction() as conn:
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)


class PostgreSQLMembershipRepository:
    """PostgreSQL implementation of the MembershipRepository contract."""

    def __init__(self, db: ArcDatabase):
        self.db = db

    async def create(self, membership: Membership) -> Membership:
        """Create a new membership."""
        return await self.db.create_membership(membership)

    async def get_by_user_and_tenant(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        return await self.db.get_membership(user_id, tenant_id)

    async def exists(self, user_id: str, tenant_id: str) -> bool:
        """Check if membership exists."""
        try:
            await self.db.get_membership(user_id, tenant_id)
            return True
        except NotFoundError:
            return False

    async def delete(self, membership_id: str) -> None:
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


__all__ = [
    "PostgreSQLTenantRepository",
    "PostgreSQLUserRepository",
    "PostgreSQLMembershipRepository",
]
