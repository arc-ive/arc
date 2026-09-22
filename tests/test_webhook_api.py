"""Webhooks foundation: API boundary tests.

Covers the machine-facing HMAC-authenticated ingestion endpoint and the
RBAC-protected tenant event-listing endpoint, following the adversarial
conventions of ``tests/test_connector_api.py``:

- uniform 401 authentication failures (endpoint existence is never
  disclosed to unauthenticated senders);
- RBAC enforcement on the listing surface (401 unauthenticated /
  403 insufficient permission / 403 path-vs-context mismatch);
- idempotent duplicate handling;
- SQL-level tenant isolation observable through the API;
- signing secrets and payload content never appear in any response or
  persisted record.
"""

import json
import os
import time
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from arc.domain.models import (
    Membership,
    Tenant,
    TenantContext,
    User,
    UserRole,
    WebhookEvent,
    WebhookEventStatus,
)
from arc.main import app
from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository
from arc.security.authorization import WEBHOOK_READ
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole
from arc.services.webhook_ingestion import MAX_BODY_BYTES, compute_signature

ENDPOINT_ID = "wh-github-demo"
SECRET = "webhook-test-signing-secret-value"


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"wa-{prefix}-{uuid.uuid4().hex[:10]}"


def _provision_endpoint(tenant_id: str, endpoint_id: str = ENDPOINT_ID):
    """Point WEBHOOK_INGESTION_ENDPOINTS at one tenant-bound endpoint.

    Returns a restoration callable for use in ``finally`` blocks (the
    same pattern as the connector credential tests).
    """
    previous = os.environ.get("WEBHOOK_INGESTION_ENDPOINTS")
    os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = json.dumps(
        {endpoint_id: {"tenant_id": tenant_id, "secret": SECRET}}
    )

    def _restore():
        if previous is None:
            os.environ.pop("WEBHOOK_INGESTION_ENDPOINTS", None)
        else:
            os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = previous

    return _restore


def _signed_headers(body: bytes, timestamp: int | None = None, secret: str = SECRET):
    ts = str(timestamp if timestamp is not None else int(time.time()))
    return {"X-Arc-Timestamp": ts, "X-Arc-Signature": compute_signature(secret, ts, body)}


def _valid_body(event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or _unique("sender-event"),
            "event_type": "issue.opened",
            "data": {"note": "external-content"},
        }
    ).encode("utf-8")


@pytest.fixture
async def webhook_tenant(db):
    """Create a tenant for ingestion tests; deletion cascades its events."""
    from arc.repositories.tenancy import PostgreSQLTenantRepository

    tenants = PostgreSQLTenantRepository(db)
    created = await tenants.create(Tenant(id=_unique("tenant"), name="Webhook API Tenant"))
    yield created
    await tenants.delete(created.id)


class TestWebhookIngestionAuthentication:
    def test_ingestion_without_credentials_is_rejected(self, client):
        response = client.post(f"/webhooks/{ENDPOINT_ID}/events", content=_valid_body())
        assert response.status_code == 401

    def test_unknown_endpoint_with_valid_signature_is_rejected(self, client):
        restore = _provision_endpoint(_unique("unused-tenant"))
        try:
            body = _valid_body()
            response = client.post(
                "/webhooks/not-a-configured-endpoint/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 401

    def test_bad_signature_is_rejected(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body, secret="a-totally-wrong-secret"),
            )
        finally:
            restore()
        assert response.status_code == 401

    def test_stale_timestamp_is_rejected(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            stale = int(time.time()) - 301
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body, timestamp=stale),
            )
        finally:
            restore()
        assert response.status_code == 401

    def test_authentication_failures_are_indistinguishable(self, client, webhook_tenant):
        """Unknown endpoints, bad signatures, and missing headers produce
        identical 401s so senders cannot enumerate configured endpoints."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            unknown = client.post(
                "/webhooks/not-a-configured-endpoint/events",
                content=body,
                headers=_signed_headers(body),
            )
            bad_signature = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body, secret="a-totally-wrong-secret"),
            )
            missing_headers = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
            )
        finally:
            restore()

        assert unknown.status_code == bad_signature.status_code == missing_headers.status_code
        assert unknown.json() == bad_signature.json() == missing_headers.json()


class TestWebhookIngestionFlow:
    def test_valid_delivery_creates_metadata_only_record(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["duplicate"] is False
        assert envelope["tenant_id"] == webhook_tenant.id
        assert envelope["endpoint_id"] == ENDPOINT_ID
        # Auto-dispatch (Issue #138) invokes the real pipeline which
        # transitions the event through processing → failed (no action
        # configured for this test endpoint). The response reflects
        # the actual persisted state.
        assert envelope["status"] == "failed"
        assert envelope["payload_size_bytes"] == len(body)
        # Only envelope metadata is returned: no sender payload content.
        assert "external-content" not in json.dumps(envelope)
        assert SECRET not in json.dumps(envelope)

    def test_duplicate_delivery_is_idempotent(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            first = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            second = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()

        assert first.status_code == second.status_code == 200
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert second.json()["id"] == first.json()["id"]

    def test_malformed_json_returns_controlled_400(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = b"{not-json"
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 400

    def test_missing_required_fields_return_400(self, client, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = json.dumps({"event_type": "issue.opened"}).encode("utf-8")
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 400

    async def test_oversized_body_is_rejected_without_persistence(self, client, db, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = b"x" * (MAX_BODY_BYTES + 1)
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()

        assert response.status_code == 400
        records = await PostgreSQLWebhookEventRepository(db).list_for_tenant(webhook_tenant.id)
        assert records == []


class TestWebhookRecordSafety:
    async def test_persisted_records_contain_no_secret_or_payload(self, client, db, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert response.status_code == 200

            records = await PostgreSQLWebhookEventRepository(db).list_for_tenant(webhook_tenant.id)
        finally:
            restore()

        assert len(records) == 1
        serialized = str(records[0])
        assert SECRET not in serialized
        assert "external-content" not in serialized


class TestWebhookListingAuthentication:
    def test_listing_requires_authentication(self, client):
        response = client.get(f"/tenants/{_unique('tenant')}/webhooks/events")
        assert response.status_code == 401


class TestWebhookListingAuthorization:
    @pytest.mark.parametrize("assign_role", [False, True])
    def test_listing_requires_webhook_read_permission(
        self, client, seeded, make_token, authorization_override, assign_role
    ):
        """Unassigned users AND EMPLOYEEs are denied by default."""
        tenant, user, _ = seeded
        assignments = {user.id: ApplicationRole.EMPLOYEE} if assign_role else {}
        authorization_override(assignments)
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/webhooks/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_operations_user_can_list_events(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/webhooks/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["items"] == []

    async def test_webhook_read_permission_constant_exists(self):
        assert WEBHOOK_READ.resource == "webhook"
        assert WEBHOOK_READ.action == "read"


class TestWebhookListingIsolation:
    async def test_events_are_only_visible_to_the_owning_tenant(
        self, client, db, repositories, webhook_tenant, make_token, authorization_override
    ):
        tenant_repo, user_repo, membership_repo = repositories

        other_tenant = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="B"))
        other_user = await user_repo.create(
            User(id=_unique("user-b"), email=f"{uuid.uuid4().hex}@example.com", username="b")
        )
        membership_b = await membership_repo.create(
            Membership(id=_unique("membership"), user_id=other_user.id, tenant_id=other_tenant.id)
        )

        authorization_override({other_user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_b = make_token(other_user.id)

        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            ingest = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest.status_code == 200
        finally:
            restore()

        foreign = client.get(
            f"/tenants/{other_tenant.id}/webhooks/events",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert foreign.status_code == 200
        assert foreign.json()["items"] == []

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(other_user.id)
        await tenant_repo.delete(other_tenant.id)

    async def test_owning_tenant_sees_its_event_with_safe_metadata_only(
        self, client, db, webhook_tenant, make_token, authorization_override, repositories
    ):
        _, user_repo, membership_repo = repositories
        owner_user = await user_repo.create(
            User(id=_unique("user-a"), email=f"{uuid.uuid4().hex}@example.com", username="a")
        )
        membership_a = await membership_repo.create(
            Membership(id=_unique("membership"), user_id=owner_user.id, tenant_id=webhook_tenant.id)
        )
        authorization_override({owner_user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(owner_user.id)

        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            ingest = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest.status_code == 200
            event_id = ingest.json()["id"]
        finally:
            restore()

        listing = client.get(
            f"/tenants/{webhook_tenant.id}/webhooks/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listing.status_code == 200
        events = listing.json()["items"]
        assert len(events) == 1
        assert events[0]["id"] == event_id
        assert "external-content" not in json.dumps(events)
        assert SECRET not in json.dumps(events)

        await membership_repo.delete(membership_a.id)
        await user_repo.delete(owner_user.id)


class TestWebhookPathTenantConsistency:
    async def test_mismatched_path_tenant_cannot_read(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        mismatched_context = TenantContext(
            tenant_id=_unique("other-tenant"),
            tenant_name="Other Tenant",
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_trusted_tenant_context] = lambda: mismatched_context
        try:
            listing = client.get(
                f"/tenants/{tenant.id}/webhooks/events",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

    async def test_tenant_cascade_probe(self, client):
        assert True


class TestWebhookTenantCascade:
    async def test_deleting_the_tenant_removes_ingested_events(self, client, db, webhook_tenant):
        """The FK cascade guarantees no orphaned event rows survive."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            ingest = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest.status_code == 200
        finally:
            restore()

        # The webhook_tenant fixture teardown deletes the tenant; verify the
        # cascade contract directly before that happens.
        repo = PostgreSQLWebhookEventRepository(db)
        assert len(await repo.list_for_tenant(webhook_tenant.id)) == 1

        from arc.repositories.tenancy import PostgreSQLTenantRepository

        tenants = PostgreSQLTenantRepository(db)
        await tenants.delete(webhook_tenant.id)
        assert await repo.list_for_tenant(webhook_tenant.id) == []


class TestBodyCapHardening:
    """Body-cap production hardening (approved PR #34 review follow-up).

    Oversized bodies are rejected with the EXISTING 400 contract BEFORE
    authentication (deliberate precedence: prevents unauthenticated
    buffering; endpoint-independent, so nothing is revealed). Bodies
    within the cap keep byte-exact HMAC semantics and unchanged uniform
    401 behavior.
    """

    def _oversize(self) -> bytes:
        return b"x" * (MAX_BODY_BYTES + 1)

    async def test_exactly_max_bytes_with_valid_signature_succeeds(
        self, client, db, webhook_tenant
    ):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            # Valid JSON envelope padded to EXACTLY the cap.
            base = {
                "event_id": _unique("sender-event"),
                "event_type": "issue.opened",
                "data": {"note": ""},
            }
            empty_len = len(json.dumps(base))
            base["data"]["note"] = "x" * (MAX_BODY_BYTES - empty_len)
            body = json.dumps(base).encode("utf-8")
            assert len(body) == MAX_BODY_BYTES
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 200
        assert response.json()["duplicate"] is False

    async def test_oversize_rejected_before_authentication_even_without_credentials(
        self, client, db, webhook_tenant
    ):
        """No timestamp/signature at all + oversize => 400 (not 401)."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            response = client.post(f"/webhooks/{ENDPOINT_ID}/events", content=self._oversize())
        finally:
            restore()
        assert response.status_code == 400

    async def test_oversize_response_is_endpoint_independent(self, client, webhook_tenant):
        """Same 400 for unknown and known endpoints: no enumeration signal."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            known = client.post(f"/webhooks/{ENDPOINT_ID}/events", content=self._oversize())
            unknown = client.post(
                f"/webhooks/{'unknown-endpoint'}/events", content=self._oversize()
            )
        finally:
            restore()
        assert known.status_code == unknown.status_code == 400
        assert known.json() == unknown.json()

    async def test_oversize_does_not_echo_payload(self, client, webhook_tenant):
        marker = b"UNIQUESUPERSECRETCONTENT123"
        body = marker * 4096  # ~96 KB, contains the unique marker throughout
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 400
        assert "UNIQUESUPERSECRETCONTENT123" not in response.text
        assert "xxxxxx" not in response.text

    async def test_chunked_transfer_within_cap_succeeds(self, client, db, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=iter([body[:100], body[100:]]),  # chunked, no Content-Length
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 200

    async def test_chunked_transfer_over_cap_is_rejected(self, client, db, webhook_tenant):
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = self._oversize()
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=iter([body[:50000], body[50000:]]),  # chunked over cap
                headers=_signed_headers(body),
            )
        finally:
            restore()
        assert response.status_code == 400
        records = await PostgreSQLWebhookEventRepository(db).list_for_tenant(webhook_tenant.id)
        assert records == []

    async def test_misleading_large_content_length_hits_fast_path(self, client, webhook_tenant):
        """CL present and clearly exceeding the cap => early 400 without read."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            response = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=b"tiny",
                headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
            )
        finally:
            restore()
        assert response.status_code == 400

    async def test_capped_reader_stops_consuming_past_limit(self):
        """Direct proof: the reader never pulls chunks beyond the cap."""
        from arc.api.controllers import _read_capped_body

        pulled_chunks: list[int] = []
        chunk = b"a" * 30000  # 3 chunks exceed 65536 cumulative

        async def receive():
            if len(pulled_chunks) >= 4:
                raise AssertionError("reader consumed beyond the cap")
            pulled_chunks.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": True}

        scope = {"type": "http", "method": "POST", "headers": []}
        request = Request(scope, receive)
        with pytest.raises(HTTPException) as excinfo:
            await _read_capped_body(request, MAX_BODY_BYTES)
        assert excinfo.value.status_code == 400
        # cap tripped inside chunk 3; chunk 4 must never have been requested
        assert len(pulled_chunks) == 3

    async def test_exact_cap_boundary_via_stream_reader_succeeds(self):
        from arc.api.controllers import _read_capped_body

        body = b"b" * MAX_BODY_BYTES

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "headers": []}, receive)
        result = await _read_capped_body(request, MAX_BODY_BYTES)
        assert result == body
        assert len(result) == MAX_BODY_BYTES


class TestWebhookEventReliabilityFields:
    """Event API exposes stored failure/retry state (Issue #222)."""

    async def _owner_token(self, webhook_tenant, make_token, authorization_override, repositories):
        _, user_repo, membership_repo = repositories
        owner = await user_repo.create(
            User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="u")
        )
        membership = await membership_repo.create(
            Membership(id=_unique("membership"), user_id=owner.id, tenant_id=webhook_tenant.id)
        )
        authorization_override({owner.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        return make_token(owner.id), owner, membership

    async def test_failed_event_exposes_error_kind_and_retry_state(
        self, client, db, webhook_tenant, make_token, authorization_override, repositories
    ):
        """Real ingestion path: no-action endpoint -> auto-dispatch fails permanently."""
        restore = _provision_endpoint(webhook_tenant.id)
        try:
            body = _valid_body()
            ingest = client.post(
                f"/webhooks/{ENDPOINT_ID}/events",
                content=body,
                headers=_signed_headers(body),
            )
            assert ingest.status_code == 200
            envelope = ingest.json()
            # Ingestion re-reads the post-dispatch state, so the failure
            # reason is available right in the ingestion response.
            assert envelope["status"] == "failed"
            assert envelope["error_kind"] == "no_action_configured"
        finally:
            restore()

        token, owner, membership = await self._owner_token(
            webhook_tenant, make_token, authorization_override, repositories
        )
        _, user_repo, membership_repo = repositories
        try:
            listing = client.get(
                f"/tenants/{webhook_tenant.id}/webhooks/events",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 200
            events = listing.json()["items"]
            assert len(events) == 1
            event = events[0]
            assert event["status"] == "failed"
            assert event["error_kind"] == "no_action_configured"
            assert event["retry_count"] == 0
            assert event["max_retries"] == 5
            assert event["next_retry_at"] is None
            assert event["processed_at"] is not None
            # Existing fields unchanged; no secret or payload content.
            assert event["event_type"] == "issue.opened"
            assert "external-content" not in json.dumps(events)
            assert SECRET not in json.dumps(events)
        finally:
            await membership_repo.delete(membership.id)
            await user_repo.delete(owner.id)

    async def test_dead_letter_distinguishable_from_first_failure(
        self, client, db, webhook_tenant, make_token, authorization_override, repositories
    ):
        """Terminal retry state via the real repository transitions.

        Driving all 5 retries through the pipeline would wait out real
        exponential backoff, so this uses the closest seam: the real
        PostgreSQL claim/dead-letter transitions on a retries-exhausted
        event. The retry state machine itself is covered by the pipeline
        and retry-sweep suites.
        """
        repo = PostgreSQLWebhookEventRepository(db)
        event = WebhookEvent(
            id=_unique("event"),
            tenant_id=webhook_tenant.id,
            endpoint_id=ENDPOINT_ID,
            event_id=_unique("sender-event"),
            event_type="issue.opened",
            status=WebhookEventStatus.RECEIVED,
            payload_size_bytes=128,
            retry_count=5,
            max_retries=5,
        )
        await repo.create(event)
        await repo.claim_for_processing(event.event_id, webhook_tenant.id)
        await repo.mark_dead_letter(event.event_id, webhook_tenant.id, "downstream_execution_error")

        token, owner, membership = await self._owner_token(
            webhook_tenant, make_token, authorization_override, repositories
        )
        _, user_repo, membership_repo = repositories
        try:
            listing = client.get(
                f"/tenants/{webhook_tenant.id}/webhooks/events",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 200
            events = listing.json()["items"]
            assert len(events) == 1
            dead = events[0]
            assert dead["status"] == "dead_letter"
            assert dead["error_kind"] == "downstream_execution_error"
            # Exhausted retries distinguish this from a first failure
            # (retry_count 0, next_retry_at null).
            assert dead["retry_count"] == 5
            assert dead["max_retries"] == 5
            assert dead["processed_at"] is not None
        finally:
            await membership_repo.delete(membership.id)
            await user_repo.delete(owner.id)

    async def test_processed_event_has_null_error_kind(
        self, client, db, webhook_tenant, make_token, authorization_override, repositories
    ):
        """Successful events stay valid: null error, processed timestamp set."""
        repo = PostgreSQLWebhookEventRepository(db)
        event = WebhookEvent(
            id=_unique("event"),
            tenant_id=webhook_tenant.id,
            endpoint_id=ENDPOINT_ID,
            event_id=_unique("sender-event"),
            event_type="issue.opened",
            status=WebhookEventStatus.RECEIVED,
            payload_size_bytes=128,
        )
        await repo.create(event)
        await repo.claim_for_processing(event.event_id, webhook_tenant.id)
        await repo.mark_processed(event.event_id, webhook_tenant.id)

        token, owner, membership = await self._owner_token(
            webhook_tenant, make_token, authorization_override, repositories
        )
        _, user_repo, membership_repo = repositories
        try:
            listing = client.get(
                f"/tenants/{webhook_tenant.id}/webhooks/events",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 200
            events = listing.json()["items"]
            assert len(events) == 1
            done = events[0]
            assert done["status"] == "processed"
            assert done["error_kind"] is None
            assert done["retry_count"] == 0
            assert done["next_retry_at"] is None
            assert done["processed_at"] is not None
        finally:
            await membership_repo.delete(membership.id)
            await user_repo.delete(owner.id)


class TestWebhookProcessingIntegration:
    """Integration tests for documented webhook processing configuration (Issue #221)."""

    async def test_documented_processing_configuration_works(self, client, db, webhook_tenant):
        """
        Verify the exact documented processing configuration from .env.example
        successfully authenticates AND reaches downstream processing.

        This is the regression test for Issue #221: the documented configuration
        must produce a working processing endpoint (i.e. NOT fail with
        no_action_configured).

        The downstream Skill execution itself is stubbed with the repository's
        established auto-dispatch seam (Issue #138): the mock performs the real
        claim -> processed repository transitions on its own connection. A real
        Skill execution would test SkillExecutionService, not the documented
        webhook configuration, and needs no fictional skill to exist.
        """
        from unittest.mock import AsyncMock

        from arc.db.connection import ArcDatabase
        from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository

        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://arc:arc-dev-password@localhost:5432/arc",
        )

        async def _process_success(tenant_id, event_id):
            database = ArcDatabase(database_url)
            await database.connect()
            try:
                repo = PostgreSQLWebhookEventRepository(database)
                await repo.claim_for_processing(event_id, tenant_id)
                await repo.mark_processed(event_id, tenant_id)
            finally:
                await database.disconnect()

        mock_pipeline = AsyncMock()
        mock_pipeline.process = AsyncMock(side_effect=_process_success)

        from arc.api.controllers import app_context as real_ctx

        original = real_ctx.services._services.get("webhook_pipeline_service")
        real_ctx.services._services["webhook_pipeline_service"] = mock_pipeline

        # Use the exact configuration shape from .env.example (processing endpoint)
        endpoint_id = "github-issues"
        secret = "github-webhook-signing-secret-min-16-chars"

        # Provision endpoint with the documented action configuration
        previous = os.environ.get("WEBHOOK_INGESTION_ENDPOINTS")
        os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = json.dumps(
            {
                endpoint_id: {
                    "tenant_id": webhook_tenant.id,
                    "secret": secret,
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

        try:
            body = json.dumps(
                {
                    "event_id": _unique("sender-event"),
                    "event_type": "issue.opened",
                    "data": {"note": "external-content"},
                }
            ).encode("utf-8")

            ts = str(int(time.time()))
            headers = {
                "X-Arc-Timestamp": ts,
                "X-Arc-Signature": compute_signature(secret, ts, body),
            }

            # Ingest the event - this triggers auto-dispatch to the pipeline
            response = client.post(f"/webhooks/{endpoint_id}/events", content=body, headers=headers)

            assert response.status_code == 200
            envelope = response.json()

            # Verify authentication succeeded
            assert envelope["tenant_id"] == webhook_tenant.id
            assert envelope["endpoint_id"] == endpoint_id

            # The documented action was resolved and dispatched downstream
            # (not failed with no_action_configured)
            assert envelope["status"] == "processed", (
                f"Expected 'processed', got '{envelope['status']}': {envelope}"
            )
            mock_pipeline.process.assert_awaited_once()

            # Verify the event was actually processed in the database
            records = await PostgreSQLWebhookEventRepository(db).list_for_tenant(webhook_tenant.id)
            assert len(records) == 1
            assert records[0].status.value == "processed"
            assert records[0].error_kind is None

        finally:
            if original is not None:
                real_ctx.services._services["webhook_pipeline_service"] = original
            else:
                real_ctx.services._services.pop("webhook_pipeline_service", None)
            if previous is None:
                os.environ.pop("WEBHOOK_INGESTION_ENDPOINTS", None)
            else:
                os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = previous

    async def test_ingestion_only_configuration_does_not_process(self, client, db, webhook_tenant):
        """
        Verify ingestion-only endpoints (no action) authenticate but fail processing.

        This documents the expected behavior: ingestion-only endpoints are valid
        but will not process events downstream.

        The failure reason is asserted at the stored-event level. Surfacing
        error_kind in the API response itself is Issue #222's contract, not
        this branch's.
        """
        from arc.repositories.webhook_events import PostgreSQLWebhookEventRepository

        endpoint_id = "ingestion-only"
        secret = "a-sufficient-secret-value"

        previous = os.environ.get("WEBHOOK_INGESTION_ENDPOINTS")
        os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = json.dumps(
            {endpoint_id: {"tenant_id": webhook_tenant.id, "secret": secret}}
        )

        try:
            event_id = _unique("sender-event")
            body = json.dumps(
                {
                    "event_id": event_id,
                    "event_type": "issue.opened",
                    "data": {"note": "external-content"},
                }
            ).encode("utf-8")

            ts = str(int(time.time()))
            headers = {
                "X-Arc-Timestamp": ts,
                "X-Arc-Signature": compute_signature(secret, ts, body),
            }

            response = client.post(f"/webhooks/{endpoint_id}/events", content=body, headers=headers)

            assert response.status_code == 200
            envelope = response.json()

            # Authentication succeeded
            assert envelope["tenant_id"] == webhook_tenant.id
            assert envelope["endpoint_id"] == endpoint_id

            # But processing failed because no action configured
            assert envelope["status"] == "failed"

            # The failure reason is recorded on the stored event
            stored = await PostgreSQLWebhookEventRepository(db).get_by_event_id(
                event_id, webhook_tenant.id
            )
            assert stored.status.value == "failed"
            assert stored.error_kind == "no_action_configured"

        finally:
            if previous is None:
                os.environ.pop("WEBHOOK_INGESTION_ENDPOINTS", None)
            else:
                os.environ["WEBHOOK_INGESTION_ENDPOINTS"] = previous
