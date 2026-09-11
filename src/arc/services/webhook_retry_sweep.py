"""Background webhook retry sweep (Issue #136, V2-ADR-019, TRD 22).

Provides a periodic asyncio task that:
1. Claims events in 'retrying' status whose next_retry_at has passed.
2. Re-processes them through the WebhookPipelineService.
3. Sweeps stuck 'processing' events (crash recovery) to dead-letter.

Tenant iteration uses the WebhookEndpointStore to discover configured
tenants. Events are processed per-tenant to maintain isolation.

Lifecycle integration: ``start_retry_sweep`` / ``stop_retry_sweep``
are called from the application startup/shutdown hooks.
"""

import asyncio
import json
import logging
import os
from typing import Optional, Set

from arc.services.webhook_pipeline import WebhookPipelineService

logger = logging.getLogger("arc.webhook_retry_sweep")

DEFAULT_RETRY_INTERVAL_SECONDS = 30
DEFAULT_STUCK_THRESHOLD_SECONDS = 600


def _get_configured_tenant_ids() -> Set[str]:
    """Extract unique tenant IDs from the WEBHOOK_INGESTION_ENDPOINTS env var."""
    raw = os.getenv("WEBHOOK_INGESTION_ENDPOINTS", "")
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(parsed, dict):
        return set()
    tenants = set()
    for entry in parsed.values():
        if isinstance(entry, dict):
            tid = entry.get("tenant_id")
            if isinstance(tid, str) and tid:
                tenants.add(tid)
    return tenants


async def _retry_sweep_loop(
    pipeline_service: WebhookPipelineService,
    retry_interval_seconds: int,
    stuck_threshold_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    """Periodic retry sweep loop. Runs until *stop_event* is set.

    Each iteration:
    1. Discovers configured tenants from the endpoint environment.
    2. For each tenant, claims and re-processes retryable events.
    3. Sweeps stuck processing events (crash recovery).
    """
    while not stop_event.is_set():
        try:
            tenant_ids = _get_configured_tenant_ids()
            for tenant_id in tenant_ids:
                await _process_retryable_for_tenant(pipeline_service, tenant_id)
                await _sweep_stuck_for_tenant(
                    pipeline_service, tenant_id, stuck_threshold_seconds
                )
        except Exception:
            logger.exception("webhook_retry_sweep_error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=retry_interval_seconds)
        except asyncio.TimeoutError:
            pass


async def _process_retryable_for_tenant(
    pipeline_service: WebhookPipelineService,
    tenant_id: str,
) -> None:
    """Claim and process retryable events for one tenant."""
    repo = pipeline_service._webhook_repository
    try:
        claimed = await repo.claim_for_retry(tenant_id, limit=10)
    except Exception:
        logger.exception(
            "Failed to claim retryable events",
            extra={"tenant_id": tenant_id},
        )
        return

    for event in claimed:
        try:
            await pipeline_service.process(tenant_id, event.event_id)
            logger.info(
                "Retry sweep processed event",
                extra={"event_id": event.event_id, "tenant_id": tenant_id},
            )
        except Exception:
            logger.exception(
                "Retry sweep failed to process event",
                extra={"event_id": event.event_id, "tenant_id": tenant_id},
            )


async def _sweep_stuck_for_tenant(
    pipeline_service: WebhookPipelineService,
    tenant_id: str,
    stuck_threshold_seconds: int,
) -> None:
    """Recover events stuck in 'processing' beyond the threshold.

    Stuck events are moved to 'dead_letter' to prevent indefinite
    blocking. The idempotency key on downstream tool execution records
    ensures that if the original processing succeeded before the crash,
    a retry will not duplicate side effects.
    """
    repo = pipeline_service._webhook_repository
    try:
        stuck_events = await repo.sweep_stuck_processing(
            tenant_id, stuck_threshold_seconds
        )
    except Exception:
        logger.exception(
            "Failed to sweep stuck processing events",
            extra={"tenant_id": tenant_id},
        )
        return

    for event in stuck_events:
        try:
            await repo.mark_dead_letter(
                event.event_id, tenant_id, "stuck_processing"
            )
            logger.warning(
                "Recovered stuck processing event to dead_letter",
                extra={
                    "event_id": event.event_id,
                    "tenant_id": tenant_id,
                    "created_at": event.created_at.isoformat(),
                },
            )
        except Exception:
            logger.exception(
                "Failed to mark stuck event as dead_letter",
                extra={"event_id": event.event_id, "tenant_id": tenant_id},
            )


class WebhookRetrySweepRunner:
    """Manages the background retry sweep task lifecycle.

    Usage::

        runner = WebhookRetrySweepRunner(pipeline_service)
        await runner.start()   # in startup hook
        await runner.stop()    # in shutdown hook
    """

    def __init__(
        self,
        pipeline_service: WebhookPipelineService,
        retry_interval_seconds: int = DEFAULT_RETRY_INTERVAL_SECONDS,
        stuck_threshold_seconds: int = DEFAULT_STUCK_THRESHOLD_SECONDS,
    ) -> None:
        self._pipeline_service = pipeline_service
        self._retry_interval_seconds = retry_interval_seconds
        self._stuck_threshold_seconds = stuck_threshold_seconds
        self._stop_event: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background retry sweep task (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            _retry_sweep_loop(
                self._pipeline_service,
                self._retry_interval_seconds,
                self._stuck_threshold_seconds,
                self._stop_event,
            ),
            name="webhook-retry-sweep",
        )

    async def stop(self) -> None:
        """Stop the background retry sweep task gracefully (idempotent)."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self._stop_event = None
