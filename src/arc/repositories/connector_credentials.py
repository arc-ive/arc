"""PostgreSQL repository for tenant-scoped connector credentials (V2-ADR-015).

Credentials are stored encrypted (BYTEA). The repository never handles
plaintext credentials. Every query is tenant-scoped to enforce isolation.

Every query also names a ``scope`` (ADR-013). Read and act credentials
live in the same table but are never interchangeable, and the scope is a
predicate on every statement rather than a filter applied afterwards, so
no code path can reach an act credential while asking for a read one.
"""

from typing import List, Optional

import asyncpg

from arc.db.connection import ArcDatabase, DuplicateKeyError, NotFoundError
from arc.domain.models import (
    ConnectorCredential,
    ConnectorCredentialAudit,
    ConnectorProvider,
    CredentialScope,
)
from arc.repositories import DEFAULT_LIST_LIMIT


class PostgreSQLConnectorCredentialRepository:
    """PostgreSQL-backed connector credential storage."""

    def __init__(self, db: ArcDatabase):
        self._db = db

    async def get_by_tenant_and_provider(
        self,
        tenant_id: str,
        provider: str,
        scope: str = CredentialScope.READ.value,
    ) -> Optional[ConnectorCredential]:
        """Return the encrypted credential for a tenant/provider/scope, or None.

        ``scope`` defaults to ``read`` so every pre-ADR-013 call site keeps
        the behaviour it had. An act credential is only ever returned to a
        caller that asked for one by name.
        """
        async with self._db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, provider, encrypted_credential,
                       key_version, created_at, rotated_at, scope
                FROM connector_credentials
                WHERE tenant_id = $1 AND provider = $2 AND scope = $3
                """,
                tenant_id,
                provider,
                scope,
            )
        if row is None:
            return None
        return self._from_row(row)

    async def create(self, credential: ConnectorCredential) -> ConnectorCredential:
        """Persist a new encrypted credential.

        Raises ``DuplicateKeyError`` when a credential already exists for
        the same ``(tenant_id, provider, scope)`` triple.  Callers must
        translate this into a domain-appropriate 409 Conflict.
        """
        async with self._db._connection_pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO connector_credentials
                        (id, tenant_id, provider, encrypted_credential,
                         key_version, created_at, rotated_at, scope)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    credential.id,
                    credential.tenant_id,
                    credential.provider.value,
                    credential.encrypted_credential,
                    credential.key_version,
                    credential.created_at,
                    credential.rotated_at,
                    credential.scope.value,
                )
            except asyncpg.UniqueViolationError as exc:
                raise DuplicateKeyError(
                    f"Credential already exists for provider {credential.provider.value}"
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
                WHERE tenant_id = $4 AND provider = $5 AND scope = $6
                """,
                credential.encrypted_credential,
                credential.key_version,
                credential.rotated_at,
                credential.tenant_id,
                credential.provider.value,
                credential.scope.value,
            )
            if result == "UPDATE 0":
                raise NotFoundError("Connector credential not found")
        return credential

    async def delete(
        self,
        tenant_id: str,
        provider: str,
        scope: str = CredentialScope.READ.value,
    ) -> None:
        """Delete the credential for a tenant/provider/scope."""
        async with self._db._connection_pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM connector_credentials
                WHERE tenant_id = $1 AND provider = $2 AND scope = $3
                """,
                tenant_id,
                provider,
                scope,
            )
            if result == "DELETE 0":
                raise NotFoundError("Connector credential not found")

    async def create_audit(self, audit: ConnectorCredentialAudit) -> ConnectorCredentialAudit:
        """Persist a credential lifecycle audit record."""
        async with self._db._connection_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO connector_credential_audit
                    (id, tenant_id, provider, operation, actor_user_id,
                     key_version, created_at, scope)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                audit.id,
                audit.tenant_id,
                audit.provider.value,
                audit.operation,
                audit.actor_user_id,
                audit.key_version,
                audit.created_at,
                audit.scope.value,
            )
        return audit

    async def list_audit_for_tenant(
        self,
        tenant_id: str,
        provider: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> List[ConnectorCredentialAudit]:
        """List audit records for a tenant, optionally filtered by provider."""
        async with self._db._connection_pool.acquire() as conn:
            if provider:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at, scope
                    FROM connector_credential_audit
                    WHERE tenant_id = $1 AND provider = $2
                    ORDER BY created_at DESC, id ASC
                    LIMIT $3
                    """,
                    tenant_id,
                    provider,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at, scope
                    FROM connector_credential_audit
                    WHERE tenant_id = $1
                    ORDER BY created_at DESC, id ASC
                    LIMIT $2
                    """,
                    tenant_id,
                    limit,
                )
        return [self._audit_from_row(row) for row in rows]

    async def list_audit_for_tenant_paginated(
        self, tenant_id: str, limit: int, offset: int, provider: Optional[str] = None
    ) -> tuple:
        """List audit records with LIMIT/OFFSET and total count."""
        async with self._db._connection_pool.acquire() as conn:
            if provider:
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM connector_credential_audit "
                    "WHERE tenant_id = $1 AND provider = $2",
                    tenant_id,
                    provider,
                )
                total = count_row["cnt"]
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at, scope
                    FROM connector_credential_audit
                    WHERE tenant_id = $1 AND provider = $2
                    ORDER BY created_at DESC, id ASC
                    LIMIT $3 OFFSET $4
                    """,
                    tenant_id,
                    provider,
                    limit,
                    offset,
                )
            else:
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM connector_credential_audit WHERE tenant_id = $1",
                    tenant_id,
                )
                total = count_row["cnt"]
                rows = await conn.fetch(
                    """
                    SELECT id, tenant_id, provider, operation, actor_user_id,
                           key_version, created_at, scope
                    FROM connector_credential_audit
                    WHERE tenant_id = $1
                    ORDER BY created_at DESC, id ASC
                    LIMIT $2 OFFSET $3
                    """,
                    tenant_id,
                    limit,
                    offset,
                )
        items = [self._audit_from_row(row) for row in rows]
        return items, total

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
            scope=CredentialScope(row["scope"]),
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
            scope=CredentialScope(row["scope"]),
        )
