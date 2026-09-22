"""Request-contract validation tests (Issue #135).

Derived from the issue's Definition of Done — "Invalid requests receive 422
with structured error details" — not from the models that implement it.

Every assertion here describes behaviour a caller can observe: a status code,
and for 422s the fact that ``detail`` is a structured list rather than a bare
string. Before this issue's change, the payloads below produced 400, 500, or a
silent 200 instead.
"""

import pytest

from arc.security.models import ApplicationRole


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _assert_structured_422(response):
    """A 422 must carry FastAPI's structured per-field detail, not a string."""
    assert response.status_code == 422, (
        f"expected 422, got {response.status_code}: {response.text[:200]}"
    )
    detail = response.json()["detail"]
    assert isinstance(detail, list), f"detail must be a structured list, got {type(detail)}"
    assert detail, "detail list must not be empty"
    assert "loc" in detail[0], f"each error must identify the offending field: {detail[0]}"


@pytest.fixture
def admin(seeded, make_token, authorization_override):
    """Platform administrator principal for the seeded tenant."""
    tenant, user, _ = seeded
    authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
    return tenant, user, make_token(user.id)


class TestMissingRequiredFieldsReturn422:
    """R3: inputs that previously produced an unhandled 500 now return 422."""

    async def test_create_tenant_with_empty_body(self, client, admin):
        _, _, token = admin
        response = client.post("/tenants", json={}, headers=_auth(token))
        _assert_structured_422(response)

    async def test_create_user_with_empty_body(self, client, admin):
        _, _, token = admin
        response = client.post("/users", json={}, headers=_auth(token))
        _assert_structured_422(response)

    async def test_create_skill_with_empty_body(self, client, admin):
        tenant, _, token = admin
        response = client.post(f"/tenants/{tenant.id}/skills", json={}, headers=_auth(token))
        _assert_structured_422(response)

    async def test_create_tenant_with_empty_string_id(self, client, admin):
        """An explicitly empty string is as invalid as a missing key."""
        _, _, token = admin
        response = client.post(
            "/tenants", json={"id": "", "name": "Valid Name"}, headers=_auth(token)
        )
        _assert_structured_422(response)

    async def test_update_tenant_with_empty_string_name(self, client, admin):
        tenant, _, token = admin
        response = client.put(f"/tenants/{tenant.id}", json={"name": ""}, headers=_auth(token))
        _assert_structured_422(response)


class TestResumeStepsReturn422:
    """R3: a malformed ``previous_steps`` entry produced an unhandled 500.

    The entries were read by direct dictionary indexing with an unwrapped enum
    parse, outside the handler's try/except. Body validation now runs before
    the handler, so the skill need not exist for the request to be rejected.
    """

    async def test_skill_resume_with_missing_step_key(self, client, admin):
        tenant, _, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/skills/does-not-matter/resume",
            json={
                "approval_id": "a-1",
                "tool_calls": [{"tool": "x"}],
                "resume_from_step": 0,
                "previous_steps": [{"tool_name": "x", "status": "success"}],
            },
            headers=_auth(token),
        )
        _assert_structured_422(response)

    @pytest.mark.parametrize(
        "step",
        [
            pytest.param(
                {"sequence": 1, "tool_name": "x", "status": "success"}, id="success-no-output"
            ),
            pytest.param(
                {"sequence": 1, "tool_name": "x", "status": "failed"}, id="failed-no-error-kind"
            ),
            pytest.param(
                {"sequence": 1, "tool_name": "", "status": "failed", "error_kind": "e"},
                id="empty-tool-name",
            ),
            pytest.param(
                {"sequence": -1, "tool_name": "x", "status": "failed", "error_kind": "e"},
                id="negative-sequence",
            ),
            pytest.param(
                {"sequence": True, "tool_name": "x", "status": "failed", "error_kind": "e"},
                id="boolean-sequence",
            ),
        ],
    )
    async def test_skill_resume_rejects_steps_the_domain_model_refuses(self, client, admin, step):
        """Each of these reached SkillExecutionStepOutcome and raised a 500.

        Presence and type validation alone is not enough: the dataclass also
        enforces cross-field rules, and anything it rejects has to be rejected
        during request validation or it still surfaces as a 500.
        """
        tenant, _, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/skills/does-not-matter/resume",
            json={
                "approval_id": "a-1",
                "tool_calls": [{"tool": "x"}],
                "resume_from_step": 0,
                "previous_steps": [step],
            },
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_agent_resume_with_invalid_step_status(self, client, admin):
        tenant, _, token = admin
        response = client.post(
            "/agent/runs/resume",
            json={
                "tenant_id": tenant.id,
                "approval_id": "a-1",
                "skill_id": "s-1",
                "tool_calls": [{"tool": "x"}],
                "resume_from_step": 0,
                "previous_steps": [
                    {"sequence": 1, "tool_name": "x", "status": "not-a-real-status"}
                ],
            },
            headers=_auth(token),
        )
        _assert_structured_422(response)


class TestWrongTypesReturn422:
    """R1/R2: a field of the wrong type is rejected with structured detail."""

    async def test_create_tenant_with_non_string_id(self, client, admin):
        _, _, token = admin
        response = client.post(
            "/tenants", json={"id": 12345, "name": "Valid Name"}, headers=_auth(token)
        )
        _assert_structured_422(response)

    async def test_create_tenant_with_list_body(self, client, admin):
        _, _, token = admin
        response = client.post("/tenants", json=["not", "an", "object"], headers=_auth(token))
        _assert_structured_422(response)


class TestInvalidEnumValuesReturn422:
    """R4: fields backed by a domain enum reject unknown values."""

    async def test_membership_role(self, client, admin):
        tenant, user, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/memberships",
            json={"user_id": user.id, "role": "emperor"},
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_skill_status(self, client, admin):
        tenant, _, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/skills",
            json={"name": "S", "purpose": "P", "status": "banana"},
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_knowledge_source(self, client, admin):
        tenant, _, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            # Every other required field is valid, so only the bad enum can
            # be responsible for the rejection.
            json={"content": "C", "provenance": "p", "source": "hearsay"},
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_connector_provider(self, client, admin):
        tenant, _, token = admin
        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            json={"name": "C", "provider": "myspace"},
            headers=_auth(token),
        )
        _assert_structured_422(response)


class TestQueryParameterBounds:
    """R5: query parameters are bounded declaratively, so violations are 422."""

    async def test_knowledge_search_limit_above_maximum(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search?query=anything&limit=9999",
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_knowledge_search_limit_below_minimum(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search?query=anything&limit=0",
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_knowledge_search_invalid_source_type(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search?query=anything&source_type=gossip",
            headers=_auth(token),
        )
        _assert_structured_422(response)

    async def test_approvals_invalid_status_filter(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/approvals?status=nonsense",
            headers=_auth(token),
        )
        _assert_structured_422(response)


class TestOpenAPIDocumentsErrorResponses:
    """R6: the generated document lists the errors each endpoint can return.

    These assert the document, not the models, and they distinguish public
    routes from protected ones — declaring 401 on an endpoint that cannot
    return it would be as wrong as omitting it from one that can.
    """

    @staticmethod
    def _responses(path, method):
        from arc.main import app

        return set(app.openapi()["paths"][path][method].get("responses", {}))

    def test_protected_endpoint_documents_authentication_errors(self):
        responses = self._responses("/platform/users", "get")
        assert {"401", "403"} <= responses

    def test_endpoint_with_a_body_documents_validation_errors(self):
        responses = self._responses("/tenants", "post")
        assert {"401", "403", "422"} <= responses

    def test_public_health_endpoint_documents_no_auth_errors(self):
        responses = self._responses("/health", "get")
        assert "401" not in responses
        assert "403" not in responses

    def test_signature_authenticated_webhook_documents_401_but_not_403(self):
        """Webhook ingestion authenticates by HMAC, so RBAC's 403 never applies."""
        responses = self._responses("/webhooks/{endpoint_id}/events", "post")
        assert "401" in responses
        assert "403" not in responses


class TestValidRequestsAreUnaffected:
    """R8: the contract only tightens for invalid input, never for valid input."""

    async def test_valid_knowledge_search_still_succeeds(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search?query=anything&limit=5",
            headers=_auth(token),
        )
        assert response.status_code == 200

    async def test_valid_approvals_listing_still_succeeds(self, client, admin):
        tenant, _, token = admin
        response = client.get(
            f"/tenants/{tenant.id}/approvals?status=pending", headers=_auth(token)
        )
        assert response.status_code == 200

    async def test_approvals_listing_without_filter_still_succeeds(self, client, admin):
        tenant, _, token = admin
        response = client.get(f"/tenants/{tenant.id}/approvals", headers=_auth(token))
        assert response.status_code == 200

    async def test_partial_update_leaves_omitted_fields_untouched(self, client, admin):
        """The models must not turn a partial update into a full replacement.

        This is the highest-risk behaviour in the change: an omitted key has to
        keep its stored value, which depends on exclude_unset rather than on
        field defaults.
        """
        tenant, _, token = admin
        seed = client.put(
            f"/tenants/{tenant.id}",
            json={"name": "Contract Co", "industry": "Technology"},
            headers=_auth(token),
        )
        assert seed.status_code == 200

        response = client.put(
            f"/tenants/{tenant.id}", json={"industry": "Healthcare"}, headers=_auth(token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["industry"] == "Healthcare"
        assert body["name"] == "Contract Co"
