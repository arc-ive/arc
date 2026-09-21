"""Webhooks foundation: ingestion service unit tests.

Exercises the ADR-001 webhook security boundary with in-memory fakes:
uniform authentication failures, timestamp window (replay resistance),
constant-time signature verification, payload validation, duplicate
handling, and the never-persist/never-leak payload contract.
"""

import json
import time
import uuid
from datetime import datetime, timezone

import pytest

from arc.domain.models import TenantContext, UserRole, WebhookEventStatus
from arc.services.webhook_config import (
    WebhookConfigurationError,
    WebhookEndpointConfig,
    WebhookEndpointStore,
)
from arc.services.webhook_ingestion import (
    MAX_BODY_BYTES,
    TIMESTAMP_TOLERANCE_SECONDS,
    WebhookAuthenticationError,
    WebhookIngestionError,
    WebhookIngestionService,
    WebhookValidationError,
    compute_signature,
)

SECRET = "unit-test-signing-secret-value"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"wi-{prefix}-{uuid.uuid4().hex[:10]}"


def _signed_headers(secret: str, body: bytes, timestamp: int | None = None):
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return {"timestamp": ts, "signature": compute_signature(secret, ts, body)}


class FakeRepository:
    """In-memory WebhookEventRepository double."""

    def __init__(self):
        self.events = []

    async def create(self, event):
        for existing in self.events:
            if existing.tenant_id == event.tenant_id and existing.event_id == event.event_id:
                from arc.db.connection import DuplicateKeyError

                raise DuplicateKeyError("duplicate")
        self.events.append(event)
        return event

    async def get_by_event_id(self, event_id, tenant_id):
        from arc.db.connection import NotFoundError

        for existing in self.events:
            if existing.tenant_id == tenant_id and existing.event_id == event_id:
                return existing
        raise NotFoundError("missing")

    async def list_for_tenant(self, tenant_id, limit=50):
        return [e for e in self.events if e.tenant_id == tenant_id][:limit]


def _make_service(tenant_id: str, endpoint_id: str = "github-demo"):
    config = WebhookEndpointConfig(endpoint_id=endpoint_id, tenant_id=tenant_id, secret=SECRET)
    store = WebhookEndpointStore(
        raw=json.dumps(
            {
                endpoint_id: {
                    "tenant_id": config.tenant_id,
                    "secret": config.secret,
                }
            }
        )
    )
    repository = FakeRepository()
    return WebhookIngestionService(endpoint_store=store, repository=repository), repository


def _valid_body(event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or _unique("sender-event"),
            "event_type": "issue.opened",
            "data": {"number": 1},
        }
    ).encode("utf-8")


@pytest.mark.asyncio
class TestWebhookIngestionHappyPath:
    async def test_valid_delivery_is_recorded_with_safe_metadata_only(self):
        tenant_id = _unique("tenant")
        service, repository = _make_service(tenant_id)
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        result = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )

        assert result.duplicate is False
        assert result.event.tenant_id == tenant_id
        assert result.event.endpoint_id == "github-demo"
        assert result.event.status == WebhookEventStatus.RECEIVED
        assert result.event.payload_size_bytes == len(body)
        assert len(repository.events) == 1

    async def test_payload_content_is_never_persisted(self):
        """The record must contain envelope metadata only: no raw payload."""
        tenant_id = _unique("tenant")
        service, repository = _make_service(tenant_id)
        body = json.dumps(
            {
                "event_id": _unique("sender-event"),
                "event_type": "issue.opened",
                "data": {"secret_field": "sensitive-payload-value"},
            }
        ).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        result = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )

        stored = str(repository.events)
        assert "sensitive-payload-value" not in stored
        assert result.event.payload_size_bytes == len(body)


class TestWebhookIngestionAuthentication:
    async def test_unknown_endpoint_is_uniformly_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest(
                "unknown-endpoint", headers["timestamp"], headers["signature"], body
            )

    async def test_missing_timestamp_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", "", compute_signature(SECRET, "", body), body)

    async def test_stale_timestamp_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()
        stale = int(time.time()) - TIMESTAMP_TOLERANCE_SECONDS - 10
        headers = _signed_headers(SECRET, body, timestamp=stale)

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_future_timestamp_beyond_window_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()
        future = int(time.time()) + TIMESTAMP_TOLERANCE_SECONDS + 10
        headers = _signed_headers(SECRET, body, timestamp=future)

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_non_numeric_timestamp_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", "not-a-number", "deadbeef", body)

    async def test_signature_mismatch_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()
        headers = _signed_headers("a-completely-different-secret", body)

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_tampered_body_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        original = _valid_body()
        headers = _signed_headers(SECRET, original)
        tampered = _valid_body()

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest(
                "github-demo", headers["timestamp"], headers["signature"], tampered
            )

    async def test_missing_signature_header_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookAuthenticationError):
            await service.ingest("github-demo", headers["timestamp"], "", body)

    async def test_authentication_errors_carry_no_reason_detail(self):
        """All auth failures must be indistinguishable to senders."""
        errors = []
        tenant_id = _unique("tenant")

        service, _ = _make_service(tenant_id)
        body = _valid_body()
        bad_sig = _signed_headers("wrong-secret-value-here", body)
        scenarios = [
            lambda: service.ingest(
                "unknown-endpoint", bad_sig["timestamp"], bad_sig["signature"], body
            ),
            lambda: service.ingest("github-demo", "garbage", "deadbeef", body),
            lambda: service.ingest("github-demo", bad_sig["timestamp"], "0" * 64, body),
        ]
        for scenario in scenarios:
            try:
                await scenario()
            except WebhookAuthenticationError as exc:
                errors.append(str(exc))
        assert len(errors) == 3
        assert all(error == errors[0] for error in errors)


class TestWebhookPayloadValidation:
    async def test_malformed_json_is_rejected_after_authentication(self):
        service, _ = _make_service(_unique("tenant"))
        body = b"{not-json"
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_non_object_json_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = json.dumps([1, 2, 3]).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_missing_event_id_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = json.dumps({"event_type": "issue.opened"}).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_missing_event_type_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = json.dumps({"event_id": _unique("sender-event")}).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_non_object_data_field_is_rejected(self):
        service, _ = _make_service(_unique("tenant"))
        body = json.dumps(
            {"event_id": _unique("sender-event"), "event_type": "t", "data": ["nope"]}
        ).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    async def test_oversized_body_is_rejected_before_persistence(self):
        service, repository = _make_service(_unique("tenant"))
        body = b"x" * (MAX_BODY_BYTES + 1)
        headers = _signed_headers(SECRET, body)

        with pytest.raises(WebhookValidationError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)
        assert repository.events == []


class TestWebhookDuplicateHandling:
    async def test_duplicate_delivery_resolves_to_original_record(self):
        tenant_id = _unique("tenant")
        service, _ = _make_service(tenant_id)
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        first = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )
        second = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )

        assert first.duplicate is False
        assert second.duplicate is True
        assert second.event.id == first.event.id


class TestWebhookListEvents:
    async def test_listing_is_scoped_to_the_trusted_tenant(self):
        tenant_a = _unique("tenant-a")
        tenant_b = _unique("tenant-b")
        service_a, _ = _make_service(tenant_a)
        service_b, _ = _make_service(tenant_b, endpoint_id="linear-demo")

        body = _valid_body()
        headers = _signed_headers(SECRET, body)
        await service_a.ingest("github-demo", headers["timestamp"], headers["signature"], body)

        context_b = TenantContext(
            tenant_id=tenant_b,
            tenant_name="B",
            user_id=_unique("user"),
            role=UserRole.MEMBER,
        )
        assert await service_b.list_events(context_b) == []

        context_a = TenantContext(
            tenant_id=tenant_a,
            tenant_name="A",
            user_id=_unique("user"),
            role=UserRole.MEMBER,
        )
        events = await service_a.list_events(context_a)
        assert len(events) == 1
        assert events[0].tenant_id == tenant_a


class TestWebhookSignatureScheme:
    def test_signature_is_deterministic_hex_digest(self):
        body = b"payload"
        first = compute_signature(SECRET, "123", body)
        second = compute_signature(SECRET, "123", body)
        assert first == second
        assert len(first) == 64

    def test_different_timestamp_changes_signature(self):
        body = b"payload"
        assert compute_signature(SECRET, "123", body) != compute_signature(SECRET, "124", body)

    def test_ingestion_error_hierarchy_is_controlled(self):
        assert issubclass(WebhookAuthenticationError, WebhookIngestionError)
        assert issubclass(WebhookValidationError, WebhookIngestionError)


class TestWebhookEventTypePiiSanitization:
    """V2-ADR-025: PII in webhook event_type must be sanitized before persistence."""

    def _make_service_with_pii_guard(self, tenant_id, pii_guard):
        config = WebhookEndpointConfig(
            endpoint_id="github-demo", tenant_id=tenant_id, secret=SECRET
        )
        store = WebhookEndpointStore(
            raw=json.dumps(
                {
                    "github-demo": {
                        "tenant_id": config.tenant_id,
                        "secret": config.secret,
                    }
                }
            )
        )
        repository = FakeRepository()
        return (
            WebhookIngestionService(
                endpoint_store=store, repository=repository, pii_guard=pii_guard
            ),
            repository,
        )

    async def test_clean_event_type_unchanged(self):
        tenant_id = _unique("tenant")
        service, repository = self._make_service_with_pii_guard(tenant_id, None)
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        result = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )

        assert result.event.event_type == "issue.opened"

    async def test_pii_in_event_type_sanitized_before_persistence(self):
        from unittest.mock import MagicMock

        pii_guard = MagicMock()
        pii_guard.sanitize = MagicMock(return_value=MagicMock(sanitized_text="<EMAIL_ADDRESS>"))
        tenant_id = _unique("tenant")
        service, repository = self._make_service_with_pii_guard(tenant_id, pii_guard)
        body = json.dumps(
            {
                "event_id": _unique("evt"),
                "event_type": "john@example.com.notification",
                "data": {},
            }
        ).encode("utf-8")
        headers = _signed_headers(SECRET, body)

        result = await service.ingest(
            "github-demo", headers["timestamp"], headers["signature"], body
        )

        assert result.event.event_type == "<EMAIL_ADDRESS>"
        pii_guard.sanitize.assert_called_once_with("john@example.com.notification")

    async def test_pii_guard_failure_propagates(self):
        from unittest.mock import MagicMock

        from arc.services.pii import PiiGuardError

        def _explode(text):
            raise PiiGuardError("analysis failed")

        pii_guard = MagicMock()
        pii_guard.sanitize = _explode
        tenant_id = _unique("tenant")
        service, _ = self._make_service_with_pii_guard(tenant_id, pii_guard)
        body = _valid_body()
        headers = _signed_headers(SECRET, body)

        with pytest.raises(PiiGuardError):
            await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)


class TestWebhookTimestampTolerance:
    """Issue #184: the replay window defaults to 120s and is env-configurable.

    A fixed clock is injected so boundary assertions are deterministic:
    ``abs(now - delivered) == tolerance`` is accepted, ``tolerance + 1``
    is rejected.
    """

    NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def _make_service_at(self, tenant_id, **kwargs):
        config = WebhookEndpointConfig(
            endpoint_id="github-demo", tenant_id=tenant_id, secret=SECRET
        )
        store = WebhookEndpointStore(
            raw=json.dumps(
                {
                    "github-demo": {
                        "tenant_id": config.tenant_id,
                        "secret": config.secret,
                    }
                }
            )
        )
        return WebhookIngestionService(
            endpoint_store=store,
            repository=FakeRepository(),
            now=lambda: self.NOW,
            **kwargs,
        )

    async def _ingest_at_offset(self, service, offset_seconds):
        body = _valid_body()
        delivered = int(self.NOW.timestamp()) + offset_seconds
        headers = _signed_headers(SECRET, body, timestamp=delivered)
        return await service.ingest("github-demo", headers["timestamp"], headers["signature"], body)

    def test_default_tolerance_is_120_seconds(self):
        assert TIMESTAMP_TOLERANCE_SECONDS == 120

    async def test_timestamp_within_default_tolerance_is_accepted(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", raising=False)
        service = self._make_service_at(_unique("tenant"))
        result = await self._ingest_at_offset(service, -60)
        assert result.duplicate is False

    async def test_timestamp_outside_default_tolerance_is_rejected(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", raising=False)
        service = self._make_service_at(_unique("tenant"))
        with pytest.raises(WebhookAuthenticationError):
            await self._ingest_at_offset(service, -(TIMESTAMP_TOLERANCE_SECONDS + 1))

    @pytest.mark.parametrize("offset", [-120, 120])
    async def test_boundary_exactly_at_tolerance_is_accepted(self, monkeypatch, offset):
        monkeypatch.delenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", raising=False)
        service = self._make_service_at(_unique("tenant"))
        result = await self._ingest_at_offset(service, offset)
        assert result.duplicate is False

    @pytest.mark.parametrize("offset", [-121, 121])
    async def test_boundary_just_outside_tolerance_is_rejected(self, monkeypatch, offset):
        monkeypatch.delenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", raising=False)
        service = self._make_service_at(_unique("tenant"))
        with pytest.raises(WebhookAuthenticationError):
            await self._ingest_at_offset(service, offset)

    async def test_environment_variable_widens_the_window(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "300")
        service = self._make_service_at(_unique("tenant"))
        result = await self._ingest_at_offset(service, -200)
        assert result.duplicate is False

    async def test_environment_variable_narrows_the_window(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "10")
        service = self._make_service_at(_unique("tenant"))
        with pytest.raises(WebhookAuthenticationError):
            await self._ingest_at_offset(service, -60)

    async def test_explicit_argument_wins_over_environment(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "10")
        service = self._make_service_at(_unique("tenant"), timestamp_tolerance_seconds=300)
        result = await self._ingest_at_offset(service, -200)
        assert result.duplicate is False

    @pytest.mark.parametrize("value", ["abc", "3.5", "ten"])
    def test_non_integer_tolerance_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", value)
        with pytest.raises(WebhookConfigurationError, match="WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS"):
            self._make_service_at(_unique("tenant"))

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_non_positive_tolerance_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", value)
        with pytest.raises(WebhookConfigurationError, match="WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS"):
            self._make_service_at(_unique("tenant"))

    async def test_empty_tolerance_falls_back_to_default(self, monkeypatch):
        """An unset variable in a .env file arrives as an empty string."""
        monkeypatch.setenv("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "")
        service = self._make_service_at(_unique("tenant"))
        result = await self._ingest_at_offset(service, -60)
        assert result.duplicate is False
        with pytest.raises(WebhookAuthenticationError):
            await self._ingest_at_offset(service, -(TIMESTAMP_TOLERANCE_SECONDS + 1))
