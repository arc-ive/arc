"""Connector synchronization service (Person C connector slice).

Sync follows the ADR-001 ingestion boundary:

    Connector (GitHub/Slack/Linear)
        -> provider adapter (validated, typed records)
        -> Company Brain ingestion (KnowledgeService + PII Guard boundary)
        -> tenant-scoped sync audit record

The tenant boundary comes exclusively from the trusted ``TenantContext``.
Provider credentials are never returned or logged; every attempt produces
an observable tenant-scoped record with a generic error kind. All
failures surface to the API as a single controlled error type.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from arc.domain.models import (
    ConnectorProvider,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
    KnowledgeSource,
    TenantContext,
)
from arc.repositories import ConnectorRepository, ConnectorSyncRepository
from arc.services.connector_providers.base import (
    ProviderAuthError,
    ProviderCredential,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)
from arc.services.connector_providers.registry import ProviderRegistry
from arc.services.connector_providers.settings import ConnectorCredentialStore
from arc.services.knowledge import KnowledgeService
from arc.services.pii import PiiGuardError


class ConnectorSyncError(Exception):
    """Controlled failure of a connector synchronization attempt."""


@dataclass(frozen=True)
class ConnectorSyncItem:
    """Safe metadata of one fetched record (never raw content)."""

    source_id: str
    title: str
    url: Optional[str] = None


@dataclass(frozen=True)
class ConnectorSyncResult:
    """Safe summary of a successful synchronization."""

    connector_id: str
    provider: ConnectorProvider
    items_fetched: int
    items: List[ConnectorSyncItem] = field(default_factory=list)


_ERROR_KINDS = {
    ProviderValidationError: "invalid_target",
    ProviderAuthError: "auth_failed",
    ProviderRateLimitError: "rate_limited",
    ProviderTransportError: "transport_error",
    ProviderResponseError: "invalid_provider_response",
}


class ConnectorSyncService:
    """Controlled connector synchronization (PRD 22, TRD 33, ADR-002)."""

    def __init__(
        self,
        connector_repo: ConnectorRepository,
        sync_repo: ConnectorSyncRepository,
        registry: ProviderRegistry,
        credential_store: ConnectorCredentialStore,
        knowledge_service: KnowledgeService,
    ):
        self.connector_repo = connector_repo
        self.sync_repo = sync_repo
        self.registry = registry
        self.credential_store = credential_store
        self.knowledge_service = knowledge_service

    async def sync(self, context: TenantContext, connector_id: str) -> ConnectorSyncResult:
        """Synchronize one tenant-owned connector.

        Flow: tenant-scoped connector lookup -> adapter selection ->
        credential resolution -> provider fetch -> validated records ->
        Company Brain ingestion (PII boundary) -> success audit record.
        Any controlled failure produces a failed audit record and raises
        ``ConnectorSyncError``; ``NotFoundError`` from the connector lookup
        propagates unchanged so the API can return a safe 404.
        """
        config = await self.connector_repo.get_by_id(connector_id, context.tenant_id)

        adapter = self.registry.get(config.provider)
        if adapter is None:
            await self._record_failure(context, config, "unsupported_provider")
            raise ConnectorSyncError("Connector provider is not supported")

        token = self.credential_store.get(context.tenant_id, config.provider)
        if token is None:
            await self._record_failure(context, config, "missing_credential")
            raise ConnectorSyncError("Connector credentials are not configured")

        credential = ProviderCredential(provider=config.provider, token=token)
        try:
            result = await adapter.fetch(credential, config.name)
        except ProviderError as exc:
            error_kind = _ERROR_KINDS.get(type(exc), "provider_error")
            await self._record_failure(context, config, error_kind)
            raise ConnectorSyncError("Connector synchronization failed") from exc

        try:
            for record in result.records:
                await self.knowledge_service.ingest_document(
                    context,
                    source=KnowledgeSource.INTERNAL_KNOWLEDGE,
                    provenance=f"connector:{config.provider.value}:{record.source_id}",
                    content=record.content,
                )
        except PiiGuardError as exc:
            await self._record_failure(context, config, "pii_guard_failed")
            raise ConnectorSyncError("Connector content failed the PII guard") from exc

        await self._record_success(context, config, len(result.records))
        return ConnectorSyncResult(
            connector_id=config.id,
            provider=config.provider,
            items_fetched=len(result.records),
            items=[
                ConnectorSyncItem(source_id=record.source_id, title=record.title, url=record.url)
                for record in result.records
            ],
        )

    async def _record_success(
        self,
        context: TenantContext,
        config,
        items_fetched: int,
    ) -> None:
        await self.sync_repo.create_record(
            ConnectorSyncRecord(
                id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                connector_id=config.id,
                provider=config.provider,
                status=ConnectorSyncStatus.SUCCESS,
                items_fetched=items_fetched,
                created_at=datetime.now(),
            )
        )

    async def _record_failure(
        self,
        context: TenantContext,
        config,
        error_kind: str,
    ) -> None:
        await self.sync_repo.create_record(
            ConnectorSyncRecord(
                id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                connector_id=config.id,
                provider=config.provider,
                status=ConnectorSyncStatus.FAILED,
                error_kind=error_kind,
                created_at=datetime.now(),
            )
        )
