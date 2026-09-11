"""API tests for Company Brain knowledge endpoints.

Security invariants under test:

- Unauthenticated requests are rejected with 401.
- Authenticated requests without the knowledge permission are rejected
  with 403.
- The trusted tenant context (from the JWT principal + persisted
  membership) is authoritative: the client-supplied tenant_id in the path
  is request input only and cross-tenant access is denied.
- A path tenant that does not match the trusted context is rejected with
  403; the trusted context is never overridden by the path.
- Missing and inaccessible documents are indistinguishable: both return
  404 at the API boundary.
- Raw content is sanitized by the real PII Guard before persistence, and
  only sanitized content is ever returned (single-get and list).
- Invalid knowledge input is rejected with 400.
"""

import uuid

from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"ka-{prefix}-{uuid.uuid4().hex[:10]}"


def _knowledge_payload(**overrides):
    payload = dict(
        source="policy",
        provenance="Policy handbook 2026 edition",
        content="Approved remote work policy.",
    )
    payload.update(overrides)
    return payload


class TestKnowledgeAuthentication:
    def test_create_requires_authentication(self, client):
        response = client.post(f"/tenants/{_unique('tenant')}/knowledge", json=_knowledge_payload())
        assert response.status_code == 401

    def test_read_requires_authentication(self, client):
        response = client.get(f"/tenants/{_unique('tenant')}/knowledge/{_unique('doc')}")
        assert response.status_code == 401


class TestKnowledgeAuthorization:
    async def test_create_requires_knowledge_create_permission(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(),
        )
        assert response.status_code == 403

    async def test_employee_can_read_knowledge_document(
        self, client, seeded, make_token, authorization_override
    ):
        """EMPLOYEE holds knowledge:read (PRD §7.4) and can read documents."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        # Non-existent document returns 404 (not 403) — the permission
        # check passes, but the document does not exist.
        response = client.get(
            f"/tenants/{tenant.id}/knowledge/{_unique('doc')}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_company_administrator_can_create_and_read(
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

    async def test_platform_administrator_can_create(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.PLATFORM_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(),
        )
        assert response.status_code == 200


class TestKnowledgeTenantIsolation:
    async def test_cross_tenant_read_is_denied(
        self, client, repositories, seeded, make_token, authorization_override
    ):
        tenant_a, user_a, _ = seeded
        tenant_repo, user_repo, membership_repo = repositories

        # Tenant B user with a membership in tenant B.
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

        # Tenant A creates a document.
        token_a = make_token(user_a.id)
        create = client.post(
            f"/tenants/{tenant_a.id}/knowledge",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_knowledge_payload(content="Tenant A secret policy"),
        )
        assert create.status_code == 200
        document_id = create.json()["id"]

        # Tenant B attempts to read Tenant A's document by ID -> denied.
        # A 404 is returned: the missing-document and inaccessible-document
        # cases are indistinguishable, so no information about tenant A's
        # documents leaks to tenant B.
        token_b = make_token(user_b.id)
        read = client.get(
            f"/tenants/{tenant_b.id}/knowledge/{document_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert read.status_code == 404

        # Tenant B listing only sees their own documents.
        list_b = client.get(
            f"/tenants/{tenant_b.id}/knowledge",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert list_b.status_code == 200
        assert all(doc["tenant_id"] == tenant_b.id for doc in list_b.json()["items"])

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)

    async def test_missing_membership_is_denied(
        self, client, repositories, seeded, make_token, authorization_override
    ):
        tenant, _, _ = seeded
        _, user_repo, _ = repositories
        orphan = await user_repo.create(
            User(id=_unique("orphan"), email=f"{uuid.uuid4().hex}@example.com", username="o")
        )
        authorization_override({orphan.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(orphan.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(),
        )
        assert response.status_code == 403

        await user_repo.delete(orphan.id)


class TestKnowledgePiiBoundary:
    async def test_raw_pii_is_sanitized_before_persistence_and_response(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        raw = "Contact alice.smith@example.com for access."
        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content=raw),
        )
        assert response.status_code == 200
        body = response.json()
        assert "alice.smith@example.com" not in body["content"]

        read = client.get(
            f"/tenants/{tenant.id}/knowledge/{body['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert "alice.smith@example.com" not in read.json()["content"]

    async def test_invalid_source_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(source="not-a-source"),
        )
        assert response.status_code == 422

    async def test_missing_content_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content=""),
        )
        assert response.status_code == 422


class TestKnowledgePathTenantConsistency:
    """The path tenant_id must match the trusted TenantContext.

    The trusted context remains the authoritative tenant boundary; the
    path parameter is request input only and is validated for consistency.
    """

    async def test_matching_path_tenant_succeeds_and_boundary_comes_from_context(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        # The persisted document belongs to the trusted context tenant,
        # which matches the path tenant here.
        assert body["tenant_id"] == tenant.id

    async def test_mismatched_path_tenant_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        # Establish a trusted context for a DIFFERENT tenant than the path.
        other_tenant_id = _unique("other-tenant")
        mismatched_context = TenantContext(
            tenant_id=other_tenant_id,
            tenant_name="Other Tenant",
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_trusted_tenant_context] = lambda: mismatched_context
        try:
            create = client.post(
                f"/tenants/{tenant.id}/knowledge",
                headers={"Authorization": f"Bearer {token}"},
                json=_knowledge_payload(content="Cross-tenant write attempt"),
            )
            assert create.status_code == 403

            read = client.get(
                f"/tenants/{tenant.id}/knowledge/{_unique('doc')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert read.status_code == 403

            listing = client.get(
                f"/tenants/{tenant.id}/knowledge",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

    async def test_mismatched_path_tenant_cannot_write(
        self,
        client,
        seeded,
        db,
        make_token,
        authorization_override,
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
            create = client.post(
                f"/tenants/{tenant.id}/knowledge",
                headers={"Authorization": f"Bearer {token}"},
                json=_knowledge_payload(content="Cross-tenant write attempt"),
            )
            assert create.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

        # The rejected request must not have persisted anything in either tenant.
        from arc.repositories.knowledge import PostgreSQLKnowledgeRepository

        knowledge_repo = PostgreSQLKnowledgeRepository(db)
        assert await knowledge_repo.list_for_tenant(tenant.id) == []
        assert await knowledge_repo.list_for_tenant(other_tenant_id) == []


class TestKnowledgeNotFoundBoundary:
    """A genuinely nonexistent document ID returns 404.

    The 404 must not rely on a cross-tenant document: with a valid
    membership and the knowledge:read permission, a nonexistent ID in the
    caller's own tenant is indistinguishable from an inaccessible document.
    """

    async def test_nonexistent_document_id_returns_404(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/knowledge/{_unique('nonexistent-doc')}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestKnowledgeListPiiBoundary:
    """The list endpoint returns only sanitized content."""

    async def test_list_endpoint_returns_sanitized_content(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        raw = "Contact bob.jones@example.com for access."
        create = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(content=raw),
        )
        assert create.status_code == 200
        # Sanitized before persistence: the create response must not leak raw PII.
        assert "bob.jones@example.com" not in create.json()["content"]

        listing = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listing.status_code == 200
        documents = listing.json()["items"]
        assert len(documents) == 1
        # The list response must not contain raw PII.
        for document in documents:
            assert "bob.jones@example.com" not in document["content"]


class TestKnowledgeExternalId:
    """Verify the public API wires external_id through to ADR-003 behavior.

    The POST /tenants/{tenant_id}/knowledge endpoint must accept an optional
    ``external_id`` field and pass it to KnowledgeService.ingest_document()
    unchanged.  When omitted, existing create-every-time behavior is
    preserved.  When supplied, ADR-003 re-ingestion semantics apply:
    idempotent redelivery for identical content, version bump for changed
    content, and tenant-scoped identity.
    """

    async def test_create_without_external_id_unchanged(
        self, client, seeded, make_token, authorization_override
    ):
        """POST without external_id behaves exactly as before."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        payload = _knowledge_payload(provenance="ext-test-no-id")
        r1 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert r1.status_code == 200
        doc1 = r1.json()
        assert doc1["version"] == 1
        assert doc1["external_id"] is None

        # A second POST without external_id always creates a new document.
        r2 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert r2.status_code == 200
        doc2 = r2.json()
        assert doc2["id"] != doc1["id"]

    async def test_first_create_with_external_id(
        self, client, seeded, make_token, authorization_override
    ):
        """First ingestion with external_id creates a new document."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        r = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-first",
                external_id="test-ext-001",
                content="First version of the document.",
            ),
        )
        assert r.status_code == 200
        doc = r.json()
        assert doc["version"] == 1
        assert doc["external_id"] == "test-ext-001"
        assert doc["source"] == "policy"

    async def test_idempotent_redelivery_same_content(
        self, client, seeded, make_token, authorization_override
    ):
        """Same external_id + same content → returned unchanged (idempotent)."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        content = "Stable content for idempotency check."
        r1 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-idempotent",
                external_id="test-ext-idempotent",
                content=content,
            ),
        )
        assert r1.status_code == 200
        doc1 = r1.json()

        r2 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-idempotent",
                external_id="test-ext-idempotent",
                content=content,
            ),
        )
        assert r2.status_code == 200
        doc2 = r2.json()

        # Same logical document: same id, same version, same content.
        assert doc2["id"] == doc1["id"]
        assert doc2["version"] == doc1["version"]
        assert doc2["content"] == doc1["content"]

    async def test_changed_content_bumps_version(
        self, client, seeded, make_token, authorization_override
    ):
        """Same external_id + different content → version bump, same id."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        r1 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-version",
                external_id="test-ext-version",
                content="Original content.",
            ),
        )
        assert r1.status_code == 200
        doc1 = r1.json()
        assert doc1["version"] == 1

        r2 = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-version",
                external_id="test-ext-version",
                content="Updated content with new information.",
            ),
        )
        assert r2.status_code == 200
        doc2 = r2.json()

        # Same logical document identity preserved, version incremented.
        assert doc2["id"] == doc1["id"]
        assert doc2["version"] == doc1["version"] + 1
        assert doc2["content"] != doc1["content"]
        # Provenance is immutable.
        assert doc2["provenance"] == doc1["provenance"]

    async def test_tenant_isolation_for_external_id(
        self, client, repositories, seeded, make_token, authorization_override
    ):
        """Same external_id in tenant-a must not collide with tenant-b."""
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
        token_b = make_token(user_b.id)
        shared_ext_id = "shared-external-id"

        r_a = client.post(
            f"/tenants/{tenant_a.id}/knowledge",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_knowledge_payload(
                provenance="tenant-a-doc",
                external_id=shared_ext_id,
                content="Tenant A content.",
            ),
        )
        assert r_a.status_code == 200
        doc_a = r_a.json()

        r_b = client.post(
            f"/tenants/{tenant_b.id}/knowledge",
            headers={"Authorization": f"Bearer {token_b}"},
            json=_knowledge_payload(
                provenance="tenant-b-doc",
                external_id=shared_ext_id,
                content="Tenant B content.",
            ),
        )
        assert r_b.status_code == 200
        doc_b = r_b.json()

        # Different tenants: different documents even with same external_id.
        assert doc_a["id"] != doc_b["id"]
        assert doc_a["tenant_id"] == tenant_a.id
        assert doc_b["tenant_id"] == tenant_b.id

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)

    async def test_pii_sanitization_with_external_id(
        self, client, seeded, make_token, authorization_override
    ):
        """PII is sanitized even when external_id is supplied."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        raw = "Contact carol@example.com for details."
        r = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-pii",
                external_id="test-ext-pii",
                content=raw,
            ),
        )
        assert r.status_code == 200
        doc = r.json()
        assert "carol@example.com" not in doc["content"]
        assert doc["external_id"] == "test-ext-pii"

        # Persisted document is also sanitized.
        read = client.get(
            f"/tenants/{tenant.id}/knowledge/{doc['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.status_code == 200
        assert "carol@example.com" not in read.json()["content"]

    async def test_empty_external_id_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        """Empty string external_id is rejected by the service validation."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        r = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-empty",
                external_id="",
                content="Test content.",
            ),
        )
        assert r.status_code == 400

    async def test_external_id_in_get_response(
        self, client, seeded, make_token, authorization_override
    ):
        """GET /knowledge/{id} returns external_id when present."""
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        r = client.post(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
            json=_knowledge_payload(
                provenance="ext-test-get",
                external_id="test-ext-get-response",
                content="Document with external_id.",
            ),
        )
        assert r.status_code == 200
        doc_id = r.json()["id"]

        read = client.get(
            f"/tenants/{tenant.id}/knowledge/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.status_code == 200
        assert read.json()["external_id"] == "test-ext-get-response"
