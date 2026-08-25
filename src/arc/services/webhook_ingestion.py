"""Webhook ingestion service (Webhooks foundation slice).

Implements the ADR-001 webhook / operational event security boundary for
the inbound-only foundation scope (PRD 16, TRD 16):

    External/simulated system
        -> POST /webhooks/{endpoint_id}/events   (HMAC-signed)
        -> endpoint resolution (tenant binding from trusted config)
        -> timestamp window check (replay resistance)
        -> HMAC-SHA256 signature verification (constant-time)
        -> payload validation (size, JSON shape, required fields)
        -> tenant-scoped WebhookEvent record (metadata-only)

Security properties:

- The tenant binding comes EXCLUSIVELY from the environment-configured
  endpoint entry. Request input can never select a tenant.
- Authentication is uniform: unknown endpoints, missing headers, stale
  or future timestamps, and signature mismatches all surface as the same
  controlled error so senders cannot enumerate valid endpoints.
- Signatures cover ``{timestamp}.{raw_body}`` with HMAC-SHA256 and are
  compared in constant time; the signed timestamp bounds replay to the
  configured window.
- Duplicate handling (PRD 16): a re-delivered ``(tenant_id, event_id)``
  pair resolves to the original record and is reported as a duplicate
  instead of creating a second row (idempotent receiver semantics).
- Raw payloads are never persisted, logged, returned, or included in
  errors; only safe envelope metadata survives ingestion.

Out of scope for this slice (explicitly deferred): triggering downstream
processing (Unified Intelligence), outbound delivery, retry policy
finalization (TRD 37), per-endpoint CRUD APIs, and secret rotation.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from arc.db.connection import DuplicateKeyError, NotFoundError
from arc.domain.models import TenantContext, WebhookEvent, WebhookEventStatus
from arc.repositories import WebhookEventRepository
from arc.services.webhook_config import WebhookEndpointConfig, WebhookEndpointStore

# Signature scheme: hex(HMAC_SHA256(secret, "{timestamp}.{body}")).
SIGNATURE_SCHEME = "sha256"

# Replay window (seconds): requests whose signed timestamp differs from
# the server time by more than this are rejected.
TIMESTAMP_TOLERANCE_SECONDS = 300

# Inbound body limit: larger bodies are rejected before parsing.
MAX_BODY_BYTES = 65536

# Payload field limits (mirroring the domain model constraints).
MAX_EVENT_TYPE_LENGTH = 100


class WebhookIngestionError(Exception):
    """Controlled failure of a webhook ingestion attempt."""


class WebhookAuthenticationError(WebhookIngestionError):
    """Uniform authentication failure of an ingestion attempt.

    Deliberately carries no reason detail: callers cannot distinguish
    unknown endpoints from bad signatures or stale timestamps.
    """


class WebhookValidationError(WebhookIngestionError):
    """The authenticated request body is not a valid webhook event."""


@dataclass(frozen=True)
class WebhookIngestionResult:
    """Safe result of one ingestion attempt.

    ``duplicate`` reports whether the sender-supplied event identifier
    had already been recorded for the tenant (PRD 16 duplicate
    handling); duplicate deliveries never create a second record.
    """

    event: WebhookEvent
    duplicate: bool = False


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Compute the expected HMAC-SHA256 signature for a delivery.

    The signature covers ``"{timestamp}.{raw_body}"`` so the freshness
    claim cannot be separated from the signed content.
    """
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class WebhookIngestionService:
    """Controlled inbound webhook ingestion (PRD 16, TRD 16, ADR-001)."""

    def __init__(
        self,
        endpoint_store: WebhookEndpointStore,
        repository: WebhookEventRepository,
        now=None,
    ):
        self._endpoint_store = endpoint_store
        self._repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def ingest(
        self,
        endpoint_id: str,
        timestamp_header: str,
        signature_header: str,
        body: bytes,
    ) -> WebhookIngestionResult:
        """Authenticate, validate, and record one inbound webhook delivery."""
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise WebhookAuthenticationError()
        endpoint = self._endpoint_store.get(endpoint_id)
        if endpoint is None:
            raise WebhookAuthenticationError()

        self._verify_authentication(endpoint, timestamp_header, signature_header, body)
        payload = self._parse_payload(body)

        event_id = payload["event_id"]
        try:
            existing = await self._repository.get_by_event_id(event_id, endpoint.tenant_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return WebhookIngestionResult(event=existing, duplicate=True)

        event = WebhookEvent(
            id=str(uuid.uuid4()),
            tenant_id=endpoint.tenant_id,
            endpoint_id=endpoint.endpoint_id,
            event_id=event_id,
            event_type=payload["event_type"],
            status=WebhookEventStatus.RECEIVED,
            payload_size_bytes=len(body),
        )
        try:
            stored = await self._repository.create(event)
        except DuplicateKeyError:
            # A concurrent delivery of the same event won the race; report
            # it idempotently instead of failing the sender.
            stored = await self._repository.get_by_event_id(event_id, endpoint.tenant_id)
            return WebhookIngestionResult(event=stored, duplicate=True)
        return WebhookIngestionResult(event=stored, duplicate=False)

    async def list_events(self, context: TenantContext, limit: int = 50) -> list:
        """List recent events for the caller's trusted tenant."""
        return await self._repository.list_for_tenant(context.tenant_id, limit)

    def _verify_authentication(
        self,
        endpoint: WebhookEndpointConfig,
        timestamp_header: str,
        signature_header: str,
        body: bytes,
    ) -> None:
        """Verify timestamp freshness and the HMAC signature.

        Every failure raises the SAME undifferentiated error.
        """
        if not isinstance(timestamp_header, str) or not timestamp_header:
            raise WebhookAuthenticationError()
        if not isinstance(signature_header, str) or not signature_header:
            raise WebhookAuthenticationError()

        try:
            delivered_at = int(timestamp_header)
        except ValueError:
            raise WebhookAuthenticationError() from None
        now_epoch = self._now().timestamp()
        if abs(now_epoch - delivered_at) > TIMESTAMP_TOLERANCE_SECONDS:
            raise WebhookAuthenticationError()

        expected = compute_signature(endpoint.secret, timestamp_header, body)
        if not hmac.compare_digest(expected, signature_header.strip().lower()):
            raise WebhookAuthenticationError()

    @staticmethod
    def _parse_payload(body: bytes) -> dict:
        """Validate the JSON envelope shape and extract safe fields.

        Runs ONLY after successful authentication so error responses
        never help unauthenticated callers probe endpoint existence.
        Only ``event_id``, ``event_type``, and (optionally) a structured
        ``data`` object are accepted. Field values are length-bounded;
        nothing else from the payload is retained anywhere.
        """
        if len(body) > MAX_BODY_BYTES:
            raise WebhookValidationError(f"Webhook body cannot exceed {MAX_BODY_BYTES} bytes")
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WebhookValidationError("Webhook body must be valid UTF-8 JSON") from None
        if not isinstance(parsed, dict):
            raise WebhookValidationError("Webhook body must be a JSON object")

        event_id = parsed.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise WebhookValidationError("Webhook event 'event_id' is required")
        if len(event_id) > 255:
            raise WebhookValidationError("Webhook event 'event_id' cannot exceed 255 characters")

        event_type = parsed.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise WebhookValidationError("Webhook event 'event_type' is required")
        if len(event_type) > MAX_EVENT_TYPE_LENGTH:
            raise WebhookValidationError(
                f"Webhook event 'event_type' cannot exceed {MAX_EVENT_TYPE_LENGTH} characters"
            )

        if "data" in parsed and not isinstance(parsed["data"], dict):
            raise WebhookValidationError("Webhook event 'data' must be a JSON object")

        return {"event_id": event_id, "event_type": event_type}
