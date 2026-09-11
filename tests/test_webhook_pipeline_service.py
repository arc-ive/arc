"""Webhook downstream processing pipeline: unit tests (Issue #102, #136).

Exercises the webhook-to-Skill execution pipeline with in-memory fakes:
atomic claiming, downstream delegation, success/failure transitions,
error kinds, PII guard integration, the "at most one processor" contract,
and the retry/backoff pipeline (V2-ADR-019, TRD 22).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from arc.db.connection import NotFoundError
from arc.domain.models import (
    SkillExecutionResult,
    SkillExecutionStatus,
    Tenant,
    WebhookEvent,
    WebhookEventStatus,
)
from arc.security.models import ApplicationRole
from arc.services.webhook_config import (
    WebhookActionConfig,
    WebhookEndpointConfig,
    WebhookEndpointStore,
)
from arc.services.webhook_pipeline import (
    WebhookPipelineService,
    WebhookProcessingError,
    classify_failure,
    compute_retry_delay,
    is_transient_failure,
)


def _unique(prefix: str) -> str:
    return f"wp-{prefix}-{uuid.uuid4().hex[:10]}"


def _make_event(
    tenant_id: str,
    endpoint_id: str = "github-demo",
    event_id: str | None = None,
    status: WebhookEventStatus = WebhookEventStatus.RECEIVED,
    retry_count: int = 0,
    max_retries: int = 5,
) -> WebhookEvent:
    return WebhookEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        endpoint_id=endpoint_id,
        event_id=event_id or _unique("evt"),
        event_type="push",
        status=status,
        payload_size_bytes=128,
        created_at=datetime.now(timezone.utc),
        retry_count=retry_count,
        max_retries=max_retries,
    )


def _success_result(tenant_id: str, skill_id: str = "skill-1") -> SkillExecutionResult:
    return SkillExecutionResult(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        principal_id="system:webhook",
        skill_id=skill_id,
        skill_name="test-skill",
        skill_version="1.0",
        status=SkillExecutionStatus.SUCCEEDED,
    )


def _failed_result(
    tenant_id: str, skill_id: str = "skill-1", error_kind: str = "execution_error"
) -> SkillExecutionResult:
    return SkillExecutionResult(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        principal_id="system:webhook",
        skill_id=skill_id,
        skill_name="test-skill",
        skill_version="1.0",
        status=SkillExecutionStatus.FAILED,
        error_kind=error_kind,
    )


class FakeRepository:
    """In-memory WebhookEventRepository with atomic claiming."""

    def __init__(self):
        self._events: dict[str, WebhookEvent] = {}

    async def create(self, event: WebhookEvent) -> WebhookEvent:
        key = (event.tenant_id, event.event_id)
        for e in self._events.values():
            if (e.tenant_id, e.event_id) == key:
                from arc.db.connection import DuplicateKeyError

                raise DuplicateKeyError("duplicate")
        self._events[event.id] = event
        return event

    async def get_by_event_id(self, event_id: str, tenant_id: str) -> WebhookEvent:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                return e
        raise NotFoundError("missing")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> List[WebhookEvent]:
        return [e for e in self._events.values() if e.tenant_id == tenant_id][:limit]

    async def claim_for_processing(self, event_id: str, tenant_id: str) -> WebhookEvent:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.RECEIVED:
                    raise NotFoundError(f"event '{event_id}' not in 'received' status")
                e.status = WebhookEventStatus.PROCESSING
                return e
        raise NotFoundError(f"event '{event_id}' not found")

    async def mark_processed(self, event_id: str, tenant_id: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    raise NotFoundError(f"event '{event_id}' not in 'processing' status")
                e.status = WebhookEventStatus.PROCESSED
                e.processed_at = datetime.now(timezone.utc)
                return
        raise NotFoundError(f"event '{event_id}' not found")

    async def mark_failed(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    raise NotFoundError(f"event '{event_id}' not in 'processing' status")
                e.status = WebhookEventStatus.FAILED
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return
        raise NotFoundError(f"event '{event_id}' not found")

    async def mark_retrying(
        self, event_id: str, tenant_id: str, retry_count: int, next_retry_at: datetime
    ) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status is not WebhookEventStatus.PROCESSING:
                    raise NotFoundError(f"event '{event_id}' not in 'processing' status")
                e.status = WebhookEventStatus.RETRYING
                e.retry_count = retry_count
                e.next_retry_at = next_retry_at
                return
        raise NotFoundError(f"event '{event_id}' not found")

    async def claim_for_retry(self, tenant_id: str, limit: int = 10) -> List[WebhookEvent]:
        now = datetime.now(timezone.utc)
        claimed = []
        for e in self._events.values():
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

    async def mark_dead_letter(self, event_id: str, tenant_id: str, error_kind: str) -> None:
        for e in self._events.values():
            if e.event_id == event_id and e.tenant_id == tenant_id:
                if e.status not in (WebhookEventStatus.PROCESSING, WebhookEventStatus.RETRYING):
                    raise NotFoundError(f"event '{event_id}' not in retryable status")
                e.status = WebhookEventStatus.DEAD_LETTER
                e.error_kind = error_kind
                e.processed_at = datetime.now(timezone.utc)
                return
        raise NotFoundError(f"event '{event_id}' not found")


class FakeTenantRepository:
    """In-memory TenantRepository."""

    def __init__(self, tenants: dict[str, Tenant] | None = None):
        self._tenants = tenants or {}

    async def get_by_id(self, tenant_id: str) -> Tenant:
        if tenant_id not in self._tenants:
            raise NotFoundError(f"tenant '{tenant_id}' not found")
        return self._tenants[tenant_id]

    async def create(self, tenant: Tenant) -> Tenant:
        self._tenants[tenant.id] = tenant
        return tenant

    async def update(self, tenant: Tenant) -> Tenant:
        self._tenants[tenant.id] = tenant
        return tenant

    async def exists(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants

    async def delete(self, tenant_id: str) -> None:
        self._tenants.pop(tenant_id, None)


def _build_service(
    action: WebhookActionConfig | None = None,
    tenant: Tenant | None = None,
    skill_result: SkillExecutionResult | None = None,
    skill_side_effect: Exception | None = None,
    endpoint_store: WebhookEndpointStore | None = None,
) -> tuple[WebhookPipelineService, FakeRepository]:
    tenant_id = "tenant-1"
    endpoint_id = "github-demo"

    if tenant is None:
        tenant = Tenant(id=tenant_id, name="Acme Corp")
    tenant_repo = FakeTenantRepository({tenant_id: tenant})

    if endpoint_store is None:
        endpoint_data: dict = {
            "tenant_id": tenant_id,
            "secret": "a" * 32,
        }
        if action is not None:
            endpoint_data["action"] = {
                "type": action.type,
                "skill_id": action.skill_id,
                "tool_calls": action.tool_calls,
                "satisfied_conditions": action.satisfied_conditions,
            }
        endpoint_store = WebhookEndpointStore(raw=json.dumps({endpoint_id: endpoint_data}))

    repo = FakeRepository()

    skill_service = MagicMock()
    skill_service.get_skill = AsyncMock()

    skill_execution = AsyncMock()
    if skill_side_effect:
        skill_execution.execute = AsyncMock(side_effect=skill_side_effect)
    else:
        skill_execution.execute = AsyncMock(return_value=skill_result or _success_result(tenant_id))

    pii_guard = MagicMock()
    pii_guard.sanitize = MagicMock(return_value=MagicMock(sanitized_text="push"))

    svc = WebhookPipelineService(
        webhook_repository=repo,
        endpoint_store=endpoint_store,
        tenant_repository=tenant_repo,
        skill_execution_service=skill_execution,
        pii_guard=pii_guard,
    )
    return svc, repo


# --- Happy path ---


@pytest.mark.asyncio
async def test_process_success():
    """Event transitions received -> processing -> processed."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1")
    await repo.create(event)

    result = await svc.process("tenant-1", event.event_id)

    assert result["status"] == "processed"
    assert result["event_id"] == event.event_id
    assert result["duplicate"] is False
    assert result["created_at"] is not None

    # Verify final state in repo.
    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.PROCESSED
    assert stored.processed_at is not None


@pytest.mark.asyncio
async def test_process_delegates_to_skill_execution():
    """Pipeline calls SkillExecutionService.execute with correct args."""
    tool_calls = [{"tool_name": "noop", "input": {"key": "val"}}]
    satisfied = ["cond-a"]
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-42",
        tool_calls=tool_calls,
        satisfied_conditions=satisfied,
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", event_id="evt-42")
    await repo.create(event)

    await svc.process("tenant-1", event.event_id)

    svc._skill_execution_service.execute.assert_called_once()
    call_args = svc._skill_execution_service.execute.call_args

    # Directly-known arguments (from action config and constants).
    assert call_args.args[2] == "skill-42"
    assert call_args.args[3] == tool_calls
    assert call_args.args[4] == satisfied

    # Context: pipeline-constructed TenantContext.
    ctx = call_args.args[0]
    assert ctx.tenant_id == "tenant-1"
    assert ctx.user_id == "system:webhook"

    # Principal: system principal.
    assert call_args.args[1].user_id == "system:webhook"

    # Authorization: system principal -> WEBHOOK_PROCESSOR.
    auth = call_args.args[5]
    assert auth.role_for("system:webhook") is ApplicationRole.WEBHOOK_PROCESSOR


# --- No action configured ---


@pytest.mark.asyncio
async def test_process_no_action_configured():
    """Event fails when endpoint has no action configuration."""
    svc, repo = _build_service(action=None)

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "no_action_configured"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "no_action_configured"


# --- Unknown action type ---


@pytest.mark.asyncio
async def test_process_unknown_action_type():
    """Event fails when action type is not 'skill'."""
    fake_action = WebhookActionConfig(
        type="unsupported",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )

    class FakeStore:
        def get(self, endpoint_id):
            return WebhookEndpointConfig(
                endpoint_id=endpoint_id,
                tenant_id="tenant-1",
                secret="a" * 32,
                action=fake_action,
            )

    svc, repo = _build_service(endpoint_store=FakeStore())

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "unknown_action_type"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "unknown_action_type"


# --- Tenant not found ---


@pytest.mark.asyncio
async def test_process_tenant_not_found():
    """Event fails when the tenant does not exist."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)
    # Replace tenant repo with empty one (no tenants).
    svc._tenant_repository = FakeTenantRepository({})

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "configuration_error"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "configuration_error"


# --- Skill execution returns non-success ---


@pytest.mark.asyncio
async def test_process_skill_execution_denied():
    """Transient failure (disallowed_tool) schedules a retry, not immediate fail."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="disallowed_tool")
    svc, repo = _build_service(action=action, skill_result=result)

    event = _make_event("tenant-1")
    await repo.create(event)

    response = await svc.process("tenant-1", event.event_id)

    assert response["status"] == "retrying"
    assert response["retry_count"] == 1

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.RETRYING
    assert stored.error_kind is None


@pytest.mark.asyncio
async def test_process_skill_execution_precondition_failed():
    """Transient failure (precondition_failed) schedules a retry."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="precondition_failed")
    svc, repo = _build_service(action=action, skill_result=result)

    event = _make_event("tenant-1")
    await repo.create(event)

    response = await svc.process("tenant-1", event.event_id)

    assert response["status"] == "retrying"
    assert response["retry_count"] == 1

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.RETRYING


# --- Skill execution raises exception ---


@pytest.mark.asyncio
async def test_process_skill_execution_raises_value_error():
    """Event fails with configuration_error on ValueError from execute."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=ValueError("invalid"))

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "configuration_error"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "configuration_error"


@pytest.mark.asyncio
async def test_process_skill_execution_raises_not_found():
    """Event fails with configuration_error on NotFoundError from execute."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=NotFoundError("skill missing"))

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "configuration_error"


# --- Unexpected exception ---


@pytest.mark.asyncio
async def test_process_unexpected_exception():
    """Unexpected exception (RuntimeError) schedules a retry via pipeline_internal_error."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=RuntimeError("boom"))

    event = _make_event("tenant-1")
    await repo.create(event)

    response = await svc.process("tenant-1", event.event_id)

    assert response["status"] == "retrying"
    assert response["retry_count"] == 1

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.RETRYING


# --- Event not found / wrong status ---


@pytest.mark.asyncio
async def test_process_event_not_found():
    """NotFoundError when event does not exist."""
    svc, _ = _build_service()

    with pytest.raises(NotFoundError):
        await svc.process("tenant-1", "nonexistent-event")


@pytest.mark.asyncio
async def test_process_already_processing():
    """NotFoundError when event is already in processing status."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", status=WebhookEventStatus.PROCESSING)
    await repo.create(event)

    with pytest.raises(NotFoundError):
        await svc.process("tenant-1", event.event_id)


@pytest.mark.asyncio
async def test_process_already_processed():
    """NotFoundError when event is already processed."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", status=WebhookEventStatus.PROCESSED)
    await repo.create(event)

    with pytest.raises(NotFoundError):
        await svc.process("tenant-1", event.event_id)


@pytest.mark.asyncio
async def test_process_already_failed():
    """NotFoundError when event is already failed."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", status=WebhookEventStatus.FAILED)
    await repo.create(event)

    with pytest.raises(NotFoundError):
        await svc.process("tenant-1", event.event_id)


# --- PII guard integration ---


@pytest.mark.asyncio
async def test_process_pii_guard_called():
    """PII Guard is applied to event_type before downstream use."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", event_id="evt-pii")
    event.event_type = "user.created"
    await repo.create(event)

    await svc.process("tenant-1", event.event_id)
    # PII guard was invoked (the MagicMock records the call).
    svc._pii_guard.sanitize.assert_called_once_with("user.created")


# --- mark_failed failure ---


@pytest.mark.asyncio
async def test_process_retry_failure():
    """When mark_retrying fails, falls back to mark_failed and re-raises the original error."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    # Skill execution fails -> pipeline tries mark_retrying -> which also fails.
    failed_result = _failed_result("tenant-1", error_kind="disallowed_tool")
    svc, repo = _build_service(action=action, skill_result=failed_result)

    event = _make_event("tenant-1")
    await repo.create(event)

    # Monkey-patch mark_retrying to raise.
    original_mark_retrying = repo.mark_retrying

    async def broken_mark_retrying(event_id, tenant_id, retry_count, next_retry_at):
        raise RuntimeError("db down")

    repo.mark_retrying = broken_mark_retrying

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    # Fallback: event is marked as failed (retry scheduling failed).
    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "disallowed_tool"

    repo.mark_retrying = original_mark_retrying


# --- Failure classification helpers ---


def test_is_transient_failure():
    """Downstream and internal errors are transient; config/action errors are not."""
    assert is_transient_failure("downstream_execution_error") is True
    assert is_transient_failure("pipeline_internal_error") is True
    assert is_transient_failure("no_action_configured") is False
    assert is_transient_failure("unknown_action_type") is False
    assert is_transient_failure("configuration_error") is False


def test_classify_failure_transient_with_retries_left():
    """Transient failure with retries remaining returns 'retry'."""
    assert classify_failure("downstream_execution_error", retry_count=0, max_retries=5) == "retry"
    assert classify_failure("pipeline_internal_error", retry_count=2, max_retries=5) == "retry"


def test_classify_failure_transient_exhausted():
    """Transient failure with retries exhausted returns 'dead_letter'."""
    assert (
        classify_failure("downstream_execution_error", retry_count=5, max_retries=5)
        == "dead_letter"
    )
    assert (
        classify_failure("pipeline_internal_error", retry_count=3, max_retries=3) == "dead_letter"
    )


def test_classify_failure_permanent():
    """Permanent failures always return 'failed' regardless of retry count."""
    assert classify_failure("no_action_configured", retry_count=0, max_retries=5) == "failed"
    assert classify_failure("unknown_action_type", retry_count=5, max_retries=5) == "failed"
    assert classify_failure("configuration_error", retry_count=0, max_retries=5) == "failed"


def test_compute_retry_delay_exponential():
    """Delay doubles with each retry, capped at 300s."""
    assert compute_retry_delay(0) == 10  # 10 * 2^0
    assert compute_retry_delay(1) == 20  # 10 * 2^1
    assert compute_retry_delay(2) == 40  # 10 * 2^2
    assert compute_retry_delay(3) == 80  # 10 * 2^3
    assert compute_retry_delay(4) == 160  # 10 * 2^4
    assert compute_retry_delay(5) == 300  # capped at 300
    assert compute_retry_delay(10) == 300  # still capped


# --- Retry pipeline ---


@pytest.mark.asyncio
async def test_transient_failure_schedules_retry():
    """A transient failure (downstream error) schedules a retry, not a permanent fail."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="downstream_execution_error")
    svc, repo = _build_service(action=action, skill_result=result)

    event = _make_event("tenant-1")
    await repo.create(event)

    response = await svc.process("tenant-1", event.event_id)

    assert response["status"] == "retrying"
    assert response["retry_count"] == 1

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.RETRYING
    assert stored.retry_count == 1
    assert stored.next_retry_at is not None
    assert stored.next_retry_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_permanent_failure_does_not_retry():
    """A permanent failure (no_action_configured) goes straight to failed."""
    svc, repo = _build_service(action=None)

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "no_action_configured"


@pytest.mark.asyncio
async def test_retries_exhausted_goes_to_dead_letter():
    """When retry_count >= max_retries, transient failure goes to dead_letter."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="downstream_execution_error")
    svc, repo = _build_service(action=action, skill_result=result)

    # Create event with retry_count=5, max_retries=5, already in retrying status.
    event = _make_event("tenant-1", event_id="evt-exhausted", retry_count=5, max_retries=5)
    event.status = WebhookEventStatus.RETRYING
    event.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await repo.create(event)

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.DEAD_LETTER


@pytest.mark.asyncio
async def test_retry_from_retrying_status():
    """Pipeline can claim and re-process an event from 'retrying' status."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", status=WebhookEventStatus.RETRYING, retry_count=1)
    event.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await repo.create(event)

    result = await svc.process("tenant-1", event.event_id)
    assert result["status"] == "processed"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.PROCESSED


@pytest.mark.asyncio
async def test_retry_backoff_increases():
    """Each retry increments retry_count and increases the backoff delay."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="downstream_execution_error")
    svc, repo = _build_service(action=action, skill_result=result)

    # First attempt: retry_count=0 -> schedules retry with retry_count=1
    event = _make_event("tenant-1", event_id="evt-backoff")
    await repo.create(event)

    response1 = await svc.process("tenant-1", event.event_id)
    assert response1["status"] == "retrying"
    assert response1["retry_count"] == 1

    stored1 = await repo.get_by_event_id(event.event_id, "tenant-1")
    first_delay = (stored1.next_retry_at - stored1.created_at).total_seconds()

    # Simulate the event being retried and failing again.
    stored1.status = WebhookEventStatus.RETRYING
    stored1.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    response2 = await svc.process("tenant-1", event.event_id)
    assert response2["status"] == "retrying"
    assert response2["retry_count"] == 2

    stored2 = await repo.get_by_event_id(event.event_id, "tenant-1")
    second_delay = (stored2.next_retry_at - stored2.created_at).total_seconds()

    # Second delay should be roughly double the first.
    assert second_delay > first_delay


@pytest.mark.asyncio
async def test_unexpected_exception_retries_when_transient():
    """An unexpected exception (RuntimeError) schedules a retry, not immediate failure."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=RuntimeError("boom"))

    event = _make_event("tenant-1")
    await repo.create(event)

    response = await svc.process("tenant-1", event.event_id)

    assert response["status"] == "retrying"
    assert response["retry_count"] == 1

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.RETRYING


@pytest.mark.asyncio
async def test_claim_for_retry_returns_eligible_events():
    """claim_for_retry returns events whose next_retry_at has passed."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", status=WebhookEventStatus.RETRYING, retry_count=1)
    event.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await repo.create(event)

    claimed = await repo.claim_for_retry("tenant-1")
    assert len(claimed) == 1
    assert claimed[0].event_id == event.event_id
    assert claimed[0].status is WebhookEventStatus.PROCESSING


@pytest.mark.asyncio
async def test_claim_for_retry_skips_future_events():
    """claim_for_retry skips events whose next_retry_at is in the future."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", status=WebhookEventStatus.RETRYING, retry_count=1)
    event.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.create(event)

    claimed = await repo.claim_for_retry("tenant-1")
    assert len(claimed) == 0
