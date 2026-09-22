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
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arc.services.webhook_config")

MIN_SECRET_LENGTH = 16
MAX_ENDPOINT_ID_LENGTH = 255


class WebhookConfigurationError(Exception):
    """Raised when the webhook endpoint configuration is missing or invalid."""


@dataclass(frozen=True)
class WebhookActionConfig:
    """Downstream action configuration for a webhook endpoint.

    Defines how a received webhook event is routed to an existing Skill.
    The ``type`` field determines the routing strategy; only ``"skill"``
    is supported in V1. The ``skill_id`` is resolved within the
    endpoint's tenant via ``SkillService.get_skill()``. The
    ``tool_calls``, ``satisfied_conditions``, and ``skill_inputs`` are
    passed directly to ``SkillExecutionService.execute()`` which
    enforces all gates (active status, preconditions, declared skill
    inputs, allowed tools, RBAC). Static ``skill_inputs`` let an
    operator satisfy an input-declaring skill; they are never derived
    from webhook payload fields.

    This configuration is platform-operator-controlled (environment
    variable), not tenant-controlled. Tool calls are deterministic and
    static — no LLM or arbitrary code execution.
    """

    type: str
    skill_id: str
    tool_calls: List[Dict[str, Any]]
    satisfied_conditions: List[str]
    skill_inputs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookEndpointConfig:
    """One ingestion endpoint: its tenant binding and signing secret.

    The secret never appears in ``repr`` or ``str`` output.
    """

    endpoint_id: str
    tenant_id: str
    secret: str
    action: Optional[WebhookActionConfig] = None

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
        action = _parse_action(entry.get("action"), endpoint_id)
        endpoints[endpoint_id] = WebhookEndpointConfig(
            endpoint_id=endpoint_id,
            tenant_id=tenant_id,
            secret=secret,
            action=action,
        )
    return endpoints


def _parse_action(raw: Any, endpoint_id: str) -> Optional[WebhookActionConfig]:
    """Parse the optional ``action`` block from an endpoint entry.

    Returns ``None`` when absent (ingestion-only endpoint). Fails closed
    on malformed action configuration.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action must be a JSON object"
        )
    action_type = raw.get("type")
    if not isinstance(action_type, str) or not action_type:
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action must define a non-empty 'type'"
        )
    if action_type != "skill":
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action type '{action_type}' is not "
            f"supported; only 'skill' is supported in V1"
        )
    skill_id = raw.get("skill_id")
    if not isinstance(skill_id, str) or not skill_id:
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action must define a non-empty 'skill_id'"
        )
    tool_calls = raw.get("tool_calls", [])
    if not isinstance(tool_calls, list) or not tool_calls:
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action must define a non-empty 'tool_calls' list"
        )
    for i, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' action tool_call {i} must be a JSON object"
            )
        tool_name = call.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' action tool_call {i} must "
                f"define a non-empty 'tool_name'"
            )
        tool_input = call.get("input", {})
        if not isinstance(tool_input, dict):
            raise WebhookConfigurationError(
                f"Webhook endpoint '{endpoint_id}' action tool_call {i} input must be a JSON object"
            )
    satisfied_conditions = raw.get("satisfied_conditions", [])
    if not isinstance(satisfied_conditions, list):
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action 'satisfied_conditions' must be a list"
        )
    skill_inputs = raw.get("skill_inputs", {})
    if not isinstance(skill_inputs, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in skill_inputs.items()
    ):
        raise WebhookConfigurationError(
            f"Webhook endpoint '{endpoint_id}' action 'skill_inputs' must be an "
            f"object mapping input names to strings"
        )
    return WebhookActionConfig(
        type=action_type,
        skill_id=skill_id,
        tool_calls=tool_calls,
        satisfied_conditions=satisfied_conditions,
        skill_inputs=skill_inputs,
    )


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


def validate_webhook_endpoints(raw: Optional[str] = None) -> Dict[str, WebhookEndpointConfig]:
    """Validate webhook endpoint configuration at startup.

    Parses the configuration and logs warnings for endpoints that have no
    downstream action configured (ingestion-only endpoints). This allows
    operators to verify that processing endpoints are correctly configured
    before any webhook deliveries arrive.

    Args:
        raw: Optional raw JSON string. If None, reads from
            WEBHOOK_INGESTION_ENDPOINTS environment variable.

    Returns:
        Dict of parsed endpoint configs for further validation if needed.

    Raises:
        WebhookConfigurationError: If the configuration is malformed or
            violates structural requirements (fails closed).
    """
    raw = raw if raw is not None else os.getenv("WEBHOOK_INGESTION_ENDPOINTS", "")
    endpoints = parse_webhook_endpoints(raw)

    for endpoint_id, config in endpoints.items():
        if config.action is None:
            logger.warning(
                "Webhook endpoint '%s' (tenant_id=%s) has no action configured; "
                "events will be ingested but NOT processed downstream. "
                "Add an 'action' block to enable Skill execution.",
                endpoint_id,
                config.tenant_id,
            )
        else:
            logger.info(
                "Webhook endpoint '%s' (tenant_id=%s) configured with "
                "action type '%s', skill_id '%s'",
                endpoint_id,
                config.tenant_id,
                config.action.type,
                config.action.skill_id,
            )

    return endpoints
