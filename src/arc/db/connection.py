"""PostgreSQL connection manager for Arc domain."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import asyncpg

from arc.domain.models import Membership, Session, Tenant, User, UserRole
from arc.repositories import DEFAULT_LIST_LIMIT

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database operations."""

    pass


class DuplicateKeyError(DatabaseError):
    """Raised when a unique constraint is violated."""

    pass


class NotFoundError(DatabaseError):
    """Raised when a required record is not found."""

    pass


class CorruptDataError(DatabaseError):
    """Raised when a persisted row violates a domain invariant.

    The row exists but cannot be materialized (e.g. an approval whose
    expiry does not follow its creation). Distinct from connection
    failures so callers translate only this case into a controlled
    domain error; the message carries identifiers, never secrets.
    """

    pass


class ConcurrentUpdateError(DatabaseError):
    """Raised when an optimistic-locking update loses a write-write race.

    The row still exists but its version no longer matches the expected
    version, so another writer committed first. Callers retry against
    freshly resolved state; this error must never be swallowed as success.
    """

    pass


_TENANT_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "status",
    "industry",
    "address",
    "phone",
    "website",
    "logo_url",
    "created_at",
    "updated_at",
)


def _tenant_select_list(alias: str = "") -> str:
    """Build the tenant projection, optionally table-qualified."""
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{column}" for column in _TENANT_COLUMNS)


def _tenant_from_row(row: asyncpg.Record) -> Tenant:
    """Map a row selected with :func:`_tenant_select_list` onto a Tenant.

    Projection and construction both derive from ``_TENANT_COLUMNS``, so a
    column cannot be selected without being mapped or mapped without being
    selected.  ``Tenant`` defaults its profile fields to ``None``, which
    otherwise lets an omitted column pass silently as missing data.
    """
    return Tenant(**{column: row[column] for column in _TENANT_COLUMNS})


DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 20


def _pool_size_from_env(name: str, default: int) -> int:
    """Read a pool bound from the environment, failing loudly on nonsense.

    A misconfigured bound would otherwise surface much later as an opaque
    asyncpg error during startup, so it is rejected here with the variable
    name in the message.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise DatabaseError(f"{name} must be an integer, got {raw!r}") from None
    if value < 1:
        raise DatabaseError(f"{name} must be at least 1, got {value}")
    return value


class ArcDatabase:
    """Database manager for Arc domain models."""

    def __init__(
        self,
        database_url: str = ("postgresql://arc:arc-dev-password@localhost:5432/arc"),
        pool_min: int | None = None,
        pool_max: int | None = None,
    ):
        """Create the manager.

        ``pool_min``/``pool_max`` default to ``DB_POOL_MIN``/``DB_POOL_MAX``
        from the environment. asyncpg's own default is a fixed 10/10, which
        caps concurrency and cannot be tuned without a code change.
        """
        self.database_url = database_url
        self.pool_min = (
            pool_min
            if pool_min is not None
            else _pool_size_from_env("DB_POOL_MIN", DEFAULT_POOL_MIN)
        )
        self.pool_max = (
            pool_max
            if pool_max is not None
            else _pool_size_from_env("DB_POOL_MAX", DEFAULT_POOL_MAX)
        )
        if self.pool_min > self.pool_max:
            raise DatabaseError(
                f"DB_POOL_MIN ({self.pool_min}) cannot exceed DB_POOL_MAX ({self.pool_max})"
            )
        self._connection_pool = None

    async def connect(self) -> None:
        """Establish connection pool."""
        self._connection_pool = await asyncpg.create_pool(
            self.database_url,
            min_size=self.pool_min,
            max_size=self.pool_max,
        )

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._connection_pool:
            await self._connection_pool.close()

    async def ensure_schema(self) -> None:
        """Provision the full Arc schema from ``schema.sql`` idempotently.

        ``src/arc/db/schema.sql`` is the single source of truth
        (Issue #207, V2-ADR-028). Every statement in that file is
        idempotent (``IF NOT EXISTS``, ``ADD COLUMN IF NOT EXISTS``,
        etc.) so this is safe to run on every startup.

        The file is split on ``;`` — the same rule the test suite
        uses — so the file must never contain a ``;`` inside a comment
        (already enforced by a comment in ``schema.sql``).

        Failures are not swallowed: a schema error fails startup
        rather than serving a misleading healthy application.
        """
        if not self._connection_pool:
            raise DatabaseError("Database not connected")

        # Locate schema.sql — the single source of truth. Prefer the
        # file alongside this module (works for both src layout and
        # site-packages when package-data is configured), then fall
        # back to importlib.resources and the known /app/src location
        # for robustness across Docker/build layouts.
        candidates: list[Path] = [Path(__file__).with_name("schema.sql")]
        try:
            import importlib.resources as _resources

            candidates.append(Path(str(_resources.files("arc.db") / "schema.sql")))
        except Exception:
            pass
        candidates.append(Path("/app/src/arc/db/schema.sql"))

        schema_path: Path | None = next((p for p in candidates if p.exists()), None)
        if schema_path is None:
            raise DatabaseError(
                f"Schema file not found (tried: {', '.join(str(p) for p in candidates)})"
            )

        schema_sql = schema_path.read_text(encoding="utf-8")

        # Ensure pgvector is available before any vector column is created.
        # The file itself also contains this statement, but executing it
        # first guarantees correct ordering regardless of file layout.
        async with self._connection_pool.acquire() as conn:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as exc:
                raise DatabaseError(f"Failed to ensure pgvector extension: {exc}") from exc

        # Execute each statement from schema.sql in order. Statements
        # that are already satisfied are no-ops due to IF NOT EXISTS.
        async with self._connection_pool.acquire() as conn:
            for raw in schema_sql.split(";"):
                stmt = raw.strip()
                if not stmt:
                    continue
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    raise DatabaseError(
                        f"Failed to apply schema statement: {stmt[:120]!r}: {exc}"
                    ) from exc

        logger.info("Database schema ensured from %s", schema_path.name)

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
                f"SELECT {_tenant_select_list()} FROM tenants WHERE id = $1",
                tenant_id,
            )
            if not row:
                raise NotFoundError(f"Tenant with id {tenant_id} not found")
            return _tenant_from_row(row)

    async def list_tenants(self, limit: int = DEFAULT_LIST_LIMIT) -> list[Tenant]:
        """List every tenant, newest first (platform-scoped, no membership filter)."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_tenant_select_list()} FROM tenants "
                "ORDER BY created_at DESC, id ASC LIMIT $1",
                limit,
            )
            return [_tenant_from_row(row) for row in rows]

    async def list_tenants_paginated(self, limit: int, offset: int) -> tuple[list[Tenant], int]:
        """One page of tenants, newest first, with the total row count."""
        async with self._connection_pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM tenants")
            rows = await conn.fetch(
                f"SELECT {_tenant_select_list()} FROM tenants "
                "ORDER BY created_at DESC, id ASC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
            return [_tenant_from_row(row) for row in rows], total

    async def set_tenant_status(self, tenant_id: str, new_status: str) -> Tenant:
        """Write ONLY the status column (ADR-011).

        Deliberately not read-modify-write through ``update_tenant``,
        which writes every column. Doing it that way loses concurrent
        edits in both directions: a company administrator renaming the
        workspace while a platform operator suspends it means whichever
        commits second overwrites the other's field entirely.

        The dangerous direction is losing the SUSPENSION -- the operator
        believes a customer is stopped and they are not, with nothing to
        indicate it. Writing one column makes the two operations
        independent, so neither can silently revert the other.

        The row is re-read on the same connection so the caller sees the
        committed state rather than a value from another pooled
        connection.
        """
        async with self.transaction() as conn:
            updated = await conn.fetchrow(
                """
                UPDATE tenants
                SET status = $2, updated_at = NOW()
                WHERE id = $1
                RETURNING id, name, status, industry, address, phone,
                          website, logo_url, created_at, updated_at
                """,
                tenant_id,
                new_status,
            )
            if updated is None:
                raise NotFoundError(f"Tenant with id {tenant_id} not found")
            return Tenant(
                id=updated["id"],
                name=updated["name"],
                status=updated["status"],
                industry=updated["industry"],
                address=updated["address"],
                phone=updated["phone"],
                website=updated["website"],
                logo_url=updated["logo_url"],
                created_at=updated["created_at"],
                updated_at=updated["updated_at"],
            )

    async def update_tenant(self, tenant: Tenant) -> Tenant:
        """Update tenant company configuration.

        Writes profile columns ONLY. ``status`` is deliberately absent
        (ADR-011): no endpoint may change it here, and writing it back
        from a read-modify-write meant a profile edit silently reverted a
        suspension -- the caller re-read the row while the tenant was
        active, then wrote that stale value over a suspension committed
        in between. The operator would believe a customer was stopped
        when they were not, with nothing to indicate it.

        Status is changed only through ``set_tenant_status``, which
        writes that one column, so the two operations are independent
        and neither can overwrite the other.

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
                    SET name = $2, industry = $3, address = $4,
                        phone = $5, website = $6, logo_url = $7, updated_at = $8
                    WHERE id = $1
                    """,
                    tenant.id,
                    tenant.name,
                    tenant.industry,
                    tenant.address,
                    tenant.phone,
                    tenant.website,
                    tenant.logo_url,
                    tenant.updated_at,
                )
                row = await conn.fetchrow(
                    f"SELECT {_tenant_select_list()} FROM tenants WHERE id = $1",
                    tenant.id,
                )
                if not row:
                    raise NotFoundError(f"Tenant with id {tenant.id} not found")
                return _tenant_from_row(row)
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
                "SELECT id, email, username, status, auth_provider, "
                "provider_subject, display_name, avatar_url, "
                "created_at, updated_at FROM users WHERE id = $1",
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

    async def get_tenants_for_user(
        self, user_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[Tenant]:
        """Get all tenants for a user."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_tenant_select_list("t")}
                FROM tenants t
                JOIN memberships m ON t.id = m.tenant_id
                WHERE m.user_id = $1
                ORDER BY t.created_at DESC, t.id ASC
                LIMIT $2
                """,
                user_id,
                limit,
            )
            return [_tenant_from_row(row) for row in rows]

    async def get_tenants_for_user_paginated(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[Tenant], int]:
        """One page of a user's tenants, with the total membership count."""
        async with self._connection_pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM memberships WHERE user_id = $1", user_id
            )
            rows = await conn.fetch(
                f"""
                SELECT {_tenant_select_list("t")}
                FROM tenants t
                JOIN memberships m ON t.id = m.tenant_id
                WHERE m.user_id = $1
                ORDER BY t.created_at DESC, t.id ASC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )
            return [_tenant_from_row(row) for row in rows], total

    async def get_users_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[User]:
        """Get all users for a tenant."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.id, u.email, u.username, u.status,
                       u.created_at, u.updated_at
                FROM users u
                JOIN memberships m ON u.id = m.user_id
                WHERE m.tenant_id = $1
                ORDER BY u.created_at DESC, u.id ASC
                LIMIT $2
                """,
                tenant_id,
                limit,
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

    async def get_memberships_for_user(
        self, user_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[Membership]:
        """Get all memberships for a user."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, tenant_id, role, created_at, updated_at
                FROM memberships
                WHERE user_id = $1
                ORDER BY created_at DESC, id ASC
                LIMIT $2
                """,
                user_id,
                limit,
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

    async def get_memberships_with_tenant_for_users(self, user_ids: list[str]) -> dict:
        """Map each user id to their memberships, with tenant names.

        One query for the whole page rather than one per user: the
        platform directory renders every provisioned user, so a per-user
        lookup is an N+1 that grows with the customer base.

        Returns ``{user_id: [{tenant_id, tenant_name, role}, ...]}``.
        Users with no membership are simply absent from the mapping.

        Membership is platform administration metadata, not tenant
        content. ADR-008 already allows a PLATFORM_ADMINISTRATOR to
        CREATE memberships for any user in any tenant, so reading which
        ones exist is strictly less privileged. Tenant content
        (knowledge, approvals, skills) remains unreachable from the
        platform plane.
        """
        if not user_ids:
            return {}
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.user_id, m.tenant_id, m.role, t.name AS tenant_name
                FROM memberships m
                JOIN tenants t ON t.id = m.tenant_id
                WHERE m.user_id = ANY($1::varchar[])
                ORDER BY t.name ASC, m.user_id ASC
                """,
                user_ids,
            )
        grouped: dict = {}
        for row in rows:
            grouped.setdefault(row["user_id"], []).append(
                {
                    "tenant_id": row["tenant_id"],
                    "tenant_name": row["tenant_name"],
                    "role": row["role"],
                }
            )
        return grouped

    async def get_memberships_for_tenant(
        self, tenant_id: str, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[Membership]:
        """Get all memberships for a tenant."""
        async with self._connection_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, tenant_id, role, created_at, updated_at
                FROM memberships
                WHERE tenant_id = $1
                ORDER BY created_at DESC, id ASC
                LIMIT $2
                """,
                tenant_id,
                limit,
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
        self,
        user_id: str,
        auth_provider: str,
        provider_subject: str,
        display_name: str | None = None,
        avatar_url: str | None = None,
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
                    user_id,
                    auth_provider,
                    provider_subject,
                    display_name,
                    avatar_url,
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
                    INSERT INTO sessions
                        (id, user_id, csrf_token, created_at,
                         expires_at, user_agent, ip_address)
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
