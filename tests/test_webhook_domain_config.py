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
    validate_webhook_endpoints,
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


class TestWebhookActionConfigParsing:
    """Tests for the action configuration parsing (Issue #221)."""

    def test_ingestion_only_configuration_parses(self):
        """Endpoints without action are valid ingestion-only endpoints."""
        raw = json.dumps(
            {
                "github-demo": {"tenant_id": "tenant-1", "secret": "a-sufficient-secret"},
            }
        )
        endpoints = parse_webhook_endpoints(raw)
        assert endpoints["github-demo"].action is None

    def test_processing_configuration_parses_with_action(self):
        """Endpoints with action block parse correctly."""
        raw = json.dumps(
            {
                "github-issues": {
                    "tenant_id": "tenant-acme",
                    "secret": "github-webhook-signing-secret-min-16-chars",
                    "action": {
                        "type": "skill",
                        "skill_id": "github-issue-processor",
                        "tool_calls": [
                            {
                                "tool_name": "create_task",
                                "input": {"title": "Issue from webhook", "project": "acme"},
                            }
                        ],
                        "satisfied_conditions": ["user_authenticated"],
                    },
                }
            }
        )
        endpoints = parse_webhook_endpoints(raw)
        config = endpoints["github-issues"]
        assert config.action is not None
        assert config.action.type == "skill"
        assert config.action.skill_id == "github-issue-processor"
        assert len(config.action.tool_calls) == 1
        assert config.action.tool_calls[0]["tool_name"] == "create_task"
        assert config.action.tool_calls[0]["input"]["title"] == "Issue from webhook"
        assert config.action.satisfied_conditions == ["user_authenticated"]

    def test_action_type_must_be_skill(self):
        """Only 'skill' action type is supported in V1."""
        raw = json.dumps(
            {
                "bad-endpoint": {
                    "tenant_id": "tenant-1",
                    "secret": "a-sufficient-secret",
                    "action": {
                        "type": "invalid",
                        "skill_id": "s1",
                        "tool_calls": [{"tool_name": "t1", "input": {}}],
                    },
                }
            }
        )
        with pytest.raises(WebhookConfigurationError, match="not supported"):
            parse_webhook_endpoints(raw)

    def test_action_requires_skill_id(self):
        """Action must define a non-empty skill_id."""
        raw = json.dumps(
            {
                "bad-endpoint": {
                    "tenant_id": "tenant-1",
                    "secret": "a-sufficient-secret",
                    "action": {"type": "skill", "tool_calls": [{"tool_name": "t1", "input": {}}]},
                }
            }
        )
        with pytest.raises(WebhookConfigurationError, match="skill_id"):
            parse_webhook_endpoints(raw)

    def test_action_requires_non_empty_tool_calls(self):
        """Action must define a non-empty tool_calls list."""
        raw = json.dumps(
            {
                "bad-endpoint": {
                    "tenant_id": "tenant-1",
                    "secret": "a-sufficient-secret",
                    "action": {"type": "skill", "skill_id": "s1", "tool_calls": []},
                }
            }
        )
        with pytest.raises(WebhookConfigurationError, match="tool_calls"):
            parse_webhook_endpoints(raw)

    def test_tool_call_requires_tool_name(self):
        """Each tool_call must define a non-empty tool_name."""
        raw = json.dumps(
            {
                "bad-endpoint": {
                    "tenant_id": "tenant-1",
                    "secret": "a-sufficient-secret",
                    "action": {
                        "type": "skill",
                        "skill_id": "s1",
                        "tool_calls": [{"input": {}}],
                    },
                }
            }
        )
        with pytest.raises(WebhookConfigurationError, match="tool_name"):
            parse_webhook_endpoints(raw)

    def test_tool_call_requires_input_object(self):
        """Each tool_call input must be a JSON object."""
        raw = json.dumps(
            {
                "bad-endpoint": {
                    "tenant_id": "tenant-1",
                    "secret": "a-sufficient-secret",
                    "action": {
                        "type": "skill",
                        "skill_id": "s1",
                        "tool_calls": [{"tool_name": "t1", "input": "not-an-object"}],
                    },
                }
            }
        )
        with pytest.raises(WebhookConfigurationError, match="input must be a JSON object"):
            parse_webhook_endpoints(raw)

    def test_satisfied_conditions_optional(self):
        """satisfied_conditions is optional and defaults to empty list."""
        raw = json.dumps(
            {
                "github-issues": {
                    "tenant_id": "tenant-acme",
                    "secret": "github-webhook-signing-secret-min-16-chars",
                    "action": {
                        "type": "skill",
                        "skill_id": "github-issue-processor",
                        "tool_calls": [{"tool_name": "create_task", "input": {}}],
                    },
                }
            }
        )
        endpoints = parse_webhook_endpoints(raw)
        assert endpoints["github-issues"].action.satisfied_conditions == []


class TestValidateWebhookEndpoints:
    """Tests for startup configuration validation (Issue #221)."""

    def test_validate_warns_for_ingestion_only(self, caplog):
        """Validation logs warning for endpoints without action."""
        import logging

        caplog.set_level(logging.WARNING)

        raw = json.dumps(
            {
                "github-demo": {"tenant_id": "tenant-1", "secret": "a-sufficient-secret"},
            }
        )
        endpoints = validate_webhook_endpoints(raw)

        assert "github-demo" in endpoints
        assert endpoints["github-demo"].action is None
        assert any("has no action configured" in record.message for record in caplog.records)
        assert any("NOT processed downstream" in record.message for record in caplog.records)

    def test_validate_logs_info_for_processing_endpoint(self, caplog):
        """Validation logs info for endpoints with action."""
        import logging

        caplog.set_level(logging.INFO)

        raw = json.dumps(
            {
                "github-issues": {
                    "tenant_id": "tenant-acme",
                    "secret": "github-webhook-signing-secret-min-16-chars",
                    "action": {
                        "type": "skill",
                        "skill_id": "github-issue-processor",
                        "tool_calls": [{"tool_name": "create_task", "input": {}}],
                    },
                }
            }
        )
        endpoints = validate_webhook_endpoints(raw)

        assert "github-issues" in endpoints
        assert endpoints["github-issues"].action is not None
        assert any("configured with" in record.message for record in caplog.records)
        assert any("github-issue-processor" in record.message for record in caplog.records)

    def test_validate_mixed_endpoints(self, caplog):
        """Validation handles mix of ingestion-only and processing endpoints."""
        import logging

        caplog.set_level(logging.INFO)

        raw = json.dumps(
            {
                "ingestion-only": {"tenant_id": "tenant-1", "secret": "a-sufficient-secret"},
                "processing": {
                    "tenant_id": "tenant-2",
                    "secret": "another-sufficient-secret",
                    "action": {
                        "type": "skill",
                        "skill_id": "skill-1",
                        "tool_calls": [{"tool_name": "noop", "input": {}}],
                    },
                },
            }
        )
        endpoints = validate_webhook_endpoints(raw)

        assert len(endpoints) == 2
        assert endpoints["ingestion-only"].action is None
        assert endpoints["processing"].action is not None

        # Should have both warning and info
        messages = [record.message for record in caplog.records]
        assert any("has no action configured" in m for m in messages)
        assert any("configured with" in m for m in messages)
