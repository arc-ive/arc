"""Webhooks foundation: domain model and endpoint configuration tests.

Covers the fail-closed validation contract of ``WebhookEvent`` and the
environment-driven ``WebhookEndpointStore`` configuration boundary
(secrets masked, malformed configuration fails closed).
"""

import json
import uuid

import pytest

from arc.domain.models import WebhookEvent, WebhookEventStatus
from arc.services.webhook_config import (
    MIN_SECRET_LENGTH,
    WebhookConfigurationError,
    WebhookEndpointConfig,
    WebhookEndpointStore,
    parse_webhook_endpoints,
)


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"wh-{prefix}-{uuid.uuid4().hex[:10]}"


class TestWebhookEventDomain:
    def test_valid_event_is_accepted(self):
        event = WebhookEvent(
            id=_unique("event"),
            tenant_id=_unique("tenant"),
            endpoint_id="github-demo",
            event_id=_unique("sender-event"),
            event_type="issue.opened",
            payload_size_bytes=42,
        )
        assert event.status == WebhookEventStatus.RECEIVED

    def test_empty_id_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id="",
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="issue.opened",
            )

    def test_empty_tenant_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id="",
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="issue.opened",
            )

    def test_empty_event_id_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id="",
                event_type="issue.opened",
            )

    def test_oversized_event_id_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id="x" * 256,
                event_type="issue.opened",
            )

    def test_empty_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="",
            )

    def test_oversized_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="x" * 101,
            )

    def test_invalid_status_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="issue.opened",
                status="received",
            )

    def test_negative_payload_size_is_rejected(self):
        with pytest.raises(ValueError):
            WebhookEvent(
                id=_unique("event"),
                tenant_id=_unique("tenant"),
                endpoint_id="github-demo",
                event_id=_unique("sender-event"),
                event_type="issue.opened",
                payload_size_bytes=-1,
            )


class TestWebhookEndpointConfig:
    def test_secret_is_masked_in_repr_and_str(self):
        secret = "super-secret-webhook-value"
        config = WebhookEndpointConfig(
            endpoint_id="github-demo", tenant_id=_unique("tenant"), secret=secret
        )
        assert secret not in repr(config)
        assert secret not in str(config)
        assert "***" in repr(config)

    def test_minimum_secret_length_constant(self):
        """The documented minimum keeps brute-force space meaningful."""
        assert MIN_SECRET_LENGTH >= 16


class TestWebhookEndpointParsing:
    def test_empty_raw_parses_to_no_endpoints(self):
        assert parse_webhook_endpoints("") == {}

    def test_valid_configuration_parses(self):
        raw = json.dumps(
            {
                "github-demo": {"tenant_id": "tenant-1", "secret": "a-sufficient-secret"},
                "linear-demo": {"tenant_id": "tenant-2", "secret": "another-secret-value"},
            }
        )
        endpoints = parse_webhook_endpoints(raw)
        assert set(endpoints) == {"github-demo", "linear-demo"}
        assert endpoints["github-demo"].tenant_id == "tenant-1"

    def test_invalid_json_fails_closed(self):
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints("{not-json")

    def test_non_object_root_fails_closed(self):
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints(json.dumps(["not", "an", "object"]))

    def test_non_object_entry_fails_closed(self):
        raw = json.dumps({"github-demo": "not-an-object"})
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints(raw)

    def test_missing_tenant_binding_fails_closed(self):
        raw = json.dumps({"github-demo": {"secret": "a-sufficient-secret"}})
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints(raw)

    def test_short_secret_fails_closed(self):
        raw = json.dumps({"github-demo": {"tenant_id": "tenant-1", "secret": "short"}})
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints(raw)

    def test_missing_secret_fails_closed(self):
        raw = json.dumps({"github-demo": {"tenant_id": "tenant-1"}})
        with pytest.raises(WebhookConfigurationError):
            parse_webhook_endpoints(raw)

    def test_endpoint_store_resolves_from_environment(self, monkeypatch):
        monkeypatch.setenv(
            "WEBHOOK_INGESTION_ENDPOINTS",
            json.dumps({"github-demo": {"tenant_id": "tenant-1", "secret": "a-sufficient-secret"}}),
        )
        store = WebhookEndpointStore()
        config = store.get("github-demo")
        assert config is not None
        assert config.tenant_id == "tenant-1"
        assert store.get("unknown-endpoint") is None

    def test_endpoint_store_without_configuration_returns_none(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_INGESTION_ENDPOINTS", raising=False)
        assert WebhookEndpointStore().get("github-demo") is None
