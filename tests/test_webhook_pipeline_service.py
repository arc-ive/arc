"""Webhook downstream processing pipeline: unit tests (Issue #102).

Exercises the webhook-to-Skill execution pipeline with in-memory fakes:
atomic claiming, downstream delegation, success/failure transitions,
error kinds, PII guard integration, and the "at most one processor"
contract.
"""

import json
import uuid
from datetime import datetime, timezone
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
)


def _unique(prefix: str) -> str:
    return f"wp-{prefix}-{uuid.uuid4().hex[:10]}"


def _make_event(
    tenant_id: str,
    endpoint_id: str = "github-demo",
    event_id: str | None = None,
    status: WebhookEventStatus = WebhookEventStatus.RECEIVED,
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
    """Event fails when SkillExecutionService returns DENIED status."""
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
    """Event fails when SkillExecutionService returns PRECONDITION_FAILED."""
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

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "precondition_failed"


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
    """Event fails with pipeline_internal_error on unexpected exception."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    svc, repo = _build_service(action=action, skill_side_effect=RuntimeError("boom"))

    event = _make_event("tenant-1")
    await repo.create(event)

    with pytest.raises(WebhookProcessingError) as exc_info:
        await svc.process("tenant-1", event.event_id)

    assert exc_info.value.error_kind == "pipeline_internal_error"

    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.FAILED
    assert stored.error_kind == "pipeline_internal_error"


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
async def test_process_mark_failed_failure():
    """When mark_failed fails, the event stays in 'processing' and the original error propagates."""
    action = WebhookActionConfig(
        type="skill",
        skill_id="skill-1",
        tool_calls=[{"tool_name": "noop", "input": {}}],
        satisfied_conditions=[],
    )
    # Skill execution fails -> pipeline tries mark_failed -> which also fails.
    failed_result = _failed_result("tenant-1", error_kind="disallowed_tool")
    svc, repo = _build_service(action=action, skill_result=failed_result)

    event = _make_event("tenant-1")
    await repo.create(event)

    # Monkey-patch mark_failed to raise.
    original_mark_failed = repo.mark_failed

    async def broken_mark_failed(event_id, tenant_id, error_kind):
        raise RuntimeError("db down")

    repo.mark_failed = broken_mark_failed

    with pytest.raises(WebhookProcessingError):
        await svc.process("tenant-1", event.event_id)

    # Event remains in processing (mark_failed failed).
    stored = await repo.get_by_event_id(event.event_id, "tenant-1")
    assert stored.status is WebhookEventStatus.PROCESSING

    repo.mark_failed = original_mark_failed
