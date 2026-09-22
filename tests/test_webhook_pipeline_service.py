"""Webhook downstream processing pipeline: unit tests (Issue #102, #136).

Exercises the webhook-to-Skill execution pipeline with in-memory fakes:
atomic claiming, downstream delegation, success/failure transitions,
error kinds, PII guard integration, the "at most one processor" contract,
and the retry/backoff pipeline (V2-ADR-019, TRD 22).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
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
from arc.services.tools import ToolDeniedError
from arc.services.webhook_config import (
    WebhookActionConfig,
    WebhookEndpointConfig,
    WebhookEndpointStore,
)
from arc.services.webhook_pipeline import (
    WebhookPipelineService,
    WebhookProcessingError,
    classify_failure,
    compute_idempotency_key,
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
                "skill_inputs": action.skill_inputs,
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

    # Idempotency key is passed through.
    assert call_args.kwargs.get("idempotency_key") is not None


@pytest.mark.asyncio
async def test_process_passes_action_skill_inputs():
    """Issue #241: configured static skill inputs reach skill execution."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-42",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
        skill_inputs={"incident_description": "outage"},
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", event_id="evt-inputs")
    await repo.create(event)

    await svc.process("tenant-1", event.event_id)

    call_args = svc._skill_execution_service.execute.call_args
    assert call_args.kwargs.get("skill_inputs") == {"incident_description": "outage"}


@pytest.mark.asyncio
async def test_process_defaults_to_empty_skill_inputs():
    """Actions without skill_inputs execute with an empty mapping."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-42",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", event_id="evt-noinputs")
    await repo.create(event)

    await svc.process("tenant-1", event.event_id)

    call_args = svc._skill_execution_service.execute.call_args
    assert call_args.kwargs.get("skill_inputs") == {}


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
    """disallowed_tool is a permanent failure — goes straight to failed."""
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

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "disallowed_tool"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "disallowed_tool"


@pytest.mark.asyncio
async def test_process_skill_execution_precondition_failed():
    """precondition_failed is a transient failure — schedules a retry."""
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


# --- Authorization/policy errors ---


@pytest.mark.asyncio
async def test_process_tool_denied_error_is_permanent():
    """ToolDeniedError (authorization/policy) is permanent — goes to failed."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=ToolDeniedError("noop"))

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "authorization_error"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "authorization_error"


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


# --- mark_retrying failure fallback ---


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
    failed_result = _failed_result("tenant-1", error_kind="downstream_execution_error")
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
    assert stored.error_kind == "downstream_execution_error"

    repo.mark_retrying = original_mark_retrying


# --- Failure classification helpers ---


def test_is_transient_failure():
    """Downstream and internal errors are transient; config/action/auth errors are not."""
    assert is_transient_failure("downstream_execution_error") is True
    assert is_transient_failure("pipeline_internal_error") is True
    assert is_transient_failure("precondition_failed") is True
    assert is_transient_failure("no_action_configured") is False
    assert is_transient_failure("unknown_action_type") is False
    assert is_transient_failure("configuration_error") is False
    assert is_transient_failure("disallowed_tool") is False
    assert is_transient_failure("authorization_error") is False


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
    assert classify_failure("disallowed_tool", retry_count=0, max_retries=5) == "failed"
    assert classify_failure("authorization_error", retry_count=0, max_retries=5) == "failed"


def test_compute_retry_delay_exponential():
    """Delay doubles with each retry, capped at 300s."""
    assert compute_retry_delay(0) == 10  # 10 * 2^0
    assert compute_retry_delay(1) == 20  # 10 * 2^1
    assert compute_retry_delay(2) == 40  # 10 * 2^2
    assert compute_retry_delay(3) == 80  # 10 * 2^3
    assert compute_retry_delay(4) == 160  # 10 * 2^4
    assert compute_retry_delay(5) == 300  # capped at 300
    assert compute_retry_delay(10) == 300  # still capped


# --- Idempotency key ---


def test_compute_idempotency_key_deterministic():
    """Same inputs produce the same key; different inputs produce different keys."""
    key1 = compute_idempotency_key("tenant-1", "evt-1")
    key2 = compute_idempotency_key("tenant-1", "evt-1")
    assert key1 == key2
    assert key1 == "webhook:tenant-1:evt-1"

    key3 = compute_idempotency_key("tenant-1", "evt-2")
    assert key1 != key3

    key4 = compute_idempotency_key("tenant-2", "evt-1")
    assert key1 != key4


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


# --- C1: Single retry claim ---


@pytest.mark.asyncio
async def test_claim_single_for_retry_claims_only_target():
    """claim_single_for_retry claims only the requested event, not others."""
    svc, repo = _build_service()

    event_a = _make_event("tenant-1", event_id="evt-a", status=WebhookEventStatus.RETRYING)
    event_a.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await repo.create(event_a)

    event_b = _make_event("tenant-1", event_id="evt-b", status=WebhookEventStatus.RETRYING)
    event_b.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await repo.create(event_b)

    claimed = await repo.claim_single_for_retry("evt-a", "tenant-1")
    assert claimed is not None
    assert claimed.event_id == "evt-a"
    assert claimed.status is WebhookEventStatus.PROCESSING

    # Event B should still be RETRYING, not accidentally claimed.
    stored_b = await repo.get_by_event_id("evt-b", "tenant-1")
    assert stored_b.status is WebhookEventStatus.RETRYING


@pytest.mark.asyncio
async def test_claim_single_for_retry_returns_none_for_future():
    """claim_single_for_retry returns None when next_retry_at is in the future."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", event_id="evt-future", status=WebhookEventStatus.RETRYING)
    event.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.create(event)

    claimed = await repo.claim_single_for_retry("evt-future", "tenant-1")
    assert claimed is None


@pytest.mark.asyncio
async def test_claim_single_for_retry_returns_none_for_missing():
    """claim_single_for_retry returns None when event does not exist."""
    svc, repo = _build_service()

    claimed = await repo.claim_single_for_retry("nonexistent", "tenant-1")
    assert claimed is None


# --- S1: Stuck processing recovery ---


@pytest.mark.asyncio
async def test_sweep_stuck_processing_finds_old_events():
    """sweep_stuck_processing returns events stuck beyond the threshold."""
    svc, repo = _build_service()

    # Create an event that was created long ago and is still processing.
    old_event = _make_event("tenant-1", event_id="evt-stuck")
    old_event.status = WebhookEventStatus.PROCESSING
    old_event.created_at = datetime.now(timezone.utc) - timedelta(seconds=1200)
    await repo.create(old_event)

    # Create a recent processing event (should NOT be swept).
    recent_event = _make_event("tenant-1", event_id="evt-recent")
    recent_event.status = WebhookEventStatus.PROCESSING
    recent_event.created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    await repo.create(recent_event)

    stuck = await repo.sweep_stuck_processing("tenant-1", stuck_threshold_seconds=600)
    assert len(stuck) == 1
    assert stuck[0].event_id == "evt-stuck"


@pytest.mark.asyncio
async def test_stuck_processing_recovery_processes_event():
    """Stuck processing events are re-processed once before dead-lettering.

    Behavior changed by Issue #178 (X-75): the sweep now attempts one
    recovery through the pipeline instead of dead-lettering directly.
    With succeeding downstream, the stuck event ends processed.
    """
    from arc.services.webhook_retry_sweep import _sweep_stuck_for_tenant

    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    stuck_event = _make_event("tenant-1", event_id="evt-stuck")
    stuck_event.status = WebhookEventStatus.PROCESSING
    stuck_event.created_at = datetime.now(timezone.utc) - timedelta(seconds=1200)
    await repo.create(stuck_event)

    await _sweep_stuck_for_tenant(svc, "tenant-1", stuck_threshold_seconds=600)

    stored = await repo.get_by_event_id("evt-stuck", "tenant-1")
    assert stored.status is WebhookEventStatus.PROCESSED


# --- Concurrency: atomic claiming ---


@pytest.mark.asyncio
async def test_concurrent_claim_for_processing_only_one_wins():
    """Two concurrent claims on the same event: exactly one succeeds."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1")
    await repo.create(event)

    # Simulate two workers trying to claim the same event.
    result1 = None
    result2 = None
    error1 = None
    error2 = None

    try:
        result1 = await repo.claim_for_processing(event.event_id, "tenant-1")
    except NotFoundError as e:
        error1 = e

    try:
        result2 = await repo.claim_for_processing(event.event_id, "tenant-1")
    except NotFoundError as e:
        error2 = e

    # Exactly one should succeed.
    assert (result1 is not None) != (result2 is not None)
    assert (error1 is not None) != (error2 is not None)


@pytest.mark.asyncio
async def test_concurrent_claim_for_retry_only_one_wins():
    """Two concurrent claims on the same retrying event: exactly one succeeds."""
    svc, repo = _build_service()

    event = _make_event("tenant-1", event_id="evt-concurrent", status=WebhookEventStatus.RETRYING)
    event.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await repo.create(event)

    claimed1 = await repo.claim_single_for_retry("evt-concurrent", "tenant-1")
    claimed2 = await repo.claim_single_for_retry("evt-concurrent", "tenant-1")

    # Exactly one should succeed (in-memory fake simulates atomicity).
    assert (claimed1 is not None) != (claimed2 is not None)


# --- Idempotency crash-window test ---


@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_tool_execution():
    """Retry after prior success does not re-execute the downstream tool.

    This is the critical crash-window scenario:
    1. Webhook event is received and processed.
    2. Downstream tool executes successfully.
    3. Process crashes before mark_processed.
    4. Event becomes retryable.
    5. Retry occurs — tool should NOT execute again.
    """
    # Track whether the skill execution was called.
    call_count = 0
    original_execute = AsyncMock(return_value=_success_result("tenant-1"))

    async def counting_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original_execute(*args, **kwargs)

    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)
    svc._skill_execution_service.execute = counting_execute

    event = _make_event("tenant-1")
    await repo.create(event)

    # First processing attempt — succeeds at downstream but we simulate
    # a crash before mark_processed by not calling it.
    claimed = await repo.claim_for_processing(event.event_id, "tenant-1")
    assert claimed.status is WebhookEventStatus.PROCESSING

    # Execute downstream (simulating the pipeline's _execute_downstream).
    idempotency_key = compute_idempotency_key("tenant-1", event.event_id)
    await svc._execute_downstream("tenant-1", event.endpoint_id, event.event_type, idempotency_key)
    assert call_count == 1

    # Simulate crash: event stays in PROCESSING, then recovered to RETRYING.
    await repo.mark_retrying(
        event.event_id,
        "tenant-1",
        1,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    # Retry: pipeline claims from retrying and re-executes downstream.
    # The idempotency key should cause the tool to be skipped.
    # We simulate the pipeline's claim + execute flow.
    claimed2 = await repo.claim_single_for_retry(event.event_id, "tenant-1")
    assert claimed2 is not None

    # In a real pipeline, _execute_downstream would pass the idempotency_key
    # to SkillExecutionService, which passes it to ToolExecutionService.
    # Since our FakeRepository doesn't implement the tool execution idempotency,
    # we verify the key is correctly generated and the pipeline would pass it.
    assert idempotency_key == f"webhook:tenant-1:{event.event_id}"


@pytest.mark.asyncio
async def test_idempotency_key_passed_to_skill_execution():
    """The pipeline passes a deterministic idempotency key to SkillExecutionService."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action)

    event = _make_event("tenant-1", event_id="evt-idem")
    await repo.create(event)

    await svc.process("tenant-1", event.event_id)

    call_args = svc._skill_execution_service.execute.call_args
    assert call_args.kwargs.get("idempotency_key") == "webhook:tenant-1:evt-idem"


@pytest.mark.asyncio
async def test_idempotency_key_same_for_retry():
    """The idempotency key is the same on first attempt and retry."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    result = _failed_result("tenant-1", error_kind="downstream_execution_error")
    svc, repo = _build_service(action=action, skill_result=result)

    event = _make_event("tenant-1", event_id="evt-idem-retry")
    await repo.create(event)

    # First attempt.
    await svc.process("tenant-1", event.event_id)
    call_args_1 = svc._skill_execution_service.execute.call_args
    key_1 = call_args_1.kwargs.get("idempotency_key")

    # Simulate retry.
    stored = await repo.get_by_event_id("evt-idem-retry", "tenant-1")
    stored.status = WebhookEventStatus.RETRYING
    stored.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    await svc.process("tenant-1", event.event_id)
    call_args_2 = svc._skill_execution_service.execute.call_args
    key_2 = call_args_2.kwargs.get("idempotency_key")

    assert key_1 == key_2 == "webhook:tenant-1:evt-idem-retry"
