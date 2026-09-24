"""Connector credential management service (V2-ADR-015, TRD 20).

Provides tenant-scoped CRUD for connector credentials with:
- AES-256-GCM encryption at rest
- Key versioning for rotation
- Audit events for credential lifecycle
- Never returns plaintext through API responses or logs
- DB credentials take precedence over ENV fallback

The service owns the narrowest possible execution scope for plaintext:
decrypt internally, pass to provider, discard immediately.

Every operation names a ``CredentialScope`` (ADR-013). ``READ`` is the
default so the sync path is unchanged; ``ACT`` addresses the separate
credential an external action uses. The two are distinct rows, and a
caller asking for one never receives the other.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from arc.db.connection import DuplicateKeyError
from arc.domain.models import (
    ConnectorCredential,
    ConnectorCredentialAudit,
    ConnectorProvider,
    CredentialScope,
    TenantContext,
)
from arc.repositories import ConnectorCredentialRepository
from arc.security.encryption import EncryptionError, EncryptionService

logger = logging.getLogger("arc.connector_credentials")


class ConnectorCredentialError(Exception):
    """Controlled failure of a credential operation."""


class ConnectorCredentialService:
    """Tenant-scoped connector credential management (V2-ADR-015).

    Args:
        credential_repo: PostgreSQL-backed credential storage.
        encryption_service: AES-256-GCM encryption/decryption.
    """

    def __init__(
        self,
        credential_repo: ConnectorCredentialRepository,
        encryption_service: EncryptionService,
    ):
        self._repo = credential_repo
        self._encryption = encryption_service

    async def create_credential(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        plaintext_credential: str,
        scope: CredentialScope = CredentialScope.READ,
    ) -> dict:
        """Create a connector credential for a tenant/provider/scope.

        Returns safe metadata only (never the plaintext or encrypted credential).
        A read credential and an act credential for the same provider are
        separate rows; creating one never replaces the other (ADR-013).
        """
        existing = await self._repo.get_by_tenant_and_provider(
            context.tenant_id, provider.value, scope.value
        )
        if existing is not None:
            raise ConnectorCredentialError(
                f"Credential already exists for provider {provider.value} "
                f"({scope.value}). Use rotate to update."
            )

        encrypted, key_version = self._encryption.encrypt(plaintext_credential)

        credential = ConnectorCredential(
            id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            provider=provider,
            encrypted_credential=encrypted,
            key_version=key_version,
            created_at=datetime.now(timezone.utc),
            scope=scope,
        )
        try:
            await self._repo.create(credential)
        except DuplicateKeyError:
            raise ConnectorCredentialError(
                f"Credential already exists for provider {provider.value} "
                f"({scope.value}). Use rotate to update."
            )

        await self._record_audit(
            context.tenant_id,
            provider,
            "create",
            context.user_id,
            key_version,
            scope,
        )

        logger.info(
            "Connector credential created for tenant=%s provider=%s key_version=%d",
            context.tenant_id,
            provider.value,
            key_version,
        )
        return self._safe_metadata(credential)

    async def rotate_credential(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        new_plaintext: str,
        scope: CredentialScope = CredentialScope.READ,
    ) -> dict:
        """Rotate an existing connector credential for one scope.

        Decrypts with existing key version, encrypts with current key version,
        and updates the stored credential. Returns safe metadata only.
        """
        existing = await self._repo.get_by_tenant_and_provider(
            context.tenant_id, provider.value, scope.value
        )
        if existing is None:
            raise ConnectorCredentialError(
                f"No credential found for provider {provider.value} "
                f"({scope.value}). Use create to add one."
            )

        encrypted, key_version = self._encryption.encrypt(new_plaintext)

        credential = ConnectorCredential(
            id=existing.id,
            tenant_id=context.tenant_id,
            provider=provider,
            encrypted_credential=encrypted,
            key_version=key_version,
            created_at=existing.created_at,
            rotated_at=datetime.now(timezone.utc),
            scope=scope,
        )
        await self._repo.update(credential)

        await self._record_audit(
            context.tenant_id,
            provider,
            "rotate",
            context.user_id,
            key_version,
            scope,
        )

        logger.info(
            "Connector credential rotated for tenant=%s provider=%s key_version=%d",
            context.tenant_id,
            provider.value,
            key_version,
        )
        return self._safe_metadata(credential)

    async def delete_credential(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        scope: CredentialScope = CredentialScope.READ,
    ) -> None:
        """Delete a connector credential for a tenant/provider/scope."""
        existing = await self._repo.get_by_tenant_and_provider(
            context.tenant_id, provider.value, scope.value
        )
        if existing is None:
            raise ConnectorCredentialError(
                f"No credential found for provider {provider.value} ({scope.value})"
            )

        await self._repo.delete(context.tenant_id, provider.value, scope.value)

        await self._record_audit(
            context.tenant_id,
            provider,
            "delete",
            context.user_id,
            existing.key_version,
            scope,
        )

        logger.info(
            "Connector credential deleted for tenant=%s provider=%s",
            context.tenant_id,
            provider.value,
        )

    async def get_credential_metadata(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        scope: CredentialScope = CredentialScope.READ,
    ) -> Optional[dict]:
        """Return safe metadata for a credential (never the secret)."""
        credential = await self._repo.get_by_tenant_and_provider(
            context.tenant_id, provider.value, scope.value
        )
        if credential is None:
            return None
        return self._safe_metadata(credential)

    async def resolve_credential(
        self,
        tenant_id: str,
        provider: ConnectorProvider,
        scope: CredentialScope = CredentialScope.READ,
    ) -> Optional[str]:
        """Resolve the plaintext credential for connector execution.

        This is the narrow internal resolution mechanism: decrypt
        in-memory, return to caller, caller discards after use. Used by
        ConnectorSyncService for ``READ`` and by ExternalActionService for
        ``ACT``; never exposed through APIs.

        A missing credential for the requested scope resolves to None even
        when the other scope is configured. That is the point: an act with
        no act credential must fail, not quietly borrow the read token.
        """
        credential = await self._repo.get_by_tenant_and_provider(
            tenant_id, provider.value, scope.value
        )
        if credential is None:
            logger.debug(
                "No %s credential configured for tenant=%s provider=%s",
                scope.value,
                tenant_id,
                provider.value,
            )
            return None
        # Narrow boundary: only the expected decryption failure (tampered
        # or invalid ciphertext) resolves to None. Anything else (DB,
        # pool, or unexpected errors) propagates to the caller.
        try:
            return self._encryption.decrypt(credential.encrypted_credential)
        except EncryptionError:
            logger.error(
                "Failed to decrypt credential for tenant=%s provider=%s",
                tenant_id,
                provider.value,
            )
            return None

    async def list_audit(
        self,
        context: TenantContext,
        provider: Optional[ConnectorProvider] = None,
    ) -> list:
        """List credential audit records for a tenant."""
        return await self._repo.list_audit_for_tenant(
            context.tenant_id,
            provider.value if provider else None,
        )

    async def list_audit_paginated(
        self,
        context: TenantContext,
        limit: int,
        offset: int,
        provider: Optional[ConnectorProvider] = None,
    ) -> tuple:
        """List credential audit records with LIMIT/OFFSET and total count."""
        return await self._repo.list_audit_for_tenant_paginated(
            context.tenant_id,
            limit,
            offset,
            provider.value if provider else None,
        )

    async def _record_audit(
        self,
        tenant_id: str,
        provider: ConnectorProvider,
        operation: str,
        actor_user_id: str,
        key_version: int,
        scope: CredentialScope = CredentialScope.READ,
    ) -> None:
        """Record a credential lifecycle audit event."""
        audit = ConnectorCredentialAudit(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            provider=provider,
            operation=operation,
            actor_user_id=actor_user_id,
            key_version=key_version,
            created_at=datetime.now(timezone.utc),
            scope=scope,
        )
        await self._repo.create_audit(audit)

    @staticmethod
    def _safe_metadata(credential: ConnectorCredential) -> dict:
        """Return safe metadata without any secret material."""
        return {
            "id": credential.id,
            "tenant_id": credential.tenant_id,
            "provider": credential.provider.value,
            "key_version": credential.key_version,
            "created_at": credential.created_at.isoformat(),
            "rotated_at": credential.rotated_at.isoformat() if credential.rotated_at else None,
            "scope": credential.scope.value,
        }
