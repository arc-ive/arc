"""Background webhook retry sweep (Issue #136, V2-ADR-019, TRD 22).

Provides a periodic asyncio task that:
1. Claims events in 'retrying' status whose next_retry_at has passed.
2. Re-processes them through the WebhookPipelineService.
3. Recovers stuck 'processing' events (crash recovery) with exactly
   one re-processing attempt before dead-lettering (Issue #178).

Tenant iteration uses the WebhookEndpointStore to discover configured
tenants. Events are processed per-tenant to maintain isolation.

Lifecycle integration: ``start_retry_sweep`` / ``stop_retry_sweep``
are called from the application startup/shutdown hooks.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Set

from arc.db.connection import NotFoundError
from arc.domain.models import WebhookEvent, WebhookEventStatus
from arc.services.webhook_pipeline import WebhookPipelineService, WebhookProcessingError

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
                await _sweep_stuck_for_tenant(pipeline_service, tenant_id, stuck_threshold_seconds)
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
    """Process due retryable events for one tenant (Issue #178).

    Due events are LISTED (never pre-claimed): each event is then
    processed through the pipeline, which performs the atomic claim
    itself. A pre-claim here would strand the event in 'processing'
    status that the pipeline can no longer claim. A concurrent worker
    that wins the race surfaces as NotFoundError and is skipped.
    """
    repo = pipeline_service._webhook_repository
    try:
        due_events = await repo.list_due_retrying(tenant_id, limit=10)
    except Exception:
        logger.exception(
            "Failed to list due retryable events",
            extra={"tenant_id": tenant_id},
        )
        return

    for event in due_events:
        try:
            await pipeline_service.process(tenant_id, event.event_id)
            logger.info(
                "Retry sweep processed event",
                extra={"event_id": event.event_id, "tenant_id": tenant_id},
            )
        except NotFoundError:
            # Concurrently claimed by another worker; nothing to do.
            logger.info(
                "Retry sweep skipped concurrently claimed event",
                extra={"event_id": event.event_id, "tenant_id": tenant_id},
            )
        except WebhookProcessingError as exc:
            # Handled terminal verdict: the pipeline already persisted
            # the outcome (failed/retrying/dead_letter). INFO, no
            # traceback — this is not an unexpected failure.
            logger.info(
                "Retry sweep recorded terminal outcome",
                extra={
                    "event_id": event.event_id,
                    "tenant_id": tenant_id,
                    "error_kind": exc.error_kind,
                },
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
    """Recover events stuck in 'processing' beyond the threshold (Issue #178).

    Each stuck event gets exactly ONE recovery attempt through the
    existing pipeline boundary: it is moved back to 'retrying'
    (immediately due, retry metadata preserved) so the pipeline's
    atomic single-event claim applies, then re-processed. A recovered
    event ends in 'processed'; any other non-terminal outcome ends in
    'dead_letter'. No recovery loops are created.

    Downstream side effects stay idempotent: recovery reuses the same
    (tenant_id, event_id) identity, hence the same deterministic
    idempotency key, as normal processing.
    """
    repo = pipeline_service._webhook_repository
    try:
        stuck_events = await repo.sweep_stuck_processing(tenant_id, stuck_threshold_seconds)
    except Exception:
        logger.exception(
            "Failed to sweep stuck processing events",
            extra={"tenant_id": tenant_id},
        )
        return

    for event in stuck_events:
        await _recover_stuck_event(pipeline_service, tenant_id, event)


async def _recover_stuck_event(
    pipeline_service: WebhookPipelineService,
    tenant_id: str,
    event: WebhookEvent,
) -> None:
    """Attempt exactly one recovery processing for a stuck event.

    The event is first moved processing -> retrying (immediately due,
    retry count preserved: this resumes the interrupted attempt, it is
    not a new one) so ``pipeline.process`` can claim it. Afterwards the
    authoritative record decides:

    - ``processed``: recovery succeeded; nothing further to do.
    - ``failed`` / ``dead_letter``: the pipeline already recorded its
      terminal verdict; it stands.
    - ``processing`` / ``retrying``: recovery did not complete; move
      to ``dead_letter`` so the event cannot block indefinitely.

    Every failure is contained per event; the sweep continues.
    """
    repo = pipeline_service._webhook_repository
    try:
        await repo.mark_retrying(
            event.event_id, tenant_id, event.retry_count, datetime.now(timezone.utc)
        )
    except Exception:
        logger.exception(
            "Failed to re-queue stuck event for recovery",
            extra={"event_id": event.event_id, "tenant_id": tenant_id},
        )
        return

    try:
        await pipeline_service.process(tenant_id, event.event_id)
    except WebhookProcessingError as exc:
        # Handled terminal verdict, already persisted by the pipeline.
        logger.info(
            "Stuck event recovery recorded terminal outcome",
            extra={
                "event_id": event.event_id,
                "tenant_id": tenant_id,
                "error_kind": exc.error_kind,
            },
        )
    except Exception:
        logger.exception(
            "Stuck event recovery processing failed",
            extra={"event_id": event.event_id, "tenant_id": tenant_id},
        )

    try:
        current = await repo.get_by_event_id(event.event_id, tenant_id)
    except NotFoundError:
        return
    except Exception:
        logger.exception(
            "Failed to re-read stuck event after recovery",
            extra={"event_id": event.event_id, "tenant_id": tenant_id},
        )
        return
    if current.status is WebhookEventStatus.PROCESSED:
        logger.info(
            "Stuck event recovered to processed",
            extra={"event_id": event.event_id, "tenant_id": tenant_id},
        )
        return
    if current.status not in (WebhookEventStatus.PROCESSING, WebhookEventStatus.RETRYING):
        # Pipeline already recorded a terminal verdict (failed/dead_letter).
        return
    try:
        await repo.mark_dead_letter(event.event_id, tenant_id, "stuck_processing")
        logger.warning(
            "Stuck event recovery failed; moved to dead_letter",
            extra={"event_id": event.event_id, "tenant_id": tenant_id},
        )
    except NotFoundError:
        pass  # Reached a terminal state concurrently.
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
