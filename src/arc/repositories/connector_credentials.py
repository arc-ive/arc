"""PostgreSQL repository for tenant-scoped connector credentials (V2-ADR-015).

Credentials are stored encrypted (BYTEA). The repository never handles
plaintext credentials. Every query is tenant-scoped to enforce isolation.
"""

from typing import List, Optional

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    ConnectorCredential,
    ConnectorCredentialAudit,
    ConnectorProvider,
)


class PostgreSQLConnectorCredentialRepository:
    """PostgreSQL-backed connector credential storage."""

    def __init__(self, db: ArcDatabase):
        self._db = db

    async def get_by_tenant_and_provider(
        self, tenant_id: str, provider: str
    ) -> Optional[ConnectorCredential]:
        """Return the encrypted credential for a tenant/provider, or None."""
        async with self._db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, provider, encrypted_credential,
                       key_version, created_at, rotated_at
                FROM connector_credentials
                WHERE tenant_id = $1 AND provider = $2
                """,
                tenant_id,
                provider,
            )
        if row is None:
            return None
        return self._from_row(row)

    async def create(self, credential: ConnectorCredential) -> ConnectorCredential:
        """Persist a new encrypted credential.

        Raises ``DuplicateKeyError`` when a credential already exists for
        the same ``(tenant_id, provider)`` pair.  Callers must translate
        this into a domain-appropriate 409 Conflict.
        """
        async with self._db._connection_pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO connector_credentials
                        (id, tenant_id, provider, encrypted_credential,
                         key_version, created_at, rotated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    credential.id,
                    credential.tenant_id,
                    credential.provider.value,
                    credential.encrypted_credential,
                    credential.key_version,
                    credential.created_at,
                    credential.rotated_at,
                )
            except asyncpg.UniqueViolationError as exc:
                raise DuplicateKeyError(
                    f"Credential already exists for tenant "
                    f"{credential.tenant_id} provider {credential.provider.value}"
                ) from exc
        return credential

    async def update(self, credential: ConnectorCredential) -> ConnectorCredential:
        """Update an existing encrypted credential (rotation)."""
        async with self._db._connection_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE connector_credentials
                SET encrypted_credential = $1,
                    key_version = $2,
                    rotated_at = $3
                WHERE tenant_id = $4 AND provider = $5
                """,
                credential.encrypted_credential,
                credential.key_version,
                credential.rotated_at,
                credential.tenant_id,
                credential.provider.value,
            )
            if result == "UPDATE 0":
                raise NotFoundError(
                    f"No credential for tenant {credential.tenant_id} "
                    f"provider {credential.provider.value}"
                )
        return credential

    async def delete(self, tenant_id: str, provider: str) -> None:
        """Delete the credential for a tenant/provider."""
        async with self._db._connection_pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM connector_credentials
                WHERE tenant_id = $1 AND provider = $2
                """,
                tenant_id,
                provider,
            )
            if result == "DELETE 0":
                raise NotFoundError(f"No credential for tenant {tenant_id} provider {provider}")

    async def create_audit(self, audit: ConnectorCredentialAudit) -> ConnectorCredentialAudit:
        """Persist a credential lifecycle audit record."""
        async with self._db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO connector_credential_audit
                    (id, tenant_id, provider, operation, actor_user_id,
                     key_version, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                audit.id,
                audit.tenant_id,
                audit.provider.value,
                audit.operation,
                audit.actor_user_id,
                audit.key_version,
                audit.created_at,
            )
        return audit

    async def list_audit_for_tenant(
        self, tenant_id: str, provider: Optional[str] = None
    ) -> List[ConnectorCredentialAudit]:
        """List audit records for a tenant, optionally filtered by provider."""
        async with self._db._connection_pool.acquire() as conn:
            if provider:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at
                    FROM connector_credential_audit
                    WHERE tenant_id = $1 AND provider = $2
                    ORDER BY created_at DESC
                    """,
                    tenant_id,
                    provider,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at
                    FROM connector_credential_audit
                    WHERE tenant_id = $1
                    ORDER BY created_at DESC
                    """,
                    tenant_id,
                )
        return [self._audit_from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> ConnectorCredential:
        return ConnectorCredential(
            id=row["id"],
            tenant_id=row["tenant_id"],
            provider=ConnectorProvider(row["provider"]),
            encrypted_credential=row["encrypted_credential"],
            key_version=row["key_version"],
            created_at=row["created_at"],
            rotated_at=row["rotated_at"],
        )

    @staticmethod
    def _audit_from_row(row) -> ConnectorCredentialAudit:
        return ConnectorCredentialAudit(
            id=row["id"],
            tenant_id=row["tenant_id"],
            provider=ConnectorProvider(row["provider"]),
            operation=row["operation"],
            actor_user_id=row["actor_user_id"],
            key_version=row["key_version"],
            created_at=row["created_at"],
        )
