"""Legacy audit migration test (real PostgreSQL, Docker test environment).

Proves that the idempotent schema bootstrap upgrades a pre-audit-contract
database without fabricating audit facts (security review requirement):

- an OLD ``tool_execution_records`` table (created before ``user_id`` and
  ``authorization_outcome`` existed) holds historical rows;
- the CURRENT schema bootstrap runs against that database (twice, to
  prove idempotency);
- the historical rows remain historically accurate: ``user_id`` stays
  NULL (no fabricated user identity) and ``authorization_outcome`` stays
  NULL (no fabricated GRANTED authorization), and no rows are added;
- NEW records still require a real trusted ``user_id`` and a real
  authorization outcome (GRANTED or DENIED) through the real
  ``ToolExecutionService``/repository path.

The test runs against a dedicated throwaway database
(``arc_tool_audit_migration``) that is created, migrated, verified, and
dropped, so it cannot interfere with the main test database.
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import (
    Tenant,
    TenantContext,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolRiskLevel,
    UserRole,
)
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.tools import ToolExecutionService, ToolNotFoundError, build_platform_tool_registry

MIGRATION_DB_NAME = "arc_tool_audit_migration"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://arc:arc-dev-password@localhost:5432/arc_test",
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src" / "arc" / "db" / "schema.sql"

# The tenants table as it existed before the audit contract.
_OLD_TENANTS = """
CREATE TABLE IF NOT EXISTS tenants (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# The tool_execution_records table as it existed before the audit
# contract: no user_id, no authorization_outcome.
_OLD_TOOL_EXECUTION_RECORDS = """
CREATE TABLE tool_execution_records (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    tool_version VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    risk_level VARCHAR(50) NOT NULL,
    input_summary TEXT NOT NULL,
    output_summary TEXT,
    error_kind VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT ck_tool_execution_records_status CHECK (status IN ('success', 'failed')),
    CONSTRAINT ck_tool_execution_records_risk_level CHECK (risk_level IN ('low', 'medium', 'high'))
);
"""

_OLD_INDEX = """
CREATE INDEX IF NOT EXISTS idx_tool_execution_records_tenant_id
    ON tool_execution_records(tenant_id);
"""


def _migration_url() -> str:
    """DATABASE_URL with the path swapped to the migration database."""
    parts = urlparse(DATABASE_URL)
    return urlunparse(parts._replace(path=f"/{MIGRATION_DB_NAME}"))


async def _drop_migration_database() -> None:
    admin = await asyncpg.connect(DATABASE_URL)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {MIGRATION_DB_NAME} WITH (FORCE)")
    finally:
        await admin.close()


async def _create_migration_database() -> None:
    admin = await asyncpg.connect(DATABASE_URL)
    try:
        await admin.execute(f"CREATE DATABASE {MIGRATION_DB_NAME}")
    finally:
        await admin.close()


async def _run_schema(database: ArcDatabase) -> None:
    """Apply the current schema.sql exactly like the application bootstrap."""
    async with database._connection_pool.acquire() as conn:
        for statement in SCHEMA_PATH.read_text().split(";"):
            if statement.strip():
                await conn.execute(statement)


async def test_legacy_audit_migration_preserves_history_and_stays_strict():
    await _drop_migration_database()
    await _create_migration_database()

    database = ArcDatabase(_migration_url())
    await database.connect()
    try:
        async with database._connection_pool.acquire() as conn:
            await conn.execute(_OLD_TENANTS)
            await conn.execute(_OLD_TOOL_EXECUTION_RECORDS)
            await conn.execute(_OLD_INDEX)
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, $2)",
                "legacy-tenant-a",
                "Legacy Tenant A",
            )
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, $2)",
                "legacy-tenant-b",
                "Legacy Tenant B",
            )
            await conn.execute(
                """
                INSERT INTO tool_execution_records
                    (id, tenant_id, tool_name, tool_version, status, risk_level,
                     input_summary, output_summary, error_kind)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                "legacy-record-1",
                "legacy-tenant-a",
                "check_service_health",
                "1",
                "success",
                "low",
                "{}",
                "{}",
                None,
            )
            await conn.execute(
                """
                INSERT INTO tool_execution_records
                    (id, tenant_id, tool_name, tool_version, status, risk_level,
                     input_summary, output_summary, error_kind)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                "legacy-record-2",
                "legacy-tenant-b",
                "restart_service",
                "1",
                "failed",
                "high",
                "{}",
                None,
                "not_allowed",
            )

        # Current bootstrap runs against the legacy database, twice, to
        # prove the migration is idempotent.
        await _run_schema(database)
        await _run_schema(database)

        async with database._connection_pool.acquire() as conn:
            columns = await conn.fetch(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'tool_execution_records'
                  AND column_name IN ('user_id', 'authorization_outcome')
                """
            )
            nullable = {row["column_name"]: row["is_nullable"] for row in columns}
            assert nullable == {"user_id": "YES", "authorization_outcome": "YES"}

            legacy_rows = await conn.fetch(
                """
                SELECT id, user_id, authorization_outcome
                FROM tool_execution_records
                WHERE id IN ('legacy-record-1', 'legacy-record-2')
                ORDER BY id
                """
            )
            assert len(legacy_rows) == 2
            for row in legacy_rows:
                assert row["user_id"] is None, "migration fabricated a user identity"
                assert row["authorization_outcome"] is None, (
                    "migration fabricated an authorization decision"
                )

            total = await conn.fetchval("SELECT COUNT(*) FROM tool_execution_records")
            assert total == 2, "migration must not fabricate or duplicate rows"

        # New-record contract on the migrated schema: the domain model
        # requires a real user_id (no default, no fabrication).
        with pytest.raises(TypeError):
            ToolExecutionRecord(
                id="new-record-without-user",
                tenant_id="legacy-tenant-a",
                tool_name="check_service_health",
                tool_version="1",
                status=ToolExecutionStatus.SUCCESS,
                risk_level=ToolRiskLevel.LOW,
                input_summary="{}",
            )

        # New-record contract through the real service + repository:
        # records on the migrated database carry a real trusted user_id
        # and a real authorization outcome.
        tenant_repo = PostgreSQLTenantRepository(database)
        new_tenant = await tenant_repo.create(
            Tenant(id=f"migrated-tenant-{uuid.uuid4().hex[:8]}", name="Migrated Tenant")
        )
        record_repo = PostgreSQLToolExecutionRepository(database)
        service = ToolExecutionService(build_platform_tool_registry(), record_repo)
        principal = AuthenticatedPrincipal(user_id="real-user-1")
        authorization = AuthorizationService({"real-user-1": ApplicationRole.OPERATIONS_USER})
        context = TenantContext(
            tenant_id=new_tenant.id,
            tenant_name="Migrated Tenant",
            user_id="real-user-1",
            role=UserRole.MEMBER,
        )

        result = await service.execute_tool(
            context, principal, "check_service_health", {}, authorization
        )
        assert result.tool_name == "check_service_health"

        with pytest.raises(ToolNotFoundError):
            await service.execute_tool(context, principal, "restart_service", {}, authorization)

        async with database._connection_pool.acquire() as conn:
            new_rows = await conn.fetch(
                """
                SELECT user_id, authorization_outcome, status, error_kind
                FROM tool_execution_records
                WHERE tenant_id = $1
                ORDER BY created_at
                """,
                new_tenant.id,
            )
            assert len(new_rows) == 2
            assert new_rows[0]["user_id"] == "real-user-1"
            assert new_rows[0]["authorization_outcome"] == "granted"
            assert new_rows[0]["status"] == "success"
            assert new_rows[1]["user_id"] == "real-user-1"
            assert new_rows[1]["authorization_outcome"] == "denied"
            assert new_rows[1]["error_kind"] == "unknown_tool"
            assert new_rows[1]["status"] == "failed"

        await tenant_repo.delete(new_tenant.id)
    finally:
        await database.disconnect()
        await _drop_migration_database()
