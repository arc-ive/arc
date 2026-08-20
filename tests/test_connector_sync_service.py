"""Tests for the ConnectorSyncService.

Security invariants under test:

- The tenant boundary comes exclusively from the trusted TenantContext;
  the connector is looked up with ``(connector_id, context.tenant_id)``.
- Every attempt produces an observable tenant-scoped audit record with a
  generic error kind; success records carry only safe item counts.
- Provider credentials and raw external payloads never appear in errors,
  results, or audit records.
- Failures are controlled: all provider errors surface as a single
  ``ConnectorSyncError``; ``NotFoundError`` propagates so the API can
  return a safe 404.
- One integration test proves the ADR-001 boundary end-to-end against
  real PostgreSQL: provider content passes through the real PII guard
  before ingestion and only sanitized content is persisted.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import (
    ConnectorConfig,
    ConnectorProvider,
    ConnectorStatus,
    ConnectorSyncRecord,
    ConnectorSyncStatus,
    KnowledgeSource,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories import ConnectorRepository, ConnectorSyncRepository
from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.services.connector_providers.base import (
    ProviderAuthError,
    ProviderCredential,
    ProviderFetchResult,
    ProviderRateLimitError,
    ProviderRecord,
    ProviderResponseError,
    ProviderTransportError,
)
from arc.services.connector_providers.fake import FakeGitHubProvider
from arc.services.connector_providers.registry import ProviderRegistry
from arc.services.connector_providers.settings import ConnectorCredentialStore
from arc.services.connector_sync import ConnectorSyncError, ConnectorSyncService
from arc.services.knowledge import KnowledgeService


def _unique(prefix: str) -> str:
    return f"css-{prefix}-{uuid.uuid4().hex[:10]}"


def _context(tenant_id: str = "tenant-1", user_id: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Acme",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _config(
    tenant_id: str = "tenant-1",
    provider=ConnectorProvider.GITHUB,
    name: str = "example/acme",
) -> ConnectorConfig:
    return ConnectorConfig(
        id=_unique("connector"),
        tenant_id=tenant_id,
        provider=provider,
        name=name,
        status=ConnectorStatus.ACTIVE,
    )


@pytest.fixture
def connector_repo():
    return AsyncMock(spec=ConnectorRepository)


@pytest.fixture
def sync_repo():
    return AsyncMock(spec=ConnectorSyncRepository)


@pytest.fixture
def knowledge_service():
    return AsyncMock(spec=KnowledgeService)


def _service(connector_repo, sync_repo, knowledge_service, registry=None, credentials=None):
    return ConnectorSyncService(
        connector_repo=connector_repo,
        sync_repo=sync_repo,
        registry=registry or ProviderRegistry({ConnectorProvider.GITHUB: FakeGitHubProvider()}),
        credential_store=ConnectorCredentialStore(
            raw=credentials or '{"tenant-1": {"github": "dev-token"}}'
        ),
        knowledge_service=knowledge_service,
    )


class TestConnectorSyncSuccess:
    async def test_success_records_and_ingests(self, connector_repo, sync_repo, knowledge_service):
        config = _config()
        connector_repo.get_by_id.return_value = config
        service = _service(connector_repo, sync_repo, knowledge_service)
        context = _context()

        result = await service.sync(context, config.id)

        assert result.connector_id == config.id
        assert result.provider is ConnectorProvider.GITHUB
        assert result.items_fetched == 3
        assert all(item.source_id for item in result.items)

        connector_repo.get_by_id.assert_awaited_once_with(config.id, context.tenant_id)

        assert knowledge_service.ingest_document.await_count == 3
        for call in knowledge_service.ingest_document.await_args_list:
            args, kwargs = call
            assert args[0].tenant_id == context.tenant_id
            assert kwargs["source"] is KnowledgeSource.INTERNAL_KNOWLEDGE
            assert kwargs["provenance"].startswith("connector:github:")

        assert sync_repo.create_record.await_count == 1
        record = sync_repo.create_record.await_args_list[0][0][0]
        assert isinstance(record, ConnectorSyncRecord)
        assert record.tenant_id == context.tenant_id
        assert record.status is ConnectorSyncStatus.SUCCESS
        assert record.items_fetched == 3
        assert record.error_kind is None

    async def test_result_never_contains_raw_content(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config
        service = _service(connector_repo, sync_repo, knowledge_service)

        fetch = await FakeGitHubProvider().fetch(
            ProviderCredential(provider=ConnectorProvider.GITHUB, token="dev-token"),
            "example/acme",
        )
        raw_contents = {record.content for record in fetch.records}

        result = await service.sync(_context(), config.id)

        # The result summary carries safe metadata only: raw provider
        # content and credential material must never appear.
        summary = repr(result)
        for raw in raw_contents:
            assert raw not in summary
        assert "dev-token" not in summary
        assert all(
            not hasattr(item, "content") and not hasattr(item, "raw") for item in result.items
        )


class TestConnectorSyncFailurePaths:
    async def test_missing_credential_fails_closed(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config
        service = _service(
            connector_repo,
            sync_repo,
            knowledge_service,
            credentials="{}",
        )

        with pytest.raises(ConnectorSyncError, match="not configured"):
            await service.sync(_context(), config.id)

        assert knowledge_service.ingest_document.await_count == 0
        record = sync_repo.create_record.await_args_list[0][0][0]
        assert record.status is ConnectorSyncStatus.FAILED
        assert record.error_kind == "missing_credential"

    async def test_unsupported_provider_fails_closed(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config(provider=ConnectorProvider.GOOGLE_DRIVE)
        connector_repo.get_by_id.return_value = config
        service = _service(
            connector_repo,
            sync_repo,
            knowledge_service,
            registry=ProviderRegistry({}),
            credentials='{"tenant-1": {"google_drive": "t"}}',
        )

        with pytest.raises(ConnectorSyncError, match="not supported"):
            await service.sync(_context(), config.id)

        record = sync_repo.create_record.await_args_list[0][0][0]
        assert record.error_kind == "unsupported_provider"
        assert knowledge_service.ingest_document.await_count == 0

    @pytest.mark.parametrize(
        "error, expected_kind",
        [
            (ProviderAuthError("auth"), "auth_failed"),
            (ProviderRateLimitError("limit"), "rate_limited"),
            (ProviderTransportError("transport"), "transport_error"),
            (ProviderResponseError("malformed"), "invalid_provider_response"),
        ],
    )
    async def test_provider_errors_map_to_generic_kinds(
        self, connector_repo, sync_repo, knowledge_service, error, expected_kind
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config

        class ExplodingAdapter:
            provider = ConnectorProvider.GITHUB

            async def fetch(self, credential, target, limit=25):
                raise error

        service = _service(
            connector_repo,
            sync_repo,
            knowledge_service,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: ExplodingAdapter()}),
        )

        with pytest.raises(ConnectorSyncError):
            await service.sync(_context(), config.id)

        assert knowledge_service.ingest_document.await_count == 0
        record = sync_repo.create_record.await_args_list[0][0][0]
        assert record.status is ConnectorSyncStatus.FAILED
        assert record.error_kind == expected_kind

    async def test_invalid_target_fails_closed(self, connector_repo, sync_repo, knowledge_service):
        config = _config(name="not-a-valid-target")
        connector_repo.get_by_id.return_value = config
        service = _service(connector_repo, sync_repo, knowledge_service)

        with pytest.raises(ConnectorSyncError):
            await service.sync(_context(), config.id)

        record = sync_repo.create_record.await_args_list[0][0][0]
        assert record.error_kind == "invalid_target"

    async def test_not_found_connector_propagates(
        self, connector_repo, sync_repo, knowledge_service
    ):
        connector_repo.get_by_id.side_effect = NotFoundError("missing")
        service = _service(connector_repo, sync_repo, knowledge_service)

        with pytest.raises(NotFoundError):
            await service.sync(_context(), _unique("missing"))

        assert sync_repo.create_record.await_count == 0

    async def test_no_credential_material_in_errors(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config

        class ExplodingAdapter:
            provider = ConnectorProvider.GITHUB

            async def fetch(self, credential, target, limit=25):
                raise ProviderTransportError("upstream exploded")

        service = _service(
            connector_repo,
            sync_repo,
            knowledge_service,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: ExplodingAdapter()}),
        )

        with pytest.raises(ConnectorSyncError) as exc_info:
            await service.sync(_context(), config.id)
        assert "upstream exploded" not in str(exc_info.value)
        assert "dev-token" not in str(exc_info.value)


class TestConnectorSyncPiiIntegration:
    """End-to-end ADR-001 boundary: provider content -> PII guard -> ingestion.

    Uses the real PostgreSQL repositories and the real Presidio-based
    PiiGuardService through KnowledgeService.
    """

    async def test_pii_is_sanitized_before_persistence(self, db):
        tenant_repo = PostgreSQLTenantRepository(db)
        connector_repo = PostgreSQLConnectorRepository(db)
        sync_repo = PostgreSQLConnectorSyncRepository(db)
        knowledge_repo = PostgreSQLKnowledgeRepository(db)

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Sync PII Tenant"))
        connector = await connector_repo.create(
            ConnectorConfig(
                id=_unique("connector"),
                tenant_id=tenant.id,
                provider=ConnectorProvider.GITHUB,
                name="example/acme",
            )
        )

        class PiiProvider:
            provider = ConnectorProvider.GITHUB

            async def fetch(self, credential, target, limit=25):
                return ProviderFetchResult(
                    provider=self.provider,
                    records=[
                        ProviderRecord(
                            source_id="pii-issue-1",
                            title="Contact support",
                            content="Contact support@example.com for onboarding.",
                        )
                    ],
                )

        service = ConnectorSyncService(
            connector_repo=connector_repo,
            sync_repo=sync_repo,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: PiiProvider()}),
            credential_store=ConnectorCredentialStore(
                raw=f'{{"{tenant.id}": {{"github": "dev-token"}}}}'
            ),
            knowledge_service=KnowledgeService(knowledge_repo),
        )

        context = _context(tenant_id=tenant.id)
        result = await service.sync(context, connector.id)
        assert result.items_fetched == 1

        documents = await knowledge_repo.list_for_tenant(tenant.id)
        assert len(documents) == 1
        assert "support@example.com" not in documents[0].content
        assert documents[0].provenance.startswith("connector:github:")

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status is ConnectorSyncStatus.SUCCESS
        assert records[0].items_fetched == 1

        await connector_repo.delete(connector.id, tenant.id)
        await tenant_repo.delete(tenant.id)
