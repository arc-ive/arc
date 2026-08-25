"""Environment-driven webhook ingestion endpoint configuration.

Secret boundary (mirrors the connector credential contract)
-----------------------------------------------------------

Webhook ingestion endpoints are provisioned through the runtime
environment only, as a JSON object keyed by endpoint ID. Each entry binds
ONE endpoint to EXACTLY ONE tenant and carries the HMAC signing secret
for that endpoint:

    {"<endpoint-id>": {"tenant_id": "<tenant-id>", "secret": "<secret>"}}

This is the current-phase development/demo mechanism (the same class of
mechanism as ``CONNECTOR_CREDENTIALS``). Secrets are NOT:

- accepted from tenant request payloads
- stored in database tables
- returned through API responses
- included in exceptions
- written to application logs or audit records
- exposed through ``repr`` or debug output

Tenant binding is a security property: an inbound event's tenant comes
EXCLUSIVELY from the matched endpoint's configured ``tenant_id`` — never
from request input (ADR-001 webhook security boundary). Unknown or
malformed configuration fails closed at lookup time.

Deferred decisions (not part of this slice): per-endpoint CRUD APIs,
secret rotation lifecycle, secure secret storage, and multiple endpoints
per tenant.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

MIN_SECRET_LENGTH = 16
MAX_ENDPOINT_ID_LENGTH = 255


class WebhookConfigurationError(Exception):
    """Raised when the webhook endpoint configuration is missing or invalid."""


@dataclass(frozen=True)
class WebhookEndpointConfig:
    """One ingestion endpoint: its tenant binding and signing secret.

    The secret never appears in ``repr`` or ``str`` output.
    """

    endpoint_id: str
    tenant_id: str
    secret: str

    def __repr__(self) -> str:
        return (
            f"WebhookEndpointConfig(endpoint_id={self.endpoint_id!r}, "
            f"tenant_id={self.tenant_id!r}, secret=***)"
        )

    def __str__(self) -> str:
        return self.__repr__()


def parse_webhook_endpoints(raw: str) -> Dict[str, WebhookEndpointConfig]:
    """Parse the WEBHOOK_INGESTION_ENDPOINTS JSON into endpoint configs.

    Fails closed on malformed JSON, non-object roots, empty/oversized
    endpoint IDs, missing tenant bindings, or secrets shorter than
    ``MIN_SECRET_LENGTH``.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebhookConfigurationError("WEBHOOK_INGESTION_ENDPOINTS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise WebhookConfigurationError("WEBHOOK_INGESTION_ENDPOINTS must be a JSON object")

    endpoints: Dict[str, WebhookEndpointConfig] = {}
    for endpoint_id, entry in parsed.items():
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise WebhookConfigurationError(
                "WEBHOOK_INGESTION_ENDPOINTS keys must be non-empty endpoint IDs"
            )
        if len(endpoint_id) > MAX_ENDPOINT_ID_LENGTH:
            raise WebhookConfigurationError(
                f"Webhook endpoint ID cannot exceed {MAX_ENDPOINT_ID_LENGTH} characters"
            )
        if not isinstance(entry, dict):
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' must map to a JSON object"
            )
        tenant_id = entry.get("tenant_id")
        secret = entry.get("secret")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' must define a non-empty 'tenant_id'"
            )
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' must define a 'secret' of at "
                f"least {MIN_SECRET_LENGTH} characters"
            )
        endpoints[endpoint_id] = WebhookEndpointConfig(
            endpoint_id=endpoint_id,
            tenant_id=tenant_id,
            secret=secret,
        )
    return endpoints


class WebhookEndpointStore:
    """Resolves ingestion endpoints from the environment.

    Configuration is read lazily from the environment on every lookup so
    tests and deployments can provision endpoints without restarting the
    application. Lookups fail closed: an unknown endpoint returns None.
    """

    def __init__(self, raw: Optional[str] = None):
        self._raw = raw

    def get(self, endpoint_id: str) -> Optional[WebhookEndpointConfig]:
        """Return the endpoint config for ``endpoint_id``, or None."""
        raw = self._raw if self._raw is not None else os.getenv("WEBHOOK_INGESTION_ENDPOINTS", "")
        endpoints = parse_webhook_endpoints(raw)
        return endpoints.get(endpoint_id)
