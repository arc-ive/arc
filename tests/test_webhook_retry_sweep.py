"""Webhook retry sweep: dedicated tests (Issue #186, V2-ADR-019, TRD 22).

Covers:
- _get_configured_tenant_ids: env parsing
- _process_retryable_for_tenant: claim + re-process retryable events
- _sweep_stuck_for_tenant: stuck processing → dead_letter
- WebhookRetrySweepRunner: start/stop lifecycle
- Error resilience: sweep continues after transient failures
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arc.domain.models import (
    SkillExecutionResult,
    SkillExecutionStatus,
    Tenant,
    WebhookEvent,
    WebhookEventStatus,
)
from arc.services.webhook_config import (
    WebhookEndpointStore,
)
from arc.services.webhook_pipeline import WebhookPipelineService
from arc.services.webhook_retry_sweep import (
    WebhookRetrySweepRunner,
    _get_configured_tenant_ids,
    _process_retryable_for_tenant,
    _sweep_stuck_for_tenant,
)


def _unique(prefix: str) -> str:
    return f"wrs-{prefix}-{uuid.uuid4().hex[:10]}"


def _make_event(
    tenant_id: str,
    event_id: str | None = None,
    status: WebhookEventStatus = WebhookEventStatus.RECEIVED,
    created_at: datetime | None = None,
    retry_count: int = 0,
    next_retry_at: datetime | None = None,
) -> WebhookEvent:
    return WebhookEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        endpoint_id="github-demo",
        event_id=event_id or _unique("evt"),
        event_type="push",
        status=status,
        payload_size_bytes=128,
        created_at=created_at or datetime.now(timezone.utc),
        retry_count=retry_count,
        next_retry_at=next_retry_at,
    )


class FakeRepository:
    """In-memory WebhookEventRepository for retry sweep tests."""

    def __init__(self):
        self._events: dict[str, WebhookEvent] = {}

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        self._events[event.id] = event
        return event

    async def get_by_event_id(self, event_id: str, tenant_id: str) -> WebhookEvent:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                return e
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[WebhookEvent]:
        return [e for e in self._events.values() if e.tenant_id == tenant_id][:limit]

    async def claim_for_retry(self, tenant_id: str, limit: int = 10) -> List[WebhookEvent]:
        now = datetime.now(timezone.utc)
        claimed = []
        for e in list(self._events.values()):
            if (
                e.tenant_id == tenant_id
                and e.status is WebhookEventStatus.RETRYING
                and e.next_retry_at is not None
                and e.next_retry_at <= now
            ):
                e.status = WebhookEventStatus.PROCESSING
                claimed.append(e)
                if len(claimed) >= limit:
                    break
        return claimed

    async def claim_for_processing(self, event_id: str, tenant_id: str) -> WebhookEvent:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.RECEIVED:
                    from arc.db.connection import NotFoundError

                    raise NotFoundError("not in received status")
                e.status = WebhookEventStatus.PROCESSING
                return e
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

    async def claim_single_for_retry(self, event_id: str, tenant_id: str) -> Optional[WebhookEvent]:
        now = datetime.now(timezone.utc)
        for e in self._events.values():
            if (
                e.event_id == event_id
                and e.tenant_id == tenant_id
                and e.status in (WebhookEventStatus.RETRYING, WebhookEventStatus.PROCESSING)
                and e.next_retry_at is not None
                and e.next_retry_at <= now
            ):
                e.status = WebhookEventStatus.PROCESSING
                return e
        return None

    async def mark_processed(self, event_id: str, tenant_id: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                e.status = WebhookEventStatus.PROCESSED
                e.processed_at = datetime.now(timezone.utc)
                return

    async def mark_failed(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                e.status = WebhookEventStatus.FAILED
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return

    async def mark_retrying(
        self, event_id: str, tenant_id: str, retry_count: int, next_retry_at: datetime
    ) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                e.status = WebhookEventStatus.RETRYING
                e.retry_count = retry_count
                e.next_retry_at = next_retry_at
                return

    async def mark_dead_letter(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                e.status = WebhookEventStatus.DEAD_LETTER
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return

    async def sweep_stuck_processing(
        self, tenant_id: str, stuck_threshold_seconds: int = 600
    ) -> List[WebhookEvent]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stuck_threshold_seconds)
        return [
            e
            for e in self._events.values()
            if (
                e.tenant_id == tenant_id
                and e.status is WebhookEventStatus.PROCESSING
                and e.created_at < cutoff
            )
        ]


def _build_pipeline_service():
    """Build a WebhookPipelineService with in-memory fakes."""
    tenant_id = "tenant-1"
    endpoint_id = "github-demo"
    tenant = Tenant(id=tenant_id, name="Test Corp")

    endpoint_data = {
        "tenant_id": tenant_id,
        "secret": "a" * 32,
        "action": {
            "type": "skill",
            "skill_id": "skill-1",
            "tool_calls": [{"tool_name": "noop", "input": {}}],
            "satisfied_conditions": [],
        },
    }
    endpoint_store = WebhookEndpointStore(raw=json.dumps({endpoint_id: endpoint_data}))

    repo = FakeRepository()

    tenant_repo = MagicMock()
    tenant_repo.get_by_id = AsyncMock(return_value=tenant)

    skill_execution = AsyncMock()
    skill_execution.execute = AsyncMock(
        return_value=SkillExecutionResult(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            principal_id="system:webhook",
            skill_id="skill-1",
            skill_name="test-skill",
            skill_version="1.0",
            status=SkillExecutionStatus.SUCCEEDED,
        )
    )

    pii_guard = MagicMock()
    pii_guard.sanitize = MagicMock(return_value=MagicMock(sanitized_text="push"))

    svc = WebhookPipelineService(
        webhook_repository=repo,
        tenant_repository=tenant_repo,
        endpoint_store=endpoint_store,
        skill_execution_service=skill_execution,
        pii_guard=pii_guard,
    )
    return svc, repo


# --- _get_configured_tenant_ids ---


class TestGetConfiguredTenantIds:
    def test_extracts_tenant_ids_from_env(self):
        env = {
            "WEBHOOK_INGESTION_ENDPOINTS": json.dumps(
                {
                    "ep1": {"tenant_id": "t-aaa", "secret": "s1"},
                    "ep2": {"tenant_id": "t-bbb", "secret": "s2"},
                }
            )
        }
        with patch.dict(os.environ, env, clear=False):
            result = _get_configured_tenant_ids()
        assert result == {"t-aaa", "t-bbb"}

    def test_deduplicates_tenant_ids(self):
        env = {
            "WEBHOOK_INGESTION_ENDPOINTS": json.dumps(
                {
                    "ep1": {"tenant_id": "t-shared", "secret": "s1"},
                    "ep2": {"tenant_id": "t-shared", "secret": "s2"},
                }
            )
        }
        with patch.dict(os.environ, env, clear=False):
            result = _get_configured_tenant_ids()
        assert result == {"t-shared"}

    def test_empty_env_returns_empty_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEBHOOK_INGESTION_ENDPOINTS", None)
            result = _get_configured_tenant_ids()
        assert result == set()

    def test_invalid_json_returns_empty_set(self):
        env = {"WEBHOOK_INGESTION_ENDPOINTS": "not-json"}
        with patch.dict(os.environ, env, clear=False):
            result = _get_configured_tenant_ids()
        assert result == set()

    def test_non_dict_json_returns_empty_set(self):
        env = {"WEBHOOK_INGESTION_ENDPOINTS": json.dumps(["list", "not", "dict"])}
        with patch.dict(os.environ, env, clear=False):
            result = _get_configured_tenant_ids()
        assert result == set()

    def test_skips_entries_without_tenant_id(self):
        env = {
            "WEBHOOK_INGESTION_ENDPOINTS": json.dumps(
                {
                    "ep1": {"tenant_id": "t-ok", "secret": "s1"},
                    "ep2": {"secret": "s2"},
                }
            )
        }
        with patch.dict(os.environ, env, clear=False):
            result = _get_configured_tenant_ids()
        assert result == {"t-ok"}


# --- _process_retryable_for_tenant ---


@pytest.mark.asyncio
class TestProcessRetryableForTenant:
    async def test_retries_due_events(self):
        svc, repo = _build_pipeline_service()
        event = _make_event(
            "tenant-1",
            event_id="evt-retry-1",
            status=WebhookEventStatus.RETRYING,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        await repo.create(event)

        await _process_retryable_for_tenant(svc, "tenant-1")

        stored = await repo.get_by_event_id("evt-retry-1", "tenant-1")
        assert stored.status is WebhookEventStatus.PROCESSED

    async def test_skips_future_retry_events(self):
        svc, repo = _build_pipeline_service()
        event = _make_event(
            "tenant-1",
            event_id="evt-future",
            status=WebhookEventStatus.RETRYING,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await repo.create(event)

        await _process_retryable_for_tenant(svc, "tenant-1")

        stored = await repo.get_by_event_id("evt-future", "tenant-1")
        assert stored.status is WebhookEventStatus.RETRYING

    async def test_no_retryable_events_is_noop(self):
        svc, repo = _build_pipeline_service()
        await _process_retryable_for_tenant(svc, "tenant-1")

    async def test_claim_failure_does_not_crash(self):
        svc, repo = _build_pipeline_service()
        repo.claim_for_retry = AsyncMock(side_effect=RuntimeError("db down"))

        await _process_retryable_for_tenant(svc, "tenant-1")

    async def test_process_failure_does_not_crash(self):
        svc, repo = _build_pipeline_service()
        event = _make_event(
            "tenant-1",
            event_id="evt-fail",
            status=WebhookEventStatus.RETRYING,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        await repo.create(event)

        svc.process = AsyncMock(side_effect=RuntimeError("processing error"))

        await _process_retryable_for_tenant(svc, "tenant-1")

        # Event was claimed (RETRYING→PROCESSING) but process() failed,
        # so it remains in PROCESSING status.
        stored = await repo.get_by_event_id("evt-fail", "tenant-1")
        assert stored.status is WebhookEventStatus.PROCESSING


# --- _sweep_stuck_for_tenant ---


@pytest.mark.asyncio
class TestSweepStuckForTenant:
    async def test_stuck_event_moves_to_dead_letter(self):
        svc, repo = _build_pipeline_service()
        old_event = _make_event(
            "tenant-1",
            event_id="evt-stuck",
            status=WebhookEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        )
        await repo.create(old_event)

        await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)

        stored = await repo.get_by_event_id("evt-stuck", "tenant-1")
        assert stored.status is WebhookEventStatus.DEAD_LETTER
        assert stored.error_kind == "stuck_processing"

    async def test_recent_event_not_swept(self):
        svc, repo = _build_pipeline_service()
        recent = _make_event(
            "tenant-1",
            event_id="evt-recent",
            status=WebhookEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        await repo.create(recent)

        await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)

        stored = await repo.get_by_event_id("evt-recent", "tenant-1")
        assert stored.status is WebhookEventStatus.PROCESSING

    async def test_no_stuck_events_is_noop(self):
        svc, repo = _build_pipeline_service()
        await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)

    async def test_claim_failure_does_not_crash(self):
        svc, repo = _build_pipeline_service()
        repo.sweep_stuck_processing = AsyncMock(side_effect=RuntimeError("db down"))

        await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)

    async def test_mark_dead_letter_failure_does_not_crash(self):
        svc, repo = _build_pipeline_service()
        old_event = _make_event(
            "tenant-1",
            event_id="evt-fail-mark",
            status=WebhookEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        )
        await repo.create(old_event)

        repo.mark_dead_letter = AsyncMock(side_effect=RuntimeError("db down"))

        await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)


# --- WebhookRetrySweepRunner lifecycle ---


@pytest.mark.asyncio
class TestWebhookRetrySweepRunnerLifecycle:
    async def test_start_stop_lifecycle(self):
        svc, _ = _build_pipeline_service()
        runner = WebhookRetrySweepRunner(svc, retry_interval_seconds=1)
        await runner.start()
        assert runner._task is not None
        assert not runner._task.done()
        await runner.stop()
        assert runner._task is None

    async def test_start_is_idempotent(self):
        svc, _ = _build_pipeline_service()
        runner = WebhookRetrySweepRunner(svc, retry_interval_seconds=60)
        await runner.start()
        task1 = runner._task
        await runner.start()
        assert runner._task is task1
        await runner.stop()

    async def test_stop_is_idempotent(self):
        svc, _ = _build_pipeline_service()
        runner = WebhookRetrySweepRunner(svc, retry_interval_seconds=60)
        await runner.start()
        await runner.stop()
        await runner.stop()

    async def test_stop_cancels_running_task(self):
        svc, _ = _build_pipeline_service()
        runner = WebhookRetrySweepRunner(svc, retry_interval_seconds=60)
        await runner.start()
        task = runner._task
        assert task is not None
        assert not task.done()
        await runner.stop()
        assert runner._task is None
        assert task.cancelled() or task.done()
