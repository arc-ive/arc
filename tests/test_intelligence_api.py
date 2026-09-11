"""API tests for the Unified Intelligence query endpoint.

Security invariants under test:

- Unauthenticated requests are rejected with 401.
- Authenticated requests without the knowledge read permission are
  rejected with 403 (reasoning is a read-class operation and reuses
  ``knowledge:read``; no new capability is invented).
- The trusted tenant context is authoritative: a path tenant that does
  not match it is rejected with 403.
- Retrieval is tenant-scoped: a caller never receives context or answers
  derived from another tenant's knowledge.
- The LLM receives only the Approved Context (sanitized content +
  citation references); the response never leaks raw PII.
- Fail closed: embedding and LLM failures map to a generic 500 with no
  internals; when no approved context matches, the answer is ``None`` and
  the LLM is never invoked.
"""

import uuid

from arc.api.controllers import app_context
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole
from arc.services.embeddings import EmbeddingError
from arc.services.intelligence import UnifiedIntelligenceService
from arc.services.llm import LlmError


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"ia-{prefix}-{uuid.uuid4().hex[:10]}"


def _knowledge_payload(**overrides):
    payload = dict(
        source="policy",
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    payload.update(overrides)
    return payload


def _query_payload(**overrides):
    payload = {"query": "remote work policy", "limit": 5}
    payload.update(overrides)
    return payload


def _create_document(client, tenant_id, token, content="Approved remote work policy."):
    response = client.post(
        f"/tenants/{tenant_id}/knowledge",
        headers={"Authorization": f"Bearer {token}"},
        json=_knowledge_payload(content=content),
    )
    assert response.status_code == 200
    return response.json()


class TestIntelligenceAuthentication:
    def test_query_requires_authentication(self, client):
        response = client.post(
            f"/tenants/{_unique('tenant')}/intelligence/query",
            json=_query_payload(),
        )
        assert response.status_code == 401


class TestIntelligenceAuthorization:
    async def test_employee_can_query_intelligence(
        self, client, seeded, make_token, authorization_override
    ):
        """EMPLOYEE holds knowledge:read (PRD §7.4) and can query intelligence."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        # No documents ingested for this tenant, so context_used is False
        # and answer is None — but the request itself is authorized.
        assert body["context_used"] is False
        assert body["answer"] is None


class TestIntelligenceHappyPath:
    async def test_company_administrator_can_reason_over_approved_context(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        document = _create_document(client, tenant.id, token)
        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(),
        )
        assert response.status_code == 200
        body = response.json()

        assert body["tenant_id"] == tenant.id
        assert body["query"] == "remote work policy"
        assert body["context_used"] is True
        assert len(body["citations"]) >= 1
        # The deterministic provider cites exactly the approved context
        # item that was retrieved; the answer is attributable.
        assert any(f"{document['id']}#c" in citation for citation in body["citations"])
        assert body["answer"] is not None
        assert body["answer"].startswith("Deterministic response")

    async def test_platform_administrator_can_query(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(),
        )
        assert response.status_code == 200
        assert response.json()["context_used"] is False


class TestIntelligenceNoContext:
    async def test_no_matching_context_returns_none_answer(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(query="quantum physics laboratory"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["context_used"] is False
        assert body["answer"] is None
        assert body["citations"] == []


class TestIntelligenceTenantIsolation:
    async def test_cross_tenant_query_never_leaks_context(
        self, client, repositories, seeded, make_token, authorization_override
    ):
        tenant_a, user_a, _ = seeded
        tenant_repo, user_repo, membership_repo = repositories

        user_b = await user_repo.create(
            User(id=_unique("user-b"), email=f"{uuid.uuid4().hex}@example.com", username="b")
        )
        tenant_b = await tenant_repo.create(Tenant(id=_unique("tenant-b"), name="Tenant B"))
        membership_b = await membership_repo.create(
            Membership(id=_unique("membership"), user_id=user_b.id, tenant_id=tenant_b.id)
        )

        authorization_override(
            {
                user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR,
                user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )

        token_a = make_token(user_a.id)
        _create_document(client, tenant_a.id, token_a, content="Tenant A secret policy")

        # Tenant B queries for the same topic: no context from tenant A is
        # ever supplied, so no answer is produced (nothing invented).
        token_b = make_token(user_b.id)
        response = client.post(
            f"/tenants/{tenant_b.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token_b}"},
            json=_query_payload(query="secret policy"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["context_used"] is False
        assert body["answer"] is None
        assert body["citations"] == []
        assert body["tenant_id"] == tenant_b.id

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)


class TestIntelligencePathTenantConsistency:
    async def test_mismatched_path_tenant_is_rejected(
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
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(),
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)


class TestIntelligenceValidation:
    async def test_empty_query_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(query=""),
        )
        assert response.status_code == 422

    async def test_missing_body_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_limit_out_of_range_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        for bad_limit in (0, 51, -1, "five"):
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(limit=bad_limit),
            )
            assert response.status_code == 422, bad_limit

    async def test_non_string_query_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        for bad_query in (123, [], {}, True, None):
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(query=bad_query),
            )
            assert response.status_code == 422, bad_query
            assert any("query" in error["loc"] for error in response.json()["detail"])

    async def test_boolean_limit_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        # bool is a subclass of int: True/False must never be accepted as
        # an integer limit.
        for bad_limit in (True, False):
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(limit=bad_limit),
            )
            assert response.status_code == 422, bad_limit
            assert any("limit" in error["loc"] for error in response.json()["detail"])

    async def test_valid_integer_limit_is_accepted(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(limit=5),
        )
        assert response.status_code == 200
        assert response.json()["context_used"] is False

    async def test_non_object_body_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        for bad_body in ([], "hello", 123, True, None):
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=bad_body,
            )
            assert response.status_code == 422, bad_body
            assert isinstance(response.json()["detail"], list)


class TestIntelligencePiiBoundary:
    async def test_raw_pii_never_reaches_the_response(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        raw = "Contact alice.smith@example.com for access."
        _create_document(client, tenant.id, token, content=raw)

        response = client.post(
            f"/tenants/{tenant.id}/intelligence/query",
            headers={"Authorization": f"Bearer {token}"},
            json=_query_payload(query="access"),
        )
        assert response.status_code == 200
        raw_response = response.text
        assert "alice.smith@example.com" not in raw_response
        assert "alice" not in raw_response.lower()


class TestIntelligenceFailClosed:
    async def test_llm_failure_maps_to_generic_500(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        _create_document(client, tenant.id, token)

        class FailingLlm:
            def complete(self, prompt: str) -> str:
                raise LlmError("model unavailable")

        original = app_context.services.get("intelligence_service")
        app_context.services.register(
            "intelligence_service",
            UnifiedIntelligenceService(original.retrieval, FailingLlm()),
        )
        try:
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(),
            )
            assert response.status_code == 500
            assert response.json()["detail"] == "Intelligence query failed"
        finally:
            app_context.services.register("intelligence_service", original)

    async def test_embedding_failure_maps_to_generic_500(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        _create_document(client, tenant.id, token)

        class FailingEmbeddingProvider:
            def embed(self, text: str):
                raise EmbeddingError("provider down")

        retrieval = app_context.services.get("retrieval_service")
        original_provider = retrieval.embedding_provider
        retrieval.embedding_provider = FailingEmbeddingProvider()
        try:
            response = client.post(
                f"/tenants/{tenant.id}/intelligence/query",
                headers={"Authorization": f"Bearer {token}"},
                json=_query_payload(),
            )
            assert response.status_code == 500
            assert response.json()["detail"] == "Intelligence query failed"
        finally:
            retrieval.embedding_provider = original_provider
