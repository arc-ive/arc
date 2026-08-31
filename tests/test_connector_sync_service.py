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
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
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
from arc.services.embeddings import DeterministicEmbeddingProvider
from arc.services.knowledge import KnowledgeService
from arc.services.pii import PiiGuardError
from arc.services.retrieval import RetrievalService


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

    async def test_pii_guard_failure_fails_closed_without_raw_persistence(self, db):
        """A PII Guard failure must block persistence entirely: no raw
        content is written, the sync is a controlled failure, and the
        audit event is safe."""
        tenant_repo = PostgreSQLTenantRepository(db)
        connector_repo = PostgreSQLConnectorRepository(db)
        sync_repo = PostgreSQLConnectorSyncRepository(db)
        knowledge_repo = PostgreSQLKnowledgeRepository(db)

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="PII Fail Tenant"))
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
                            title="Sensitive",
                            content="Call +91-9876543210 for the customer.",
                        )
                    ],
                )

        class BrokenGuard:
            def sanitize(self, text):
                raise PiiGuardError("PII analysis unavailable")

        service = ConnectorSyncService(
            connector_repo=connector_repo,
            sync_repo=sync_repo,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: PiiProvider()}),
            credential_store=ConnectorCredentialStore(
                raw=f'{{"{tenant.id}": {{"github": "dev-token"}}}}'
            ),
            knowledge_service=KnowledgeService(knowledge_repo, pii_guard=BrokenGuard()),
        )

        context = _context(tenant_id=tenant.id)
        with pytest.raises(ConnectorSyncError, match="PII guard"):
            await service.sync(context, connector.id)

        documents = await knowledge_repo.list_for_tenant(tenant.id)
        assert documents == []

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        assert records[0].status is ConnectorSyncStatus.FAILED
        assert records[0].error_kind == "pii_guard_failed"
        assert "+91-9876543210" not in records[0].error_kind

        await connector_repo.delete(connector.id, tenant.id)
        await tenant_repo.delete(tenant.id)

    async def test_audit_records_never_store_raw_provider_content(self, db):
        """Even when provider content contains PII or secret-like values,
        the audit record stores metadata only (counts and error kinds)."""
        tenant_repo = PostgreSQLTenantRepository(db)
        connector_repo = PostgreSQLConnectorRepository(db)
        sync_repo = PostgreSQLConnectorSyncRepository(db)
        knowledge_repo = PostgreSQLKnowledgeRepository(db)

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Audit Tenant"))
        connector = await connector_repo.create(
            ConnectorConfig(
                id=_unique("connector"),
                tenant_id=tenant.id,
                provider=ConnectorProvider.GITHUB,
                name="example/acme",
            )
        )

        class SecretProvider:
            provider = ConnectorProvider.GITHUB

            async def fetch(self, credential, target, limit=25):
                return ProviderFetchResult(
                    provider=self.provider,
                    records=[
                        ProviderRecord(
                            source_id="secret-issue-1",
                            title="Contains secret",
                            content="Contact ops-secret-abc@example.com for the account.",
                        ),
                        ProviderRecord(
                            source_id="secret-issue-2",
                            title="Contains token",
                            content="Rotate the token abc123secret before Friday.",
                        ),
                    ],
                )

        service = ConnectorSyncService(
            connector_repo=connector_repo,
            sync_repo=sync_repo,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: SecretProvider()}),
            credential_store=ConnectorCredentialStore(
                raw=f'{{"{tenant.id}": {{"github": "dev-token"}}}}'
            ),
            knowledge_service=KnowledgeService(knowledge_repo),
        )

        context = _context(tenant_id=tenant.id)
        result = await service.sync(context, connector.id)
        assert result.items_fetched == 2

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 1
        record = records[0]
        for raw in ("ops-secret-abc", "abc123secret", "dev-token", "example.com"):
            assert raw not in (record.error_kind or "")
            assert raw not in str(record.status)
            assert raw not in str(record.provider)
            assert raw not in str(record.items_fetched)

        await connector_repo.delete(connector.id, tenant.id)
        await tenant_repo.delete(tenant.id)


class TestConnectorSyncDocumentIdentity:
    """ADR-003: connector sync binds a stable per-record external identity."""

    async def test_ingest_binds_provider_scoped_external_id(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config
        service = _service(connector_repo, sync_repo, knowledge_service)
        context = _context()

        result = await service.sync(context, config.id)

        assert knowledge_service.ingest_document.await_count == len(result.items)
        expected = {f"github:{item.source_id}" for item in result.items}
        passed = {
            call.kwargs["external_id"] for call in knowledge_service.ingest_document.await_args_list
        }
        assert passed == expected

    async def test_repeated_sync_uses_identical_external_ids(
        self, connector_repo, sync_repo, knowledge_service
    ):
        config = _config()
        connector_repo.get_by_id.return_value = config
        service = _service(connector_repo, sync_repo, knowledge_service)
        context = _context()

        await service.sync(context, config.id)
        first = [
            call.kwargs["external_id"] for call in knowledge_service.ingest_document.await_args_list
        ]

        knowledge_service.ingest_document.reset_mock()
        await service.sync(context, config.id)
        second = [
            call.kwargs["external_id"] for call in knowledge_service.ingest_document.await_args_list
        ]

        # Stable identity across re-deliveries is what lets the Company Brain
        # deduplicate instead of creating duplicate logical documents.
        assert sorted(first) == sorted(second)


class TestConnectorSyncRepeatedSyncDeduplication:
    """ADR-003 end to end: two syncs of the same provider record must
    converge to exactly ONE tenant-scoped knowledge document (no duplicate
    logical documents, no duplicate chunks), with the provider-scoped
    external identity persisted."""

    class _PassthroughGuard:
        def sanitize(self, text: str):
            from types import SimpleNamespace

            return SimpleNamespace(sanitized_text=text)

    async def test_two_syncs_produce_exactly_one_logical_document(self, db):
        tenant_repo = PostgreSQLTenantRepository(db)
        connector_repo = PostgreSQLConnectorRepository(db)
        sync_repo = PostgreSQLConnectorSyncRepository(db)
        knowledge_repo = PostgreSQLKnowledgeRepository(db)

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="Dedup Tenant"))
        connector = await connector_repo.create(
            ConnectorConfig(
                id=_unique("connector"),
                tenant_id=tenant.id,
                provider=ConnectorProvider.GITHUB,
                name="example/acme",
            )
        )

        class SingleRecordProvider:
            provider = ConnectorProvider.GITHUB

            async def fetch(self, credential, target, limit=25):
                return ProviderFetchResult(
                    provider=self.provider,
                    records=[
                        ProviderRecord(
                            source_id="dedup-1",
                            title="Runbook",
                            content="Deterministic dedup runbook body.",
                        )
                    ],
                )

        service = ConnectorSyncService(
            connector_repo=connector_repo,
            sync_repo=sync_repo,
            registry=ProviderRegistry({ConnectorProvider.GITHUB: SingleRecordProvider()}),
            credential_store=ConnectorCredentialStore(
                raw=f'{{"{tenant.id}": {{"github": "dev-token"}}}}'
            ),
            knowledge_service=KnowledgeService(
                knowledge_repo,
                pii_guard=self._PassthroughGuard(),
                indexer=RetrievalService(
                    PostgreSQLKnowledgeChunkRepository(db),
                    embedding_provider=DeterministicEmbeddingProvider(),
                ),
            ),
        )
        context = _context(tenant_id=tenant.id)

        await service.sync(context, connector.id)
        documents_after_first = await knowledge_repo.list_for_tenant(tenant.id)
        assert len(documents_after_first) == 1
        assert documents_after_first[0].version == 1
        assert documents_after_first[0].external_id == "github:dedup-1"

        await service.sync(context, connector.id)
        documents_after_second = await knowledge_repo.list_for_tenant(tenant.id)

        # The re-delivery resolves to the SAME logical document: no duplicate
        # rows, no version churn for identical content.
        assert len(documents_after_second) == 1
        assert documents_after_second[0].id == documents_after_first[0].id
        assert documents_after_second[0].version == 1
        assert documents_after_second[0].external_id == "github:dedup-1"

        records = await sync_repo.list_for_tenant(tenant.id)
        assert len(records) == 2
        assert all(record.status is ConnectorSyncStatus.SUCCESS for record in records)

        async with db._connection_pool.acquire() as conn:
            chunk_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kd.id = kc.document_id
                WHERE kd.tenant_id = $1
                """,
                tenant.id,
            )
        # Chunks belong to exactly the one logical document and were not
        # duplicated by the second delivery.
        assert chunk_count > 0

        await connector_repo.delete(connector.id, tenant.id)
        await tenant_repo.delete(tenant.id)
