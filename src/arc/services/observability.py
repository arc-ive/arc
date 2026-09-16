"""Observability service (PRD 17, TRD 17/28/31; approved architecture).

Observability is an aggregation/read layer, NOT a second source of
truth. Authoritative records remain owned by their subsystems; this
service only assembles read-side aggregates from them and owns the HTTP
telemetry write path plus component-health evaluation.

Failure semantics (approved):

- TELEMETRY WRITE: best effort. A telemetry persistence failure is
  logged safely and dropped — it must NEVER fail the business request.
- READ APIs: fail closed for authorization and tenant isolation, which
  is enforced upstream by the security dependencies; this service never
  widens a scope.

Component health uses ONLY existing public factories/settings readers of
the owning subsystems (no owner-owned implementation is modified). The
webhook-configuration component joins once the Webhooks foundation
(PR #34) merges and its configuration module exists on main.
"""

import logging
from typing import Any, Dict

from arc.domain.models import AgentRunRecord, ApiRequestRecord, LlmUsageRecord
from arc.services.embeddings import build_embedding_provider, get_embedding_settings
from arc.services.llm import build_llm_provider, get_llm_settings

logger = logging.getLogger("arc.observability")

MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168
DEFAULT_WINDOW_HOURS = 24


class ObservabilityService:
    """Aggregation/read-side service for operational observability."""

    def __init__(self, repository):
        self.repository = repository

    # ------------------------------------------------------------------
    # Telemetry write path (best effort)
    # ------------------------------------------------------------------
    async def record_api_request(self, record: ApiRequestRecord) -> bool:
        """Persist one HTTP telemetry record without ever raising.

        Returns True when persisted, False when dropped. A telemetry
        failure must never propagate into the served business response
        (approved failure semantics): failures are counted via the safe
        log line below, which carries metadata only.
        """
        try:
            await self.repository.create_api_request_record(record)
            return True
        except Exception:
            logger.warning(
                "telemetry_write_dropped method=%s route=%s status=%s",
                record.method,
                record.route_template,
                record.status_code,
            )
            return False

    # ------------------------------------------------------------------
    # Agent execution trace write path (best effort; PRD 17 O-6)
    # ------------------------------------------------------------------
    async def record_agent_run(self, record: AgentRunRecord) -> bool:
        """Persist one agent execution trace without ever raising.

        Returns True when persisted, False when dropped. Follows the
        approved best-effort telemetry write semantics: persistence
        failure is logged safely and must never fail the caller.
        """
        try:
            await self.repository.create_agent_run_record(record)
            return True
        except Exception:
            logger.warning(
                "agent_run_trace_dropped run_id=%s tenant=%s status=%s",
                record.id,
                record.tenant_id,
                record.status,
            )
            return False

    async def get_agent_run_trace(self, tenant_id: str, record_id: str) -> AgentRunRecord:
        """Read one agent execution trace within the trusted tenant."""
        return await self.repository.get_agent_run_record(record_id, tenant_id)

    async def list_agent_run_traces(
        self, tenant_id: str, hours: int = DEFAULT_WINDOW_HOURS
    ) -> list:
        """List agent run traces for a tenant within a time window."""
        window = self._validated_window(hours)
        return await self.repository.list_agent_run_records(tenant_id, window)

    # ------------------------------------------------------------------
    # LLM usage telemetry write path (best effort; V2-ADR-024, Issue #141)
    # ------------------------------------------------------------------
    async def record_llm_usage(self, record: LlmUsageRecord) -> bool:
        """Persist one LLM usage telemetry record without ever raising.

        Returns True when persisted, False when dropped. Follows the
        approved best-effort telemetry write semantics: persistence
        failure is logged safely and must never fail the caller or the
        primary LLM workflow (TRD 24).
        """
        try:
            await self.repository.create_llm_usage_record(record)
            return True
        except Exception:
            logger.warning(
                "llm_usage_dropped provider=%s model=%s call_type=%s",
                record.provider,
                record.model,
                record.call_type,
            )
            return False

    async def get_llm_usage(self, tenant_id: str, hours: int = DEFAULT_WINDOW_HOURS) -> dict:
        """Return aggregated LLM usage for a tenant."""
        window = self._validated_window(hours)
        return await self.repository.llm_usage_activity(tenant_id, window)

    async def get_llm_usage_records(
        self,
        tenant_id: str,
        hours: int = DEFAULT_WINDOW_HOURS,
        call_type: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Return paginated LLM usage records for a tenant."""
        window = self._validated_window(hours)
        limit = max(1, min(200, limit))
        offset = max(0, offset)
        records, total = await self.repository.llm_usage_records_page(
            tenant_id, window, call_type, limit, offset
        )
        return {"records": records, "limit": limit, "offset": offset, "total": total}

    # ------------------------------------------------------------------
    # Aggregation reads
    # ------------------------------------------------------------------
    @staticmethod
    def _validated_window(hours: int) -> int:
        if not isinstance(hours, int) or isinstance(hours, bool):
            raise ValueError("Window hours must be an integer")
        if not MIN_WINDOW_HOURS <= hours <= MAX_WINDOW_HOURS:
            raise ValueError(
                f"Window hours must be between {MIN_WINDOW_HOURS} and {MAX_WINDOW_HOURS}"
            )
        return hours

    async def get_tenant_usage_summary(
        self, tenant_id: str, hours: int = DEFAULT_WINDOW_HOURS
    ) -> Dict[str, Any]:
        """Assemble the tenant-scoped usage summary (aggregates only)."""
        window = self._validated_window(hours)
        http = await self.repository.api_request_summary(tenant_id, window)
        tools = await self.repository.tool_execution_activity(tenant_id, window)
        connectors = await self.repository.connector_sync_activity(tenant_id, window)
        webhooks = await self.repository.webhook_event_activity(tenant_id, window)
        approvals = await self.repository.approval_activity(tenant_id, window)
        escalation_count = await self.repository.escalation_count(tenant_id, window)
        agent_runs = await self.repository.agent_run_activity(tenant_id, window)
        llm = await self.repository.llm_usage_activity(tenant_id, window)
        return {
            "window_hours": window,
            "http": self._http_payload(http),
            "tools": {
                "total_executions": tools.total_executions,
                "successful": tools.successful,
                "failed": tools.failed,
                "denied": tools.denied,
            },
            "connectors": {
                "total_syncs": connectors.total_syncs,
                "successful": connectors.successful,
                "failed": connectors.failed,
                "items_fetched": connectors.items_fetched,
            },
            "webhooks": {
                "available": webhooks.available,
                "total_events": webhooks.total_events,
                "distinct_event_types": webhooks.distinct_event_types,
                "total_payload_bytes": webhooks.total_payload_bytes,
            },
            "approvals": {
                "total": approvals.total,
                "pending": approvals.pending,
                "approved": approvals.approved,
                "rejected": approvals.rejected,
                "expired": approvals.expired,
                "consumed": approvals.consumed,
            },
            "escalation_count": escalation_count,
            "agent_runs": {
                "total_runs": agent_runs.total_runs,
                "succeeded": agent_runs.succeeded,
                "failed": agent_runs.failed,
                "approval_required": agent_runs.approval_required,
                "max_steps_reached": agent_runs.max_steps_reached,
            },
            "llm": self._llm_payload(llm),
        }

    async def get_platform_summary(self, hours: int = DEFAULT_WINDOW_HOURS) -> Dict[str, Any]:
        """Assemble the STRICTLY TENANT-AGNOSTIC platform summary.

        Answers only: is the ARC platform operating correctly? No tenant
        identifiers, per-tenant usage, rankings, or breakdowns are ever
        included (approved Joe/Bala policy).
        """
        window = self._validated_window(hours)
        http = await self.repository.api_request_summary(None, window)
        tools = await self.repository.tool_execution_activity(None, window)
        connectors = await self.repository.connector_sync_activity(None, window)
        webhooks = await self.repository.webhook_event_activity(None, window)
        approvals = await self.repository.approval_activity(None, window)
        escalation_count = await self.repository.escalation_count(None, window)
        agent_runs = await self.repository.agent_run_activity(None, window)
        return {
            "window_hours": window,
            "http": self._http_payload(http),
            "tool_activity_total": tools.total_executions,
            "tool_failures_total": tools.failed + tools.denied,
            "connector_syncs_total": connectors.total_syncs,
            "connector_failures_total": connectors.failed,
            "webhook_events_total": webhooks.total_events if webhooks.available else 0,
            "webhook_source_available": webhooks.available,
            "approval_activity_total": approvals.total,
            "approval_failures_total": approvals.rejected + approvals.expired,
            "escalation_count_total": escalation_count,
            "agent_runs_total": agent_runs.total_runs,
            "agent_runs_succeeded": agent_runs.succeeded,
            "agent_runs_failed": agent_runs.failed,
        }

    @staticmethod
    def _http_payload(http) -> Dict[str, Any]:
        return {
            "total_requests": http.total_requests,
            "error_count": http.error_count,
            "error_rate": round(http.error_rate, 4),
            "avg_duration_ms": round(http.avg_duration_ms, 2),
            "p95_duration_ms": round(http.p95_duration_ms, 2),
        }

    @staticmethod
    def _llm_payload(llm) -> Dict[str, Any]:
        return {
            "total_calls": llm.total_calls,
            "total_tokens": llm.total_tokens,
            "avg_latency_ms": round(llm.avg_latency_ms, 2),
            "total_cost_usd": float(llm.total_cost_usd) if llm.total_cost_usd is not None else None,
            "unknown_cost_records": llm.unknown_cost_records,
            "cost_coverage": llm.cost_coverage,
        }

    # ------------------------------------------------------------------
    # Component health
    # ------------------------------------------------------------------
    async def get_component_health(self) -> Dict[str, Any]:
        """Evaluate real component checks using existing public contracts.

        Results expose status labels only — never settings values, error
        details, or anything that could leak configuration material.
        """
        components: Dict[str, Dict[str, str]] = {}
        database_status = "healthy" if await self.repository.database_reachable() else "unhealthy"
        components["database"] = {"status": database_status}
        components["llm_provider"] = self._probe(lambda: build_llm_provider(get_llm_settings()))
        components["embeddings"] = self._probe(
            lambda: build_embedding_provider(get_embedding_settings())
        )
        all_healthy = all(c["status"] == "healthy" for c in components.values())
        overall = "healthy" if all_healthy else "degraded"
        return {"overall": overall, "components": components}

    @staticmethod
    def _probe(build) -> Dict[str, str]:
        try:
            build()
            return {"status": "healthy"}
        except Exception:
            return {"status": "unhealthy"}
