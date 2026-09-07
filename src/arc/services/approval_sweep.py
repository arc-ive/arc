"""Background approval expiry sweep (PRD §15).

Provides a periodic asyncio task that transitions stale pending approval
requests to terminal ``expired`` at the persistence layer.  This is
maintenance-only: it does NOT execute tools, grant/consume approvals,
or modify authorization state.

Lifecycle integration: ``start_approval_sweep`` / ``stop_approval_sweep``
are called from the application startup/shutdown hooks.
"""

import asyncio
import logging

from arc.services.approvals import HumanApprovalService

logger = logging.getLogger("arc.approval_sweep")

DEFAULT_INTERVAL_SECONDS = 300  # 5 minutes


async def _sweep_loop(
    approval_service: HumanApprovalService,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    """Periodic sweep loop.  Runs until *stop_event* is set."""
    while not stop_event.is_set():
        try:
            await approval_service.sweep_expired_approvals()
        except Exception:
            logger.exception("approval_sweep_error")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


class ApprovalSweepRunner:
    """Manages the background sweep task lifecycle.

    Usage::

        runner = ApprovalSweepRunner(approval_service)
        await runner.start()   # in startup hook
        await runner.stop()    # in shutdown hook
    """

    def __init__(
        self,
        approval_service: HumanApprovalService,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._approval_service = approval_service
        self._interval_seconds = interval_seconds
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background sweep task (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            _sweep_loop(self._approval_service, self._interval_seconds, self._stop_event),
            name="approval-expiry-sweep",
        )

    async def stop(self) -> None:
        """Stop the background sweep task gracefully (idempotent)."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self._stop_event = None
