"""Webhook automatic dispatch: integration tests (Issue #138, V2-ADR-017).

Verifies that successful webhook ingestion automatically invokes the Skill
pipeline (WebhookPipelineService.process), and that the API response reflects
the actual persisted event state after dispatch (processed / failed / received).

Tests the real ingestion → auto-dispatch → response path through the
FastAPI TestClient, with the pipeline service mocked to control
downstream execution outcomes.

Each mock side_effect creates its own ``ArcDatabase`` so the asyncpg pool
lives on the TestClient's blocking-portal event loop, avoiding the
cross-loop ``InterfaceError`` that occurs when sharing the pytest-scoped
``db`` fixture pool.
"""

import json
import os
import time
import uuid
from unittest.mock import AsyncMock

import pytest

from arc.db.connection import ArcDatabase
from arc.domain.models import Tenant, WebhookEventStatus
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository
from arc.services.webhook_ingestion import compute_signature

ENDPOINT_ID = "wh-autodispatch-demo"
SECRET = "webhook-autodispatch-test-signing-01234"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://arc:arc-dev-password@localhost:5432/arc",
)


def _unique(prefix: str) -> str:
    return f"wa-{prefix}-{uuid.uuid4().hex[:10]}"


def _provision_endpoint(
    tenant_id: str,
    endpoint_id: str = ENDPOINT_ID,
    with_action: bool = True,
):
    entry = {"tenant_id": tenant_id, "secret": SECRET}
    if with_action:
        entry["action"] = {
            "type": "skill",
            "skill_id": "skill-webhook-handler",
            "tool_calls": [{"tool_name": "echo", "input": {"source": "webhook"}}],
            "satisfied_conditions": [],
        }
    previous = os.environ.get("WEBHOOK_INGESTION_ENDPOINTS")
    os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = json.dumps({endpoint_id: entry})

    def _restore():
        if previous is None:
            os.environ.pop("WEBHOOK_INGESTION_ENDPOINTS", None)
        else:
            os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = previous

    return _restore


def _signed_headers(body: bytes, timestamp: int | None = None, secret: str = SECRET):
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return {
        "X-Arc-Timestamp": ts,
        "X-Arc-Signature": compute_signature(secret, ts, body),
    }


def _valid_body(event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or _unique("sender-event"),
            "event_type": "issue.opened",
            "data": {"note": "test-webhook"},
        }
    ).encode("utf-8")


@pytest.fixture
async def webhook_tenant(db):
    tenants = PostgreSQLTenantRepository(db)
    created = await tenants.create(Tenant(id=_unique("tenant"), name="AutoDispatch Tenant"))
    yield created
    await tenants.delete(created.id)


def _make_mock_pipeline(*, succeed: bool = True):
    """Create a mock WebhookPipelineService.

    Each side_effect spins up its own ``ArcDatabase`` so the asyncpg pool
    runs on the TestClient's blocking-portal event loop instead of
    pytest's asyncio loop.
    """
    mock = AsyncMock()

    async def _process_success(tenant_id, event_id):
        database = ArcDatabase(DATABASE_URL)
        await database.connect()
        try:
            repo = PostgreSQLWebhookEventRepository(database)
            await repo.claim_for_processing(event_id, tenant_id)
            await repo.mark_processed(event_id, tenant_id)
        finally:
            await database.disconnect()

    async def _process_failure(tenant_id, event_id):
        from arc.services.webhook_pipeline import WebhookProcessingError

        database = ArcDatabase(DATABASE_URL)
        await database.connect()
        try:
            repo = PostgreSQLWebhookEventRepository(database)
            await repo.claim_for_processing(event_id, tenant_id)
            await repo.mark_failed(event_id, tenant_id, "downstream_execution_error")
        finally:
            await database.disconnect()
        raise WebhookProcessingError("downstream_execution_error", "skill execution failed")

    mock.process = AsyncMock(side_effect=_process_success if succeed else _process_failure)
    return mock


def _patch_app_context(mock_pipeline):
    from arc.api.controllers import app_context as real_ctx

    original = real_ctx.services._services.get("webhook_pipeline_service")
    real_ctx.services._services["webhook_pipeline_service"] = mock_pipeline

    class _Restore:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            if original is not None:
                real_ctx.services._services["webhook_pipeline_service"] = original
            else:
                real_ctx.services._services.pop("webhook_pipeline_service", None)

    return _Restore()


class TestAutoDispatchSuccess:
    def test_successful_dispatch_returns_processed(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            mock_pipeline = _make_mock_pipeline(succeed=True)
            with _patch_app_context(mock_pipeline):
                body = _valid_body()
                response = client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["duplicate"] is False
        assert envelope["tenant_id"] == webhook_tenant.id
        assert envelope["endpoint_id"] == ENDPOINT_ID
        assert envelope["status"] == "processed"
        mock_pipeline.process.assert_awaited_once()

    def test_successful_dispatch_calls_pipeline_with_correct_args(self, client, webhook_tenant):
        mock_pipeline = _make_mock_pipeline(succeed=True)
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            with _patch_app_context(mock_pipeline):
                body = _valid_body()
                client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        call_args = mock_pipeline.process.call_args
        assert call_args[0][0] == webhook_tenant.id
        assert isinstance(call_args[0][1], str)

    async def test_event_reaches_processed_in_database(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            mock_pipeline = _make_mock_pipeline(succeed=True)
            body = _valid_body()
            event_id = json.loads(body)["event_id"]
            with _patch_app_context(mock_pipeline):
                response = client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        assert response.status_code == 200
        database = ArcDatabase(DATABASE_URL)
        await database.connect()
        try:
            repo = PostgreSQLWebhookEventRepository(database)
            event = await repo.get_by_event_id(event_id, webhook_tenant.id)
            assert event.status is WebhookEventStatus.PROCESSED
        finally:
            await database.disconnect()


class TestAutoDispatchDuplicateSafety:
    def test_duplicate_skips_dispatch(self, client, webhook_tenant):
        mock_pipeline = _make_mock_pipeline(succeed=True)
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            body = _valid_body()
            with _patch_app_context(mock_pipeline):
                first = client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
                second = client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert second.json()["id"] == first.json()["id"]
        assert mock_pipeline.process.await_count == 1


class TestAutoDispatchDownstreamFailure:
    def test_downstream_failure_returns_failed_status(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            mock_pipeline = _make_mock_pipeline(succeed=False)
            body = _valid_body()
            with _patch_app_context(mock_pipeline):
                response = client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["status"] == "failed"
        assert envelope["duplicate"] is False

    async def test_downstream_failure_persists_failed_state(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            mock_pipeline = _make_mock_pipeline(succeed=False)
            body = _valid_body()
            event_id = json.loads(body)["event_id"]
            with _patch_app_context(mock_pipeline):
                client.post(
                    f"/webhooks/{ENDPOINT_ID}/events",
                    content=body,
                    headers=_signed_headers(body),
                )
        finally:
            restore()

        database = ArcDatabase(DATABASE_URL)
        await database.connect()
        try:
            repo = PostgreSQLWebhookEventRepository(database)
            event = await repo.get_by_event_id(event_id, webhook_tenant.id)
            assert event.status is WebhookEventStatus.FAILED
        finally:
            await database.disconnect()


class TestAutoDispatchNoActionConfig:
    def test_no_action_returns_failed_not_received(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=False)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["status"] == "failed"


class TestAutoDispatchInvalidHMAC:
    def test_invalid_hmac_returns_401(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body, secret="wrong-secret-value"),
            )
        finally:
            restore()

        assert response.status_code == 401

    def test_stale_timestamp_returns_401(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=True)
        try:
            body = _valid_body()
            stale = int(time.time()) - 301
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body, timestamp=stale),
            )
        finally:
            restore()

        assert response.status_code == 401


class TestAutoDispatchManualRecoverySemantics:
    def test_process_endpoint_rejects_failed_event(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id, with_action=False)
        try:
            body = _valid_body()
            ingest_response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest_response.status_code == 200
            event_id = ingest_response.json()["event_id"]
        finally:
            restore()

        response = client.post(
            f"/tenants/{webhook_tenant.id}/webhooks/process?event_id={event_id}",
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# WebhookIngestionService.get_event_by_id — public API contract
# ---------------------------------------------------------------------------


class TestGetEventById:
    """Verify the public get_event_by_id service method (Finding #2 fix).

    The auto-dispatch controller path calls get_event_by_id after
    process() to re-read the persisted event state. These tests verify
    that the re-read path works correctly end-to-end.
    """

    def test_re_read_returns_persisted_event(self, client, webhook_tenant):
        """After ingestion + dispatch, the response reflects the re-read state."""
        restore = _provision_endpoint(webhook_tenant.id, with_action=False)
        try:
            body = _valid_body()
            ingest_response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest_response.status_code == 200
            data = ingest_response.json()
            assert data["event_id"]
            assert data["status"] in ("received", "failed", "processing")
        finally:
            restore()

    def test_duplicate_ingest_returns_same_event(self, client, webhook_tenant):
        """Duplicate delivery returns the original event (no re-dispatch)."""
        restore = _provision_endpoint(webhook_tenant.id, with_action=False)
        try:
            event_id = _unique("dedup")
            body = _valid_body(event_id)
            first = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert first.status_code == 200
            assert first.json()["event_id"] == event_id

            second = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert second.status_code == 200
            assert second.json()["event_id"] == event_id
            assert second.json()["duplicate"] is True
        finally:
            restore()
