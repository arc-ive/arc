"""API tests for the Secure RAG knowledge search endpoint.

Security invariants under test:

- Unauthenticated requests are rejected with 401.
- Authenticated requests without the ``knowledge:read`` permission are
  rejected with 403 (retrieval reuses the existing permission; it is not
  a new capability).
- The trusted tenant context is authoritative: a path tenant that does
  not match the context is rejected with 403, and cross-tenant search
  returns no results (no information leak).
- Search only ever returns already-sanitized content.
- Empty queries and invalid limits are rejected with 400.
- The search route does not shadow the existing document-by-ID route.
"""

import uuid

from arc.api.controllers import app_context
from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.repositories.knowledge import PostgreSQLKnowledgeRepository
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole
from arc.services.embeddings import EmbeddingError


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"ra-{prefix}-{uuid.uuid4().hex[:10]}"


def _knowledge_payload(**overrides):
    payload = dict(
        source="policy",
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    payload.update(overrides)
    return payload


class ExplodingEmbeddingProvider:
    """Embedding provider that always fails: proves the 500 fail-closed path."""

    def embed(self, text: str):
        raise EmbeddingError("embedding provider unavailable")

    def embed_many(self, texts):
        raise EmbeddingError("embedding provider unavailable")


def _swap_embedding_provider(provider):
    """Swap the app retrieval service's embedding provider; returns a restorer."""
    original = app_context.retrieval_service.embedding_provider
    app_context.retrieval_service.embedding_provider = provider
    return original


class TestIngestionEmbeddingError:
    """An embedding failure during ingestion returns 500 and persists nothing.

    The error must be mapped to the generic ingestion failure message and
    must never expose provider/internal exception details.
    """

    async def test_ingestion_embedding_error_returns_500_and_persists_nothing(
        self, client, seeded, db, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        original = _swap_embedding_provider(ExplodingEmbeddingProvider())
        try:
            response = client.post(
                f"/tenants/{tenant.id}/knowledge",
                headers={"Authorization": f"Bearer {token}"},
                json=_knowledge_payload(content="approved remote work policy"),
            )
        finally:
            app_context.retrieval_service.embedding_provider = original

        assert response.status_code == 500
        assert response.json()["detail"] == "Knowledge ingestion failed"
        assert "embedding" not in response.text.lower()

        # Fail closed: no document (and therefore no chunks) persisted.
        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        assert await knowledge_repo.list_for_tenant(tenant.id) == []


class TestSearchEmbeddingError:
    """An embedding failure during search returns 500 with the generic message."""

    async def test_search_embedding_error_returns_500(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        original = _swap_embedding_provider(ExplodingEmbeddingProvider())
        try:
            response = client.get(
                f"/tenants/{tenant.id}/knowledge/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"query": "remote"},
            )
        finally:
            app_context.retrieval_service.embedding_provider = original

        assert response.status_code == 500
        assert response.json()["detail"] == "Knowledge search failed"
        assert "embedding" not in response.text.lower()


class TestSearchAuthentication:
    def test_search_requires_authentication(self, client):
        response = client.get(
            f"/tenants/{_unique('tenant')}/knowledge/search",
            params={"query": "remote"},
        )
        assert response.status_code == 401


class TestSearchAuthorization:
    async def test_employee_can_search_knowledge(
        self, client, seeded, make_token, authorization_override
    ):
        """EMPLOYEE holds knowledge:read (PRD 7.4) and can search documents."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "remote"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_company_administrator_can_search(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        create = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="Approved remote work policy."),
        )
        assert create.status_code == 200

        search = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "remote work"},
        )
        assert search.status_code == 200
        matches = search.json()
        assert len(matches) == 1
        assert matches[0]["document_id"] == create.json()["id"]
        assert matches[0]["tenant_id"] == tenant.id
        assert "remote" in matches[0]["content"].lower()
        assert set(matches[0]) == {
            "chunk_id",
            "document_id",
            "tenant_id",
            "content",
            "source",
            "provenance",
            "document_version",
            "sequence",
            "similarity",
        }


class TestSearchTenantIsolation:
    async def test_cross_tenant_search_returns_no_results(
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

        # Tenant A creates a document with a distinctive secret term.
        token_a = make_token(user_a.id)
        create = client.post(
            f"/tenants/{tenant_a.id}/knowledge",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_knowledge_payload(content="Tenant A secret strategy alpha"),
        )
        assert create.status_code == 200

        # Tenant A finds its own content.
        search_a = client.get(
            f"/tenants/{tenant_a.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token_a}"},
            params={"query": "secret strategy"},
        )
        assert search_a.status_code == 200
        assert len(search_a.json()) == 1

        # Tenant B searching the same term sees nothing: no information leak.
        token_b = make_token(user_b.id)
        search_b = client.get(
            f"/tenants/{tenant_b.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token_b}"},
            params={"query": "secret strategy"},
        )
        assert search_b.status_code == 200
        assert search_b.json() == []

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)


class TestSearchPathTenantConsistency:
    async def test_mismatched_path_tenant_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        other_tenant_id = _unique("other-tenant")
        mismatched_context = TenantContext(
            tenant_id=other_tenant_id,
            tenant_name="Other Tenant",
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_trusted_tenant_context] = lambda: mismatched_context
        try:
            search = client.get(
                f"/tenants/{tenant.id}/knowledge/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"query": "remote"},
            )
            assert search.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)


class TestSearchInputValidation:
    async def test_empty_query_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": ""},
        )
        assert response.status_code == 400

    async def test_blank_query_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "   "},
        )
        assert response.status_code == 400

    async def test_limit_out_of_range_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        for invalid in (0, 51, -1):
            response = client.get(
                f"/tenants/{tenant.id}/knowledge/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"query": "remote", "limit": invalid},
            )
            assert response.status_code == 400, f"limit={invalid}"


class TestSearchPiiBoundary:
    async def test_search_returns_only_sanitized_content(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        raw = "Contact alice.smith@example.com for access."
        create = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content=raw),
        )
        assert create.status_code == 200
        assert "alice.smith@example.com" not in create.json()["content"]

        search = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "contact"},
        )
        assert search.status_code == 200
        matches = search.json()
        assert len(matches) >= 1
        # The email was sanitized before ingestion and therefore can never
        # appear in retrieval results.
        assert all("alice.smith@example.com" not in match["content"] for match in matches)


class TestSearchRouteSurface:
    async def test_search_route_does_not_shadow_document_by_id(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        create = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(),
        )
        assert create.status_code == 200
        document_id = create.json()["id"]

        read = client.get(
            f"/tenants/{tenant.id}/knowledge/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.status_code == 200
        assert read.json()["id"] == document_id


class TestSearchSourceFiltering:
    """Source-type filtering on the search endpoint."""

    async def test_no_filter_returns_all_sources(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content alpha"),
        )
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="procedure", content="procedure content beta"),
        )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_policy_filter_returns_only_policy_documents(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content"),
        )
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="procedure", content="procedure content"),
        )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "policy"},
        )
        assert response.status_code == 200
        matches = response.json()
        assert len(matches) == 1
        assert matches[0]["source"] == "policy"

    async def test_procedure_filter_returns_only_procedure_documents(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content"),
        )
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="procedure", content="procedure content"),
        )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "procedure"},
        )
        assert response.status_code == 200
        matches = response.json()
        assert len(matches) == 1
        assert matches[0]["source"] == "procedure"

    async def test_incident_report_filter_works(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content"),
        )
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="incident_report", content="incident content"),
        )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "incident_report"},
        )
        assert response.status_code == 200
        matches = response.json()
        assert len(matches) == 1
        assert matches[0]["source"] == "incident_report"

    async def test_source_filter_returns_empty_when_no_matching_source(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content"),
        )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "procedure"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_archived_documents_excluded_with_source_filter(
        self, client, seeded, db, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        create = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy content"),
        )
        assert create.status_code == 200
        doc_id = create.json()["id"]

        # Archive the document
        async with db._connection_pool.acquire() as conn:
            await conn.execute(
                "UPDATE knowledge_documents SET status = 'archived' WHERE id = $1",
                doc_id,
            )

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "policy"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_source_filter_preserves_tenant_isolation(
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
        client.post(
            f"/tenants/{tenant_a.id}/knowledge",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_knowledge_payload(content="tenant A policy secret"),
        )

        token_b = make_token(user_b.id)
        response = client.get(
            f"/tenants/{tenant_b.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token_b}"},
            params={"query": "policy secret", "source_type": "policy"},
        )
        assert response.status_code == 200
        assert response.json() == []

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)

    async def test_invalid_source_type_returns_400(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "remote", "source_type": "invalid_source"},
        )
        assert response.status_code == 400
        assert "Invalid source_type" in response.json()["detail"]

    async def test_multiple_source_types_isolated_from_each_other(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content="policy alpha"),
        )
        client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="incident_report", content="incident beta"),
        )

        policy_response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "policy"},
        )
        incident_response = client.get(
            f"/tenants/{tenant.id}/knowledge/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": "content", "source_type": "incident_report"},
        )

        assert policy_response.status_code == 200
        assert len(policy_response.json()) == 1
        assert policy_response.json()[0]["source"] == "policy"

        assert incident_response.status_code == 200
        assert len(incident_response.json()) == 1
        assert incident_response.json()[0]["source"] == "incident_report"
