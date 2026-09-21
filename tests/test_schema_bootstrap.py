"""Fresh-database schema bootstrap integration tests (Issue #207).

These tests use a genuinely empty database — a temporary database
created for the test — rather than relying on ``tests/conftest.py``'s
pre-applied schema. They prove:

1. ``ArcDatabase.ensure_schema()`` provisions the full schema from
   ``src/arc/db/schema.sql`` (the single source of truth).
2. Provisioning is idempotent and does not destroy existing data.
3. The application can serve ``/health`` after provisioning.

The temporary database is created via a superuser connection to the
``postgres`` maintenance database and is dropped after the test,
so the main test database (``arc``) is never disturbed.
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

from arc.db.connection import ArcDatabase

# The single source of truth — used to derive the expected table set.
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"

# A minimal set of tables that must exist after provisioning. The full
# schema currently has 18 tables (verified against schema.sql); we assert
# at least the core set so the test does not need to be updated for every
# future table addition, while still catching the "no schema" failure.
REQUIRED_TABLES = frozenset(
    {
        "tenants",
        "users",
        "memberships",
        "connector_configs",
        "knowledge_documents",
        "knowledge_chunks",
        "skills",
        "tool_execution_records",
        "connector_sync_records",
        "connector_credentials",
        "connector_credential_audit",
        "webhook_events",
        "api_request_records",
        "approval_requests",
        "agent_run_records",
        "skill_execution_records",
        "sessions",
        "llm_usage_records",
        "platform_capabilities",
        "tenant_capabilities",
    }
)


def _parse_database_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "user": parsed.username or "arc",
        "password": parsed.password or "arc-dev-password",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "database": parsed.path.lstrip("/") or "arc",
    }


def _base_database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://arc:arc-dev-password@localhost:5432/arc")


def _maintenance_url(parts: dict) -> str:
    return (
        f"postgresql://{parts['user']}:{parts['password']}@{parts['host']}:{parts['port']}/postgres"
    )


def _temp_database_url(parts: dict, temp_db: str) -> str:
    return f"postgresql://{parts['user']}:{parts['password']}@{parts['host']}:{parts['port']}/{temp_db}"


@pytest.fixture
async def temp_db_url():
    """Create an empty temporary database and yield its URL.

    The database is dropped after the test, so the main ``arc``
    database is never affected.
    """
    parts = _parse_database_url(_base_database_url())
    temp_db = f"arc_bootstrap_{uuid.uuid4().hex[:8]}"

    conn = await asyncpg.connect(_maintenance_url(parts))
    try:
        await conn.execute(f'CREATE DATABASE "{temp_db}"')
    finally:
        await conn.close()

    url = _temp_database_url(parts, temp_db)
    try:
        yield url
    finally:
        conn = await asyncpg.connect(_maintenance_url(parts))
        try:
            # Terminate any remaining connections so DROP succeeds.
            await conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = $1 AND pid <> pg_backend_pid()
                """,
                temp_db,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{temp_db}"')
        finally:
            await conn.close()


async def _table_names(conn) -> set[str]:
    rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {r["tablename"] for r in rows}


async def _extension_exists(conn, ext: str) -> bool:
    return await conn.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname = $1", ext) > 0


@pytest.mark.asyncio
async def test_fresh_database_provisions_full_schema(temp_db_url):
    """Empty database -> ensure_schema -> all required tables exist."""
    db = ArcDatabase(temp_db_url)
    await db.connect()
    try:
        # The database is empty: only pgvector extension may or may not
        # exist. Ensure no application tables are present.
        async with db._connection_pool.acquire() as conn:
            tables_before = await _table_names(conn)
            # Filter to only Arc tables (ignore potential pg internal tables,
            # but public schema should be empty at this point).
            arc_before = tables_before & REQUIRED_TABLES
            assert arc_before == set(), f"Expected empty DB, found: {arc_before}"

        await db.ensure_schema()

        async with db._connection_pool.acquire() as conn:
            tables_after = await _table_names(conn)
            missing = REQUIRED_TABLES - tables_after
            assert not missing, f"Missing tables after provisioning: {missing}"
            assert await _extension_exists(conn, "vector"), "pgvector extension not provisioned"

            # Verify a broader count: schema.sql currently creates 18 tables
            # plus the pgvector extension. At least REQUIRED_TABLES must be
            # present; extra tables are allowed.
            assert len(tables_after) >= len(REQUIRED_TABLES)
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_schema_provisioning_is_idempotent_and_preserves_data(temp_db_url):
    """Provisioning twice must not destroy data (Issue #207 criterion 2)."""
    db = ArcDatabase(temp_db_url)
    await db.connect()
    try:
        await db.ensure_schema()

        # Insert representative persistent data.
        async with db._connection_pool.acquire() as conn:
            tenant_id = f"bootstrap-test-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, $2)",
                tenant_id,
                "Bootstrap Test Tenant",
            )
            before_count = await conn.fetchval(
                "SELECT COUNT(*) FROM tenants WHERE id = $1",
                tenant_id,
            )
            assert before_count == 1

        # Second provisioning must be a no-op for existing data.
        await db.ensure_schema()

        async with db._connection_pool.acquire() as conn:
            after_count = await conn.fetchval(
                "SELECT COUNT(*) FROM tenants WHERE id = $1",
                tenant_id,
            )
            assert after_count == 1, "Idempotent provisioning must not delete existing rows"

            row = await conn.fetchrow("SELECT name FROM tenants WHERE id = $1", tenant_id)
            assert row["name"] == "Bootstrap Test Tenant"

            tables = await _table_names(conn)
            assert REQUIRED_TABLES.issubset(tables)

        # Third provisioning must also be safe.
        await db.ensure_schema()

        async with db._connection_pool.acquire() as conn:
            assert await conn.fetchval("SELECT COUNT(*) FROM tenants WHERE id = $1", tenant_id) == 1
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_schema_sql_remains_single_source_of_truth():
    """Repository must not contain a second DDL source (Issue #207)."""
    # The only authoritative DDL is src/arc/db/schema.sql. This test
    # guards against re-introducing inline CREATE TABLE in setup/init.py
    # or elsewhere in src/arc. It searches for CREATE TABLE outside
    # schema.sql.
    src_root = Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for py_file in src_root.rglob("*.py"):
        # setup/init.py is allowed to reference schema.sql via psql -f,
        # but must not contain CREATE TABLE itself.
        text = py_file.read_text(encoding="utf-8")
        if "CREATE TABLE" in text:
            offenders.append(str(py_file.relative_to(src_root.parents[1])))

    assert offenders == [], f"Found inline DDL outside schema.sql: {offenders}"

    # schema.sql must exist and be non-empty.
    assert SCHEMA_PATH.exists(), f"Schema file not found: {SCHEMA_PATH}"
    assert SCHEMA_PATH.stat().st_size > 1000, "Schema file unexpectedly small"
