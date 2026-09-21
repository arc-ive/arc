"""Webhook downstream processing pipeline (Issue #102, #136, PRD 16).

Implements the webhook-to-Skill execution pipeline that transitions
received webhook events through processing to processed or failed.
This service is the controlled boundary between webhook ingestion and
the existing Skill/Tool execution stack.

Security invariants:

- Tenant identity comes EXCLUSELY from the endpoint configuration
  (``tenant_id``) and the authoritative tenant store (``tenant.name``).
  Request input never selects a tenant.
- The system principal (``system:webhook``) holds only
  ``WEBHOOK_PROCESSOR`` permissions (``skill:execute`` + ``tool:execute``).
  ``TenantContext.role`` (UserRole.OWNER) is invisible to the
  authorization layer and grants zero additional permissions.
- All downstream execution flows through the existing
  ``SkillExecutionService`` → ``ToolExecutionService`` boundary.
  No parallel execution path is created.
- PII Guard is applied to the ``event_type`` label before any
  downstream use. No raw payload, signing secret, or untrusted
  metadata reaches Skills or Tools.
- At most one processor can atomically claim a received event.
  Downstream execution is best-effort; a crash during processing
  leaves the event in ``processing`` status (manual recovery).
- Retries use a deterministic idempotency key derived from the
  webhook event to prevent duplicate downstream side effects
  (V2-ADR-019, Issue #136).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from arc.db.connection import NotFoundError
from arc.domain.models import (
    SkillExecutionStatus,
    TenantContext,
    UserRole,
    WebhookEventStatus,
)
from arc.repositories import TenantRepository, WebhookEventRepository
from arc.security.authorization import AuthorizationService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.pii import PiiGuardService
from arc.services.skill_execution import SkillExecutionService
from arc.services.tools import ToolDeniedError
from arc.services.webhook_config import WebhookEndpointStore

logger = logging.getLogger("arc.services.webhook_pipeline")

# System principal for webhook-triggered execution. The user_id is
# distinguishable in audit records (ToolExecutionRecord.user_id,
# SkillExecutionResult.principal_id). The WEBHOOK_PROCESSOR role
# grants ONLY skill:execute + tool:execute.
_SYSTEM_USER_ID = "system:webhook"

# Safe, generic error kinds for pipeline failures. Raw exceptions and
# internal details never cross this boundary.
_ERROR_NO_ACTION = "no_action_configured"
_ERROR_UNKNOWN_ACTION_TYPE = "unknown_action_type"
_ERROR_CONFIGURATION = "configuration_error"
_ERROR_DOWNSTREAM = "downstream_execution_error"
_ERROR_INTERNAL = "pipeline_internal_error"
_ERROR_DISALLOWED_TOOL = "disallowed_tool"
_ERROR_AUTHORIZATION = "authorization_error"

# Retry configuration defaults.
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY_SECONDS = 10
DEFAULT_MAX_DELAY_SECONDS = 300

# Error kinds that are NEVER retried (permanent/auth/policy failures).
# These go straight to failed. Authentication failures (HMAC) never
# reach the pipeline. Authorization/policy failures are permanent.
_PERMANENT_ERROR_KINDS = frozenset(
    {
        _ERROR_NO_ACTION,
        _ERROR_UNKNOWN_ACTION_TYPE,
        _ERROR_CONFIGURATION,
        _ERROR_DISALLOWED_TOOL,
        _ERROR_AUTHORIZATION,
    }
)


def is_transient_failure(error_kind: str) -> bool:
    """Return True if the error kind represents a retryable transient failure.

    Transient failures are: downstream execution errors and internal
    pipeline errors. Configuration, action, authorization, and policy
    errors are permanent.
    """
    return error_kind not in _PERMANENT_ERROR_KINDS


def compute_retry_delay(retry_count: int, base_delay: float = DEFAULT_BASE_DELAY_SECONDS) -> float:
    """Compute exponential backoff delay in seconds.

    delay = base_delay * 2^retry_count, capped at DEFAULT_MAX_DELAY_SECONDS.
    """
    delay = base_delay * (2**retry_count)
    return min(delay, DEFAULT_MAX_DELAY_SECONDS)


def classify_failure(error_kind: str, retry_count: int, max_retries: int) -> str:
    """Classify a failure into next action: 'retry', 'dead_letter', or 'failed'.

    Returns 'retry' if the failure is transient and retries remain,
    'dead_letter' if retries are exhausted, 'failed' for permanent
    errors.
    """
    if error_kind in _PERMANENT_ERROR_KINDS:
        return "failed"
    if retry_count >= max_retries:
        return "dead_letter"
    return "retry"


def compute_idempotency_key(tenant_id: str, event_id: str) -> str:
    """Compute a deterministic idempotency key for a webhook event.

    The key is scoped to (tenant, event) and is stable across retries.
    Per-tool-step differentiation is handled by SkillExecutionService
    which appends the step index.
    """
    return f"webhook:{tenant_id}:{event_id}"


class WebhookProcessingError(Exception):
    """Controlled failure of a webhook processing attempt."""

    def __init__(self, error_kind: str, message: str):
        self.error_kind = error_kind
        super().__init__(message)


class WebhookPipelineService:
    """Orchestrates downstream processing of received webhook events.

    The pipeline reads a received event, atomically claims it for
    processing, resolves the configured downstream action, and routes
    the event through the existing SkillExecutionService. On success
    the event transitions to ``processed``; on any failure it
    transitions to ``failed`` or ``retrying`` with a safe error category.
    """

    def __init__(
        self,
        webhook_repository: WebhookEventRepository,
        endpoint_store: WebhookEndpointStore,
        tenant_repository: TenantRepository,
        skill_execution_service: SkillExecutionService,
        pii_guard: PiiGuardService,
    ):
        self._webhook_repository = webhook_repository
        self._endpoint_store = endpoint_store
        self._tenant_repository = tenant_repository
        self._skill_execution_service = skill_execution_service
        self._pii_guard = pii_guard

    async def process(self, tenant_id: str, event_id: str) -> Dict[str, Any]:
        """Process a received webhook event through the downstream pipeline.

        Args:
            tenant_id: the trusted tenant ID from the authenticated context.
            event_id: the sender-supplied event identifier (external dedup ID).

        Returns:
            A dict with the updated event metadata and processing status.

        Raises:
            NotFoundError: the event does not exist, is not in 'received'
                or 'retrying' status, or belongs to a different tenant.
            WebhookProcessingError: a handled pipeline failure. The event
                is in 'failed', 'retrying', or 'dead_letter' status.
        """
        # Step 1: Atomically claim the event (received -> processing, or
        # retrying -> processing). At most one processor wins this race.
        try:
            event = await self._webhook_repository.claim_for_processing(event_id, tenant_id)
        except NotFoundError:
            # Try claiming from retrying status using a dedicated single-event
            # claim (C1 fix: no longer claims unrelated events).
            claimed = await self._webhook_repository.claim_single_for_retry(event_id, tenant_id)
            if claimed is None:
                logger.debug(
                    "Webhook event %s not claimable for tenant %s",
                    event_id,
                    tenant_id,
                )
                raise NotFoundError("Webhook event not found")
            event = claimed

        # Compute deterministic idempotency key for downstream dedup.
        idempotency_key = compute_idempotency_key(tenant_id, event_id)

        try:
            await self._execute_downstream(
                tenant_id, event.endpoint_id, event.event_type, idempotency_key
            )
            # Step 2a: Downstream succeeded -> processed.
            await self._webhook_repository.mark_processed(event_id, tenant_id)
            logger.info(
                "Webhook event processed successfully",
                extra={"event_id": event_id, "tenant_id": tenant_id},
            )
            return {
                "id": event.id,
                "tenant_id": event.tenant_id,
                "endpoint_id": event.endpoint_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "status": WebhookEventStatus.PROCESSED.value,
                "payload_size_bytes": event.payload_size_bytes,
                "created_at": event.created_at.isoformat(),
                "duplicate": False,
            }
        except WebhookProcessingError as exc:
            # Classify the failure and choose next action.
            action = classify_failure(exc.error_kind, event.retry_count, event.max_retries)
            if action == "retry":
                new_retry_count = event.retry_count + 1
                try:
                    await self._schedule_retry(
                        event_id, tenant_id, event.retry_count, exc.error_kind
                    )
                except Exception:
                    logger.exception(
                        "Failed to schedule retry, marking as failed",
                        extra={"event_id": event_id, "tenant_id": tenant_id},
                    )
                    try:
                        await self._webhook_repository.mark_failed(
                            event_id, tenant_id, exc.error_kind
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark webhook event as failed",
                            extra={"event_id": event_id, "tenant_id": tenant_id},
                        )
                    raise exc
                return {
                    "id": event.id,
                    "tenant_id": event.tenant_id,
                    "endpoint_id": event.endpoint_id,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "status": WebhookEventStatus.RETRYING.value,
                    "payload_size_bytes": event.payload_size_bytes,
                    "created_at": event.created_at.isoformat(),
                    "retry_count": new_retry_count,
                }
            elif action == "dead_letter":
                try:
                    await self._webhook_repository.mark_dead_letter(
                        event_id, tenant_id, exc.error_kind
                    )
                except Exception:
                    logger.exception(
                        "Failed to mark webhook event as dead letter",
                        extra={"event_id": event_id, "tenant_id": tenant_id},
                    )
                raise
            else:
                # Permanent failure -> failed.
                try:
                    await self._webhook_repository.mark_failed(event_id, tenant_id, exc.error_kind)
                except Exception:
                    logger.exception(
                        "Failed to mark webhook event as failed",
                        extra={"event_id": event_id, "tenant_id": tenant_id},
                    )
                raise
        except Exception as exc:
            # Step 2b: Unexpected failure -> classify and retry or fail.
            error_kind = _ERROR_INTERNAL
            action = classify_failure(error_kind, event.retry_count, event.max_retries)
            if action == "retry":
                new_retry_count = event.retry_count + 1
                await self._schedule_retry(event_id, tenant_id, event.retry_count, error_kind)
                return {
                    "id": event.id,
                    "tenant_id": event.tenant_id,
                    "endpoint_id": event.endpoint_id,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "status": WebhookEventStatus.RETRYING.value,
                    "payload_size_bytes": event.payload_size_bytes,
                    "created_at": event.created_at.isoformat(),
                    "retry_count": new_retry_count,
                }
            elif action == "dead_letter":
                try:
                    await self._webhook_repository.mark_dead_letter(event_id, tenant_id, error_kind)
                except Exception:
                    logger.exception(
                        "Failed to mark webhook event as dead letter",
                        extra={"event_id": event_id, "tenant_id": tenant_id},
                    )
            else:
                try:
                    await self._webhook_repository.mark_failed(event_id, tenant_id, error_kind)
                except Exception:
                    logger.exception(
                        "Failed to mark webhook event as failed",
                        extra={"event_id": event_id, "tenant_id": tenant_id},
                    )
            raise WebhookProcessingError(
                error_kind,
                f"Webhook processing failed: {error_kind}",
            ) from exc

    async def _schedule_retry(
        self, event_id: str, tenant_id: str, current_retry_count: int, error_kind: str
    ) -> None:
        """Schedule the next retry attempt with exponential backoff."""
        new_retry_count = current_retry_count + 1
        delay = compute_retry_delay(current_retry_count)
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        await self._webhook_repository.mark_retrying(
            event_id, tenant_id, new_retry_count, next_retry_at
        )
        logger.info(
            "Webhook event scheduled for retry",
            extra={
                "event_id": event_id,
                "tenant_id": tenant_id,
                "retry_count": new_retry_count,
                "delay_seconds": delay,
                "error_kind": error_kind,
            },
        )

    async def _execute_downstream(
        self,
        tenant_id: str,
        endpoint_id: str,
        event_type: str,
        idempotency_key: str,
    ) -> None:
        """Execute the configured downstream action for an endpoint.

        Resolves the endpoint configuration, validates the action,
        constructs the system context, and delegates to
        SkillExecutionService.

        The ``idempotency_key`` is derived from the webhook event and
        passed through to prevent duplicate side effects on retry.

        Raises:
            WebhookProcessingError: on any handled failure.
        """
        # Resolve endpoint configuration.
        config = self._endpoint_store.get(endpoint_id)
        if config is None or config.action is None:
            raise WebhookProcessingError(
                _ERROR_NO_ACTION,
                f"No action configured for endpoint '{endpoint_id}'",
            )

        action = config.action
        if action.type != "skill":
            raise WebhookProcessingError(
                _ERROR_UNKNOWN_ACTION_TYPE,
                f"Action type '{action.type}' not supported",
            )

        # Resolve tenant name from the authoritative store.
        try:
            tenant = await self._tenant_repository.get_by_id(tenant_id)
        except NotFoundError:
            raise WebhookProcessingError(
                _ERROR_CONFIGURATION,
                f"Tenant '{tenant_id}' not found",
            )

        # Sanitize event_type before any downstream use.
        sanitized_type = self._pii_guard.sanitize(event_type).sanitized_text
        logger.debug(
            "Processing webhook event type: %s (sanitized)",
            sanitized_type,
        )

        # Construct system context. TenantContext.role is OWNER but this
        # is invisible to AuthorizationService — only the ApplicationRole
        # (WEBHOOK_PROCESSOR) matters for permission checks.
        context = TenantContext(
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            user_id=_SYSTEM_USER_ID,
            role=UserRole.OWNER,
        )
        principal = AuthenticatedPrincipal(user_id=_SYSTEM_USER_ID)
        authorization = AuthorizationService({_SYSTEM_USER_ID: ApplicationRole.WEBHOOK_PROCESSOR})

        # Delegate to the existing Skill execution boundary.
        try:
            result = await self._skill_execution_service.execute(
                context,
                principal,
                action.skill_id,
                action.tool_calls,
                action.satisfied_conditions,
                authorization,
                idempotency_key=idempotency_key,
            )
        except (ValueError, NotFoundError) as exc:
            raise WebhookProcessingError(
                _ERROR_CONFIGURATION,
                f"Skill execution configuration error: {_ERROR_CONFIGURATION}",
            ) from exc
        except ToolDeniedError as exc:
            # F1 fix: ToolDeniedError from authorization or policy is
            # permanent — never retry. Maps to authorization_error or
            # disallowed_tool depending on the underlying cause.
            error_kind = _ERROR_AUTHORIZATION
            raise WebhookProcessingError(
                error_kind,
                f"Tool execution denied: {error_kind}",
            ) from exc

        # Any non-success status from SkillExecutionService is a failure.
        if result.status is not SkillExecutionStatus.SUCCEEDED:
            error_kind = result.error_kind or _ERROR_DOWNSTREAM
            raise WebhookProcessingError(
                error_kind,
                f"Skill execution failed: {error_kind}",
            )
