"""PostgreSQL connection manager for Arc domain."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

from arc.domain.models import Membership, Session, Tenant, User, UserRole


class DatabaseError(Exception):
    """Base exception for database operations."""

    pass


class DuplicateKeyError(DatabaseError):
    """Raised when a unique constraint is violated."""

    pass


class NotFoundError(DatabaseError):
    """Raised when a required record is not found."""

    pass


class ArcDatabase:
    """Database manager for Arc domain models."""

    def __init__(
        self,
        database_url: str = ("postgresql://arc:arc-dev-password@localhost:5432/arc"),
    ):
        self.database_url = database_url
        self._connection_pool = None

    async def connect(self) -> None:
        """Establish connection pool."""
        self._connection_pool = await asyncpg.create_pool(self.database_url)

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._connection_pool:
            await self._connection_pool.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Context manager for database transactions."""
        if not self._connection_pool:
            raise DatabaseError("Database not connected")

        async with self._connection_pool.acquire() as connection:
            async with connection.transaction():
                yield connection

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        """Create a new tenant."""
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO tenants (id, name, status, industry, address,
                        phone, website, logo_url, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    tenant.id,
                    tenant.name,
                    tenant.status,
                    tenant.industry,
                    tenant.address,
                    tenant.phone,
                    tenant.website,
                    tenant.logo_url,
                    tenant.created_at,
                    tenant.updated_at,
                )
                return tenant
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(f"Tenant with id {tenant.id} already exists") from e
            except Exception as e:
                raise DatabaseError(f"Failed to create tenant: {e}") from e

    async def create_tenant_with_owner(self, tenant: Tenant, membership: Membership) -> Tenant:
        """Create a new tenant with an initial OWNER membership atomically.

        Both the tenant row and the membership row are created within a
        single database transaction. If either operation fails, both
        are rolled back, preventing partial state.
        """
        async with self.transaction() as conn:
            try:
                # Create tenant
                await conn.execute(
                    """
                    INSERT INTO tenants (id, name, status, industry, address,
                        phone, website, logo_url, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    tenant.id,
                    tenant.name,
                    tenant.status,
                    tenant.industry,
                    tenant.address,
                    tenant.phone,
                    tenant.website,
                    tenant.logo_url,
                    tenant.created_at,
                    tenant.updated_at,
                )
                # Create membership in same transaction
                await conn.execute(
                    """
                    INSERT INTO memberships (
                        id, user_id, tenant_id, role, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    membership.id,
                    membership.user_id,
                    membership.tenant_id,
                    membership.role.value,
                    membership.created_at,
                    membership.updated_at,
                )
                return tenant
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"Tenant with id {tenant.id} already exists "
                    f"or user {membership.user_id} already belongs to tenant {membership.tenant_id}"
                ) from e
            except Exception as e:
                raise DatabaseError(f"Failed to create tenant with owner: {e}") from e

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """Get tenant by ID."""
        async with self._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, status, industry, address, phone, website, "
                "logo_url, created_at, updated_at FROM tenants WHERE id = $1",
                tenant_id,
            )
            if not row:
                raise NotFoundError(f"Tenant with id {tenant_id} not found")
            return Tenant(
                id=row["id"],
                name=row["name"],
                status=row["status"],
                industry=row["industry"],
                address=row["address"],
                phone=row["phone"],
                website=row["website"],
                logo_url=row["logo_url"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def update_tenant(self, tenant: Tenant) -> Tenant:
        """Update tenant company configuration.

        The SELECT re-reads within the same transaction connection so it
        sees the updated row before the transaction commits.  This avoids
        the stale-read bug where ``get_tenant`` acquires a different
        connection from the pool and misses uncommitted writes.
        """
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    UPDATE tenants
                    SET name = $2, status = $3, industry = $4, address = $5,
                        phone = $6, website = $7, logo_url = $8, updated_at = $9
                    WHERE id = $1
                    """,
                    tenant.id,
                    tenant.name,
                    tenant.status,
                    tenant.industry,
                    tenant.address,
                    tenant.phone,
                    tenant.website,
                    tenant.logo_url,
                    tenant.updated_at,
                )
                row = await conn.fetchrow(
                    "SELECT id, name, status, industry, address, phone, "
                    "website, logo_url, created_at, updated_at "
                    "FROM tenants WHERE id = $1",
                    tenant.id,
                )
                if not row:
                    raise NotFoundError(f"Tenant with id {tenant.id} not found")
                return Tenant(
                    id=row["id"],
                    name=row["name"],
                    status=row["status"],
                    industry=row["industry"],
                    address=row["address"],
                    phone=row["phone"],
                    website=row["website"],
                    logo_url=row["logo_url"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            except Exception as e:
                raise DatabaseError(f"Failed to update tenant: {e}") from e

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO users (
                        id, email, username, status, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user.id,
                    user.email,
                    user.username,
                    user.status,
                    user.created_at,
                    user.updated_at,
                )
                return user
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(f"User with email {user.email} already exists") from e
            except Exception as e:
                raise DatabaseError(f"Failed to create user: {e}") from e

    async def get_user(self, user_id: str) -> User:
        """Get user by ID."""
        async with self._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, username, status, created_at, "
                "updated_at FROM users WHERE id = $1",
                user_id,
            )
            if not row:
                raise NotFoundError(f"User with id {user_id} not found")
            return User(
                id=row["id"],
                email=row["email"],
                username=row["username"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def create_membership(self, membership: Membership) -> Membership:
        """Create a new membership (user-tenant relationship)."""
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO memberships (
                        id, user_id, tenant_id, role, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    membership.id,
                    membership.user_id,
                    membership.tenant_id,
                    membership.role.value,
                    membership.created_at,
                    membership.updated_at,
                )
                return membership
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(
                    f"User {membership.user_id} already belongs to tenant {membership.tenant_id}"
                ) from e
            except Exception as e:
                raise DatabaseError(f"Failed to create membership: {e}") from e

    async def get_membership(self, user_id: str, tenant_id: str) -> Membership:
        """Get membership by user and tenant IDs."""
        async with self._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, user_id, tenant_id, role, created_at, "
                "updated_at FROM memberships "
                "WHERE user_id = $1 AND tenant_id = $2",
                user_id,
                tenant_id,
            )
            if not row:
                raise NotFoundError(
                    f"Membership not found for user {user_id} in tenant {tenant_id}"
                )
            return Membership(
                id=row["id"],
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                role=UserRole(row["role"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def get_tenants_for_user(self, user_id: str) -> list[Tenant]:
        """Get all tenants for a user."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.id, t.name, t.status, t.created_at, t.updated_at
                FROM tenants t
                JOIN memberships m ON t.id = m.tenant_id
                WHERE m.user_id = $1
                """,
                user_id,
            )
            tenants = []
            for row in rows:
                tenants.append(
                    Tenant(
                        id=row["id"],
                        name=row["name"],
                        status=row["status"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return tenants

    async def get_users_for_tenant(self, tenant_id: str) -> list[User]:
        """Get all users for a tenant."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.id, u.email, u.username, u.status,
                       u.created_at, u.updated_at
                FROM users u
                JOIN memberships m ON u.id = m.user_id
                WHERE m.tenant_id = $1
                """,
                tenant_id,
            )
            users = []
            for row in rows:
                users.append(
                    User(
                        id=row["id"],
                        email=row["email"],
                        username=row["username"],
                        status=row["status"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return users

    async def get_memberships_for_user(self, user_id: str) -> list[Membership]:
        """Get all memberships for a user."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, tenant_id, role, created_at, updated_at
                FROM memberships
                WHERE user_id = $1
                """,
                user_id,
            )
            memberships = []
            for row in rows:
                memberships.append(
                    Membership(
                        id=row["id"],
                        user_id=row["user_id"],
                        tenant_id=row["tenant_id"],
                        role=UserRole(row["role"]),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return memberships

    async def get_memberships_for_tenant(self, tenant_id: str) -> list[Membership]:
        """Get all memberships for a tenant."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, tenant_id, role, created_at, updated_at
                FROM memberships
                WHERE tenant_id = $1
                """,
                tenant_id,
            )
            memberships = []
            for row in rows:
                memberships.append(
                    Membership(
                        id=row["id"],
                        user_id=row["user_id"],
                        tenant_id=row["tenant_id"],
                        role=UserRole(row["role"]),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return memberships

    async def get_user_by_provider(self, auth_provider: str, provider_subject: str) -> User | None:
        """Look up a user by their external identity provider and subject.

        Returns None if no matching user exists (does NOT auto-provision).
        """
        async with self._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, email, username, status, auth_provider, provider_subject,
                       display_name, avatar_url, created_at, updated_at
                FROM users
                WHERE auth_provider = $1 AND provider_subject = $2
                """,
                auth_provider,
                provider_subject,
            )
            if not row:
                return None
            return User(
                id=row["id"],
                email=row["email"],
                username=row["username"],
                status=row["status"],
                auth_provider=row["auth_provider"],
                provider_subject=row["provider_subject"],
                display_name=row["display_name"],
                avatar_url=row["avatar_url"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def link_user_provider(
        self, user_id: str, auth_provider: str, provider_subject: str,
        display_name: str | None = None, avatar_url: str | None = None,
    ) -> User:
        """Link an existing user to an external identity provider.

        This binds the durable provider_subject to the Arc user. The user
        MUST already exist; this does NOT create users. Email is NOT
        updated from the provider to prevent account-takeover via email
        reassignment.
        """
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    UPDATE users
                    SET auth_provider = $2, provider_subject = $3,
                        display_name = COALESCE($4, display_name),
                        avatar_url = COALESCE($5, avatar_url),
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    user_id, auth_provider, provider_subject, display_name, avatar_url,
                )
                row = await conn.fetchrow(
                    """
                    SELECT id, email, username, status, auth_provider, provider_subject,
                           display_name, avatar_url, created_at, updated_at
                    FROM users WHERE id = $1
                    """,
                    user_id,
                )
                if not row:
                    raise NotFoundError(f"User with id {user_id} not found")
                return User(
                    id=row["id"],
                    email=row["email"],
                    username=row["username"],
                    status=row["status"],
                    auth_provider=row["auth_provider"],
                    provider_subject=row["provider_subject"],
                    display_name=row["display_name"],
                    avatar_url=row["avatar_url"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            except Exception as e:
                raise DatabaseError(f"Failed to link user provider: {e}") from e

    async def create_session(self, session: Session) -> Session:
        """Create a new server-side session."""
        async with self.transaction() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO sessions (id, user_id, csrf_token, created_at, expires_at, user_agent, ip_address)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    session.id,
                    session.user_id,
                    session.csrf_token,
                    session.created_at,
                    session.expires_at,
                    session.user_agent,
                    session.ip_address,
                )
                return session
            except asyncpg.UniqueViolationError as e:
                raise DuplicateKeyError(f"Session with id {session.id} already exists") from e
            except Exception as e:
                raise DatabaseError(f"Failed to create session: {e}") from e

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID. Returns None if not found or expired."""
        async with self._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, csrf_token, created_at, expires_at, user_agent, ip_address
                FROM sessions
                WHERE id = $1 AND expires_at > NOW()
                """,
                session_id,
            )
            if not row:
                return None
            return Session(
                id=row["id"],
                user_id=row["user_id"],
                csrf_token=row["csrf_token"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                user_agent=row["user_agent"],
                ip_address=row["ip_address"],
            )

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if a session was deleted."""
        async with self._connection_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM sessions WHERE id = $1",
                session_id,
            )
            return result.endswith("1")

    async def delete_sessions_for_user(self, user_id: str) -> int:
        """Delete all sessions for a user. Returns count of deleted sessions."""
        async with self._connection_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM sessions WHERE user_id = $1",
                user_id,
            )
            return int(result.split()[-1])


# Global database instance
db = ArcDatabase()
