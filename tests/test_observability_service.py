"""Unit tests for the ObservabilityService (approved failure semantics).

Telemetry WRITES are best effort: a persistence failure is dropped and
logged — it must never propagate into the served business response.
READ paths assemble aggregates only and validate the window bounds.
Component health uses existing public factories and reports status
labels without ever exposing configuration material.
"""

import pytest

from arc.domain.models import (
    AgentRunActivityMetrics,
    AgentRunRecord,
    AgentRunRecordStep,
    ApiRequestRecord,
    ApprovalActivityMetrics,
    ConnectorSyncActivityMetrics,
    HttpUsageMetrics,
    SkillExecutionActivityMetrics,
    ToolExecutionActivityMetrics,
    WebhookEventActivityMetrics,
)
from arc.services.embeddings import EmbeddingConfigurationError
from arc.services.llm import LlmConfigurationError
from arc.services.observability import ObservabilityService


class FlakyRepository:
    """Fake repository whose write path can be forced to fail."""

    def __init__(self, fail_writes: bool = False):
        self.fail_writes = fail_writes
        self.calls = 0
        self.agent_run_calls = 0

    async def create_api_request_record(self, record):
        if self.fail_writes:
            raise RuntimeError("database exploded")
        self.calls += 1
        return record

    async def create_agent_run_record(self, record):
        if self.fail_writes:
            raise RuntimeError("database exploded")
        self.agent_run_calls += 1
        return record


class RecordingRepository:
    """Fake returning deterministic aggregates for assembly tests."""

    async def create_api_request_record(self, record):
        return record

    async def api_request_summary(self, tenant_id, hours):
        return HttpUsageMetrics(
            total_requests=10,
            error_count=2,
            error_rate=0.2,
            avg_duration_ms=50.0,
            p95_duration_ms=120.0,
        )

    async def skill_execution_activity(self, tenant_id, hours):
        return SkillExecutionActivityMetrics(
            total_executions=12, succeeded=9, failed=2, approval_required=1, denied=0
        )

    async def tool_execution_activity(self, tenant_id, hours):
        return ToolExecutionActivityMetrics(total_executions=7, successful=5, failed=1, denied=1)

    async def connector_sync_activity(self, tenant_id, hours):
        return ConnectorSyncActivityMetrics(total_syncs=4, successful=3, failed=1, items_fetched=42)

    async def webhook_event_activity(self, tenant_id, hours):
        return WebhookEventActivityMetrics(
            available=True, total_events=9, distinct_event_types=2, total_payload_bytes=300
        )

    async def approval_activity(self, tenant_id, hours):
        return ApprovalActivityMetrics(
            total=3, pending=1, approved=1, rejected=0, expired=1, consumed=0
        )

    async def escalation_count(self, tenant_id, hours):
        return 2

    async def agent_run_activity(self, tenant_id, hours):
        return AgentRunActivityMetrics(
            total_runs=5, succeeded=3, failed=1, approval_required=1, max_steps_reached=0
        )

    async def create_agent_run_record(self, record):
        return record


@pytest.mark.asyncio
async def test_record_api_request_persists_and_returns_true():
    repo = FlakyRepository()
    service = ObservabilityService(repository=repo)
    record = ApiRequestRecord(
        id="r1",
        request_id="cr1",
        method="GET",
        route_template="/health",
        status_code=200,
        duration_ms=1,
    )
    assert await service.record_api_request(record) is True
    assert repo.calls == 1


@pytest.mark.asyncio
async def test_telemetry_write_failure_is_swallowed_not_raised():
    service = ObservabilityService(repository=FlakyRepository(fail_writes=True))
    record = ApiRequestRecord(
        id="r2",
        request_id="cr2",
        method="GET",
        route_template="/health",
        status_code=200,
        duration_ms=1,
    )
    assert await service.record_api_request(record) is False


def test_window_bounds_enforced():
    service = ObservabilityService(repository=RecordingRepository())
    with pytest.raises(ValueError):
        service._validated_window(0)
    with pytest.raises(ValueError):
        service._validated_window(169)
    with pytest.raises(ValueError):
        service._validated_window("24")


@pytest.mark.asyncio
async def test_tenant_summary_assembles_aggregates_only():
    service = ObservabilityService(repository=RecordingRepository())
    summary = await service.get_tenant_usage_summary("tenant-1", 24)
    assert summary["window_hours"] == 24
    assert summary["http"] == {
        "total_requests": 10,
        "error_count": 2,
        "error_rate": 0.2,
        "avg_duration_ms": 50.0,
        "p95_duration_ms": 120.0,
    }
    assert summary["tools"]["denied"] == 1
    assert summary["connectors"]["items_fetched"] == 42
    assert summary["webhooks"]["available"] is True
    assert summary["approvals"]["total"] == 3
    assert summary["approvals"]["pending"] == 1
    assert summary["approvals"]["consumed"] == 0
    # No raw rows or sensitive material in any section
    flat = str(summary)
    for forbidden in ("input_summary", "output_summary", "content", "answer", "prompt"):
        assert forbidden not in flat


@pytest.mark.asyncio
async def test_platform_summary_is_strictly_tenant_agnostic():
    service = ObservabilityService(repository=RecordingRepository())
    summary = await service.get_platform_summary(24)
    assert set(summary) == {
        "window_hours",
        "http",
        "tool_activity_total",
        "tool_failures_total",
        "skill_activity_total",
        "skill_failures_total",
        "connector_syncs_total",
        "connector_failures_total",
        "webhook_events_total",
        "webhook_source_available",
        "approval_activity_total",
        "approval_failures_total",
        "escalation_count_total",
        "agent_runs_total",
        "agent_runs_succeeded",
        "agent_runs_failed",
    }
    serialized = str(summary)
    assert "tenant_id" not in serialized
    assert "tenant-" not in serialized


@pytest.mark.asyncio
async def test_unavailable_webhook_source_reports_zeroes_not_fabrication():
    class AbsentWebhookRepo(RecordingRepository):
        async def webhook_event_activity(self, tenant_id, hours):
            return WebhookEventActivityMetrics(available=False)

    service = ObservabilityService(repository=AbsentWebhookRepo())
    platform = await service.get_platform_summary(24)
    assert platform["webhook_source_available"] is False
    assert platform["webhook_events_total"] == 0


class HealthRepository:
    """Fake with a controllable database probe for health tests."""

    def __init__(self, ok: bool = True):
        self._ok = ok

    async def database_reachable(self):
        return self._ok


@pytest.mark.asyncio
async def test_component_health_all_healthy(monkeypatch):
    from arc.services import observability as obs_module

    monkeypatch.setattr(obs_module, "build_llm_provider", lambda settings: object())
    monkeypatch.setattr(obs_module, "get_llm_settings", lambda: object())
    monkeypatch.setattr(obs_module, "build_embedding_provider", lambda settings: object())
    monkeypatch.setattr(obs_module, "get_embedding_settings", lambda: object())

    service = ObservabilityService(repository=HealthRepository(ok=True))
    health = await service.get_component_health()
    assert health["overall"] == "healthy"
    assert health["components"]["database"]["status"] == "healthy"
    assert health["components"]["llm_provider"]["status"] == "healthy"
    assert health["components"]["embeddings"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_component_health_reports_failures_without_details(monkeypatch):
    from arc.services import observability as obs_module

    def llm_boom(settings):
        raise LlmConfigurationError("secret-config-value-must-not-leak")

    def embedding_boom(settings):
        raise EmbeddingConfigurationError("embedding-config-must-not-leak")

    monkeypatch.setattr(obs_module, "get_llm_settings", lambda: object())
    monkeypatch.setattr(obs_module, "build_llm_provider", llm_boom)
    monkeypatch.setattr(obs_module, "get_embedding_settings", lambda: object())
    monkeypatch.setattr(obs_module, "build_embedding_provider", embedding_boom)

    service = ObservabilityService(repository=HealthRepository(ok=False))
    health = await service.get_component_health()
    assert health["overall"] == "degraded"
    assert health["components"]["database"]["status"] == "unhealthy"
    assert health["components"]["llm_provider"]["status"] == "unhealthy"
    assert health["components"]["embeddings"]["status"] == "unhealthy"
    # Configuration error text must never leak into the response.
    serialized = str(health)
    assert "secret-config-value" not in serialized
    assert "embedding-config-must-not-leak" not in serialized


@pytest.mark.asyncio
async def test_probe_catches_unexpected_exceptions(monkeypatch):
    from arc.services import observability as obs_module

    def boom(settings):
        raise ConnectionError("database connection refused")

    monkeypatch.setattr(obs_module, "get_llm_settings", lambda: object())
    monkeypatch.setattr(obs_module, "build_llm_provider", boom)
    monkeypatch.setattr(obs_module, "get_embedding_settings", lambda: object())
    monkeypatch.setattr(obs_module, "build_embedding_provider", boom)

    service = ObservabilityService(repository=HealthRepository(ok=True))
    health = await service.get_component_health()
    # Even though the probes raise unexpected exception types,
    # the health endpoint should return gracefully with "unhealthy" labels.
    assert health["overall"] == "degraded"
    assert health["components"]["llm_provider"]["status"] == "unhealthy"
    assert health["components"]["embeddings"]["status"] == "unhealthy"
    assert "database connection refused" not in str(health)


# ------------------------------------------------------------------
# Agent execution trace (PRD 17 O-6)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_agent_run_persists_and_returns_true():
    repo = FlakyRepository()
    service = ObservabilityService(repository=repo)
    record = AgentRunRecord(
        id="run-1",
        tenant_id="t-1",
        principal_id="u-1",
        goal="Do something",
        status="succeeded",
        steps=[
            AgentRunRecordStep(sequence=0, skill_id="sk-1", skill_name="Echo", status="succeeded")
        ],
    )
    assert await service.record_agent_run(record) is True
    assert repo.agent_run_calls == 1


@pytest.mark.asyncio
async def test_agent_run_trace_write_failure_is_swallowed():
    service = ObservabilityService(repository=FlakyRepository(fail_writes=True))
    record = AgentRunRecord(
        id="run-2",
        tenant_id="t-1",
        principal_id="u-1",
        goal="Do something",
        status="failed",
        error_kind="tool_failure",
    )
    assert await service.record_agent_run(record) is False


@pytest.mark.asyncio
async def test_tenant_summary_includes_escalation_count():
    service = ObservabilityService(repository=RecordingRepository())
    summary = await service.get_tenant_usage_summary("tenant-1", 24)
    assert "escalation_count" in summary
    assert summary["escalation_count"] == 2


@pytest.mark.asyncio
async def test_tenant_summary_includes_agent_runs():
    service = ObservabilityService(repository=RecordingRepository())
    summary = await service.get_tenant_usage_summary("tenant-1", 24)
    assert "agent_runs" in summary
    assert summary["agent_runs"]["total_runs"] == 5
    assert summary["agent_runs"]["succeeded"] == 3
    assert summary["agent_runs"]["failed"] == 1
    assert summary["agent_runs"]["approval_required"] == 1
    assert summary["agent_runs"]["max_steps_reached"] == 0


@pytest.mark.asyncio
async def test_platform_summary_includes_escalation_and_agent_runs():
    service = ObservabilityService(repository=RecordingRepository())
    summary = await service.get_platform_summary(24)
    assert summary["escalation_count_total"] == 2
    assert summary["agent_runs_total"] == 5
    assert summary["agent_runs_succeeded"] == 3
    assert summary["agent_runs_failed"] == 1
