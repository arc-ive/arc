"""Shared fixtures for X-11 authentication and authorization tests."""

import base64
import os
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from arc.db.connection import ArcDatabase
from arc.domain.models import Membership, Tenant, User, UserRole
from arc.main import app
from arc.repositories.tenancy import (
    PostgreSQLMembershipRepository,
    PostgreSQLTenantRepository,
    PostgreSQLUserRepository,
)
from arc.security.authorization import AuthorizationService
from arc.security.dependencies import get_authorization_service
from arc.security.jwt import JwtService
from arc.security.settings import SecuritySettings, get_security_settings

TEST_JWT_SECRET = "test-jwt-secret-0123456789-abcdef"

# Disposable test database convention: the suite drops and recreates the
# schema, so it must never target the development database. Only database
# names ending in "_test" (e.g. "arc_test") are accepted.
TEST_DATABASE_URL = "postgresql://arc:arc-dev-password@localhost:5432/arc_test"
TEST_DATABASE_NAME_SUFFIX = "_test"

DATABASE_URL = os.getenv("DATABASE_URL", TEST_DATABASE_URL)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"


class UnsafeTestDatabaseError(Exception):
    """Refusal to run destructive test fixtures against a non-test database."""


def require_test_database(database_url: str) -> str:
    """Validate that a DATABASE_URL names a disposable test database.

    Returns the database name when it ends with ``_test``. Otherwise raises
    :class:`UnsafeTestDatabaseError` with an actionable message that never
    includes credentials. Anything unparseable or ambiguous fails closed.

    This is pure validation: it never connects anywhere.
    """
    try:
        parts = urlsplit(database_url or "")
        # Hostname parsing can raise on malformed IPv6; keep it inside the
        # fail-closed boundary so any unparseable URL is refused cleanly.
        host = parts.hostname or "<missing>"
    except ValueError as exc:
        raise UnsafeTestDatabaseError(
            "Refusing to run destructive test fixtures: DATABASE_URL is not a valid URL. "
            "Set DATABASE_URL to the disposable test database, "
            "e.g. postgresql://arc:<password>@localhost:5432/arc_test"
        ) from exc
    dbname = unquote(parts.path).lstrip("/")
    if (
        parts.scheme != "postgresql"
        or not dbname
        or "/" in dbname
        or not dbname.endswith(TEST_DATABASE_NAME_SUFFIX)
    ):
        # Report only the name/host needed for diagnosis, never credentials.
        seen = dbname or "<missing>"
        raise UnsafeTestDatabaseError(
            f"Refusing to run destructive test fixtures against database "
            f"'{seen}' on host '{host}'. Tests require a disposable test "
            f"database whose name ends with '{TEST_DATABASE_NAME_SUFFIX}' "
            f"(e.g. 'arc_test'). Set DATABASE_URL to the disposable test "
            f"database, e.g. postgresql://arc:<password>@localhost:5432/arc_test"
        )
    return dbname


# Fail fast at collection time: no fixture (destructive or otherwise) runs
# until the target database is proven to be a disposable test database.
require_test_database(DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
async def _initialize_schema():
    """Bootstrap the PostgreSQL schema before any test executes.

    The suite runs against a real PostgreSQL database and must create the
    schema itself: on a fresh database the first test that touches the
    database would otherwise fail with an undefined-table error.

    The entire ``public`` schema is dropped and recreated so that stale
    types, indexes, or constraints from a prior run never interfere with
    the bootstrap.
    """
    database = ArcDatabase(DATABASE_URL)
    await database.connect()

    async with database._connection_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        schema = SCHEMA_PATH.read_text()

        for statement in schema.split(";"):
            if statement.strip():
                await conn.execute(statement)

    await database.disconnect()


@pytest.fixture(scope="session", autouse=True)
def _test_security_environment():
    """Pin the security environment before any application code runs.

    Role assignments default to an empty mapping: unassigned users are
    denied by default. Tests that need roles use ``authorization_override``
    instead of the environment.
    """
    os.environ["JWT_SECRET"] = TEST_JWT_SECRET
    os.environ["JWT_ISSUER"] = "arc"
    os.environ["JWT_AUDIENCE"] = "arc-api"
    os.environ["JWT_EXPIRY_SECONDS"] = "3600"
    os.environ["APPLICATION_ROLE_ASSIGNMENTS"] = "{}"
    # A fixed, non-secret key so encryption-at-rest paths are exercised
    # rather than silently skipped. Without it EncryptionService cannot
    # be constructed, connector credentials degrade to the ENV fallback,
    # and an approved call's arguments are never stored — so the resume
    # path (issue #300) would pass tests by not running at all.
    os.environ.setdefault(
        "CONNECTOR_ENCRYPTION_KEY",
        base64.b64encode(b"arc-test-encryption-key-32bytes!").decode(),
    )
    yield


@pytest.fixture(scope="session")
def jwt_service() -> JwtService:
    """JWT service built from the pinned test environment."""
    return JwtService(get_security_settings())


@pytest.fixture
def make_token(jwt_service):
    """Factory for minting valid JWTs for arbitrary subjects/claims."""

    def _make(
        subject: str,
        *,
        expires_in_seconds: int | None = None,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> str:
        return jwt_service.create_access_token(
            subject,
            expires_in_seconds=expires_in_seconds,
            issuer=issuer,
            audience=audience,
        )

    return _make


@pytest.fixture
def wrong_secret_token():
    """Factory for tokens signed with a DIFFERENT secret (invalid signature)."""
    service = JwtService(SecuritySettings(jwt_secret="another-test-secret-000000-abcdef"))

    def _make(subject: str) -> str:
        return service.create_access_token(subject)

    return _make


@pytest.fixture
def client():
    """TestClient that runs the real app lifecycle (startup/shutdown).

    Requires PostgreSQL, matching the project's Docker-based test
    environment. The session-scoped ``_initialize_schema`` fixture
    handles schema bootstrap; this fixture only manages the app lifecycle.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authorization_override(client):
    """Override the application authorization service with explicit assignments.

    Usage::

        authorization_override({"user-1": ApplicationRole.COMPANY_ADMINISTRATOR})
    """

    def _override(assignments) -> AuthorizationService:
        service = AuthorizationService(assignments)
        app.dependency_overrides[get_authorization_service] = lambda: service
        return service

    yield _override
    app.dependency_overrides.clear()


@pytest.fixture
async def db():
    """Connect to PostgreSQL. Schema is bootstrapped by session-scoped ``_initialize_schema``."""
    database = ArcDatabase(DATABASE_URL)
    await database.connect()

    yield database
    await database.disconnect()


@pytest.fixture
async def repositories(db):
    """Create the three concrete repository instances over one database."""
    tenant_repo = PostgreSQLTenantRepository(db)
    user_repo = PostgreSQLUserRepository(db)
    membership_repo = PostgreSQLMembershipRepository(db)

    return tenant_repo, user_repo, membership_repo


@pytest.fixture(autouse=True)
async def _clean_capability_tables():
    """Truncate capability tables before each test to prevent cross-module pollution."""
    yield
    db = ArcDatabase(DATABASE_URL)
    await db.connect()
    async with db._connection_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE tenant_capabilities, platform_capabilities CASCADE")
    await db.disconnect()


def unique_id(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"x11-{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def seeded(repositories):
    """Create a tenant, a user, and a MEMBER membership; clean up afterwards."""
    tenant_repo, user_repo, membership_repo = repositories

    tenant = await tenant_repo.create(
        Tenant(
            id=unique_id("tenant"),
            name="X11 Tenant",
        )
    )

    user = await user_repo.create(
        User(
            id=unique_id("user"),
            email=f"{uuid.uuid4().hex}@example.com",
            username="x11-user",
        )
    )

    membership = await membership_repo.create(
        Membership(
            id=unique_id("membership"),
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.MEMBER,
        )
    )

    yield tenant, user, membership

    await membership_repo.delete(membership.id)
    await user_repo.delete(user.id)
    await tenant_repo.delete(tenant.id)
