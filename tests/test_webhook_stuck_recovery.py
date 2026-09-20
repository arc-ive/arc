"""Stuck-processing webhook recovery: retry once before dead-letter (Issue #178).

Exercises the recovery path in ``_sweep_stuck_for_tenant`` with a real
``WebhookPipelineService`` over an in-memory repository that mirrors the
production SQL state guards (status-gated transitions, tenant scoping,
due-date filtering). Final persisted states are asserted, not mock calls.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

from arc.domain.models import (
    SkillExecutionResult,
    SkillExecutionStatus,
    Tenant,
    WebhookEvent,
    WebhookEventStatus,
)
from arc.services.webhook_config import WebhookEndpointStore
from arc.services.webhook_pipeline import (
    WebhookPipelineService,
    compute_idempotency_key,
)
from arc.services.webhook_retry_sweep import (
    _process_retryable_for_tenant,
    _sweep_stuck_for_tenant,
)

STUCK_THRESHOLD_SECONDS = 600


def _unique(prefix: str) -> str:
    return f"wsr-{prefix}-{uuid.uuid4().hex[:10]}"


def _make_event(
    tenant_id: str,
    event_id: str | None = None,
    status: WebhookEventStatus = WebhookEventStatus.PROCESSING,
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


def _stuck_event(tenant_id: str, event_id: str | None = None) -> WebhookEvent:
    """An event stuck in processing beyond the sweep threshold."""
    return _make_event(
        tenant_id,
        event_id=event_id,
        status=WebhookEventStatus.PROCESSING,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
    )


class FakeRepository:
    """In-memory repository mirroring the production SQL state guards."""

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

    async def claim_single_for_retry(self, event_id: str, tenant_id: str) -> Optional[WebhookEvent]:
        now = datetime.now(timezone.utc)
        for e in self._events.values():
            if (
                e.event_id == event_id
                and e.tenant_id == tenant_id
                and e.status is WebhookEventStatus.RETRYING
                and e.next_retry_at is not None
                and e.next_retry_at <= now
            ):
                e.status = WebhookEventStatus.PROCESSING
                return e
        return None

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

    async def list_due_retrying(self, tenant_id: str, limit: int = 10) -> List[WebhookEvent]:
        now = datetime.now(timezone.utc)
        return [
            e
            for e in list(self._events.values())
            if (
                e.tenant_id == tenant_id
                and e.status is WebhookEventStatus.RETRYING
                and e.next_retry_at is not None
                and e.next_retry_at <= now
            )
        ][:limit]

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

    async def mark_processed(self, event_id: str, tenant_id: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    from arc.db.connection import NotFoundError

                    raise NotFoundError("not in processing status")
                e.status = WebhookEventStatus.PROCESSED
                e.processed_at = datetime.now(timezone.utc)
                return
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

    async def mark_failed(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    from arc.db.connection import NotFoundError

                    raise NotFoundError("not in processing status")
                e.status = WebhookEventStatus.FAILED
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

    async def mark_retrying(
        self, event_id: str, tenant_id: str, retry_count: int, next_retry_at: datetime
    ) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    from arc.db.connection import NotFoundError

                    raise NotFoundError("not in processing status")
                e.status = WebhookEventStatus.RETRYING
                e.retry_count = retry_count
                e.next_retry_at = next_retry_at
                return
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

    async def mark_dead_letter(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status not in (WebhookEventStatus.PROCESSING, WebhookEventStatus.RETRYING):
                    from arc.db.connection import NotFoundError

                    raise NotFoundError("not in retryable status")
                e.status = WebhookEventStatus.DEAD_LETTER
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return
        from arc.db.connection import NotFoundError

        raise NotFoundError("missing")

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


def _success_result(tenant_id: str) -> SkillExecutionResult:
    return SkillExecutionResult(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        principal_id="system:webhook",
        skill_id="skill-1",
        skill_name="test-skill",
        skill_version="1.0",
        status=SkillExecutionStatus.SUCCEEDED,
    )


def _build_pipeline(tenant_id: str, skill_side_effect=None, idempotency_calls=None):
    """Real pipeline service over fakes; records downstream idempotency keys."""

    async def _execute(*args, **kwargs):
        if idempotency_calls is not None:
            idempotency_calls.append(kwargs.get("idempotency_key"))
        if skill_side_effect is not None:
            raise skill_side_effect
        return _success_result(tenant_id)

    endpoint_store = WebhookEndpointStore(
        raw=json.dumps(
            {
                "github-demo": {
                    "tenant_id": tenant_id,
                    "secret": "a" * 32,
                    "action": {
                        "type": "skill",
                        "skill_id": "skill-1",
                        "tool_calls": [{"tool_name": "noop", "input": {}}],
                        "satisfied_conditions": [],
                    },
                }
            }
        )
    )
    repo = FakeRepository()
    tenant_repo = MagicMock()
    tenant_repo.get_by_id = AsyncMock(return_value=Tenant(id=tenant_id, name="Acme"))
    skill_execution = AsyncMock()
    skill_execution.execute = AsyncMock(side_effect=_execute)
    pii_guard = MagicMock()
    pii_guard.sanitize = MagicMock(return_value=MagicMock(sanitized_text="push"))
    svc = WebhookPipelineService(
        webhook_repository=repo,
        tenant_repository=tenant_repo,
        endpoint_store=endpoint_store,
        skill_execution_service=skill_execution,
        pii_guard=pii_guard,
    )
    return svc, repo, skill_execution


class TestStuckEventRecovery:
    async def test_stuck_event_recovered_to_processed(self):
        """TEST 1 — successful recovery ends processed, never dead-lettered."""
        svc, repo, skill = _build_pipeline("tenant-1")
        event = _stuck_event("tenant-1", event_id="evt-recover")
        await repo.create(event)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        stored = await repo.get_by_event_id("evt-recover", "tenant-1")
        assert stored.status is WebhookEventStatus.PROCESSED
        assert stored.retry_count == 0  # resumed attempt, not a new one
        assert skill.execute.await_count == 1

    async def test_failed_recovery_moves_to_dead_letter(self):
        """TEST 2 — failed recovery ends dead_letter after exactly one attempt."""
        svc, repo, skill = _build_pipeline("tenant-1", skill_side_effect=RuntimeError("boom"))
        event = _stuck_event("tenant-1", event_id="evt-fail")
        await repo.create(event)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        stored = await repo.get_by_event_id("evt-fail", "tenant-1")
        assert stored.status is WebhookEventStatus.DEAD_LETTER
        assert stored.error_kind == "stuck_processing"
        assert skill.execute.await_count == 1

    async def test_recovery_uses_stable_idempotency_key_once(self):
        """TEST 3/4 — one downstream side effect; second sweep is a no-op."""
        calls: list = []
        svc, repo, skill = _build_pipeline("tenant-1", idempotency_calls=calls)
        event = _stuck_event("tenant-1", event_id="evt-idem")
        await repo.create(event)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)
        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        assert skill.execute.await_count == 1
        assert calls == [compute_idempotency_key("tenant-1", "evt-idem")]
        stored = await repo.get_by_event_id("evt-idem", "tenant-1")
        assert stored.status is WebhookEventStatus.PROCESSED

    async def test_dead_lettered_event_is_not_recovered_again(self):
        """TEST 4 (failure path) — exactly one recovery attempt per stuck event."""
        svc, repo, skill = _build_pipeline("tenant-1", skill_side_effect=RuntimeError("boom"))
        event = _stuck_event("tenant-1", event_id="evt-once")
        await repo.create(event)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)
        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        assert skill.execute.await_count == 1
        stored = await repo.get_by_event_id("evt-once", "tenant-1")
        assert stored.status is WebhookEventStatus.DEAD_LETTER

    async def test_retryable_path_unchanged(self):
        """TEST 5 — due retryable events process; future ones stay scheduled."""
        svc, repo, skill = _build_pipeline("tenant-1")
        due = _make_event(
            "tenant-1",
            event_id="evt-due",
            status=WebhookEventStatus.RETRYING,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        future = _make_event(
            "tenant-1",
            event_id="evt-future",
            status=WebhookEventStatus.RETRYING,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        await repo.create(due)
        await repo.create(future)

        await _process_retryable_for_tenant(svc, "tenant-1")

        assert (await repo.get_by_event_id("evt-due", "tenant-1")).status is (
            WebhookEventStatus.PROCESSED
        )
        assert (await repo.get_by_event_id("evt-future", "tenant-1")).status is (
            WebhookEventStatus.RETRYING
        )

    async def test_recent_processing_event_untouched(self):
        """TEST 6 — below-threshold processing events are never recovered."""
        svc, repo, skill = _build_pipeline("tenant-1")
        recent = _make_event(
            "tenant-1",
            event_id="evt-recent",
            status=WebhookEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        await repo.create(recent)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        assert (await repo.get_by_event_id("evt-recent", "tenant-1")).status is (
            WebhookEventStatus.PROCESSING
        )
        assert skill.execute.await_count == 0

    async def test_tenant_isolation(self):
        """TEST 7 — sweeping tenant A never touches tenant B's stuck event."""
        svc, repo, skill = _build_pipeline("tenant-1")
        other = _stuck_event("tenant-2", event_id="evt-other")
        await repo.create(other)

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        assert (await repo.get_by_event_id("evt-other", "tenant-2")).status is (
            WebhookEventStatus.PROCESSING
        )
        assert skill.execute.await_count == 0

    async def test_one_bad_event_does_not_stop_sweep(self):
        """TEST 8 — dead-letter failure is contained; other events recover."""
        svc, repo, skill = _build_pipeline("tenant-1", skill_side_effect=RuntimeError("boom"))
        first = _stuck_event("tenant-1", event_id="evt-first")
        second = _stuck_event("tenant-1", event_id="evt-second")
        await repo.create(first)
        await repo.create(second)

        real_mark_dead_letter = repo.mark_dead_letter

        async def _poisoned(event_id, tenant_id, error_kind):
            if event_id == "evt-first":
                raise RuntimeError("dead-letter store down")
            await real_mark_dead_letter(event_id, tenant_id, error_kind)

        repo.mark_dead_letter = _poisoned

        await _sweep_stuck_for_tenant(svc, "tenant-1", STUCK_THRESHOLD_SECONDS)

        assert (await repo.get_by_event_id("evt-second", "tenant-1")).status is (
            WebhookEventStatus.DEAD_LETTER
        )
        assert skill.execute.await_count == 2
