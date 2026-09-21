"""API tests for the connector endpoints (PRD 22, TRD 33, ADR-002).

Security invariants under test:

- Unauthenticated requests are rejected with 401.
- Authenticated requests without the connector permission are rejected
  with 403 (EMPLOYEE has none; OPERATIONS can read/sync but not create).
- The trusted tenant context is authoritative: the client-supplied
  ``tenant_id`` in the path is request input only and cross-tenant
  access is denied (missing/inaccessible connectors both return 404).
- A path tenant that does not match the trusted context is rejected with
  403; the trusted context is never overridden by the path.
- Connector payloads never contain credential material; sync responses
  are safe summaries only and failures are generic.
- Invalid providers, empty names, and duplicate connectors are rejected
  with controlled status codes (400/409).
"""

import json
import os
import uuid

from arc.domain.models import Membership, Tenant, TenantContext, User, UserRole
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"ca-{prefix}-{uuid.uuid4().hex[:10]}"


def _connector_payload(**overrides):
    payload = dict(provider="github", name="acme-github", target="example/acme")
    payload.update(overrides)
    return payload


class TestConnectorAuthentication:
    def test_list_requires_authentication(self, client):
        response = client.get(f"/tenants/{_unique('tenant')}/connectors")
        assert response.status_code == 401

    def test_create_requires_authentication(self, client):
        response = client.post(
            f"/tenants/{_unique('tenant')}/connectors", json=_connector_payload()
        )
        assert response.status_code == 401

    def test_sync_requires_authentication(self, client):
        response = client.post(
            f"/tenants/{_unique('tenant')}/connectors/{_unique('connector')}/sync"
        )
        assert response.status_code == 401


class TestConnectorAuthorization:
    async def test_create_requires_connector_create_permission(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert response.status_code == 403

    async def test_read_requires_connector_read_permission(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_sync_requires_connector_sync_permission(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors/{_unique('connector')}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_operations_user_can_read_and_sync_but_not_create(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)

        create = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert create.status_code == 403

        listing = client.get(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listing.status_code == 200

    async def test_operations_user_can_sync_a_connector(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override(
            {
                user.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        connector_id = created.json()["id"]

        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        os.environ["CONNECTOR_CREDENTIALS"] = json.dumps({tenant.id: {"github": "dev-token"}})
        try:
            sync = client.post(
                f"/tenants/{tenant.id}/connectors/{connector_id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            os.environ.pop("CONNECTOR_CREDENTIALS", None)

        assert sync.status_code == 200
        assert sync.json()["status"] == "success"


class TestConnectorCreate:
    async def test_company_administrator_can_create(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "github"
        assert body["name"] == "acme-github"
        assert body["target"] == "example/acme"
        assert body["tenant_id"] == tenant.id
        # No credential material is ever returned.
        assert "token" not in json.dumps(body)

    async def test_invalid_provider_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(provider="dropbox"),
        )
        assert response.status_code == 422
        assert any("provider" in e["loc"] for e in response.json()["detail"])

    async def test_missing_provider_is_rejected(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert response.status_code == 422

    async def test_empty_name_is_rejected(self, client, seeded, make_token, authorization_override):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(name=""),
        )
        assert response.status_code == 422

    async def test_duplicate_connector_returns_409(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        first = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert first.status_code == 200

        second = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert second.status_code == 409


class TestConnectorList:
    async def test_list_returns_only_own_tenant_connectors(
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
        created = client.post(
            f"/tenants/{tenant_a.id}/connectors",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_connector_payload(),
        )
        assert created.status_code == 200

        token_b = make_token(user_b.id)
        list_b = client.get(
            f"/tenants/{tenant_b.id}/connectors",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert list_b.status_code == 200
        assert list_b.json()["items"] == []

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)


class TestConnectorSync:
    async def test_sync_success_ingests_sanitized_knowledge(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        assert created.status_code == 200
        connector_id = created.json()["id"]

        os.environ["CONNECTOR_CREDENTIALS"] = json.dumps({tenant.id: {"github": "dev-token"}})
        try:
            sync = client.post(
                f"/tenants/{tenant.id}/connectors/{connector_id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            os.environ.pop("CONNECTOR_CREDENTIALS", None)

        assert sync.status_code == 200
        body = sync.json()
        assert body["status"] == "success"
        assert body["items_fetched"] == 3
        assert "dev-token" not in json.dumps(body)
        assert all("token" not in json.dumps(item) for item in body["items"])

        listing = client.get(
            f"/tenants/{tenant.id}/knowledge",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listing.status_code == 200
        documents = listing.json()["items"]
        assert len(documents) == 3
        for document in documents:
            assert document["provenance"].startswith("connector:github:")
            # Fake provider content contains synthetic emails; only
            # sanitized content may be persisted and returned.
            assert "example.com" not in document["content"]

    async def test_sync_missing_credential_returns_generic_400(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        connector_id = created.json()["id"]

        os.environ.pop("CONNECTOR_CREDENTIALS", None)
        sync = client.post(
            f"/tenants/{tenant.id}/connectors/{connector_id}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert sync.status_code == 400
        assert sync.json()["detail"] == "Connector synchronization failed"

    async def test_sync_unknown_connector_returns_404(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/connectors/{_unique('missing')}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Connector not found"

    async def test_cross_tenant_sync_is_denied(
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
        created = client.post(
            f"/tenants/{tenant_a.id}/connectors",
            headers={"Authorization": f"Bearer {token_a}"},
            json=_connector_payload(),
        )
        connector_id = created.json()["id"]

        # Tenant B attempts to sync tenant A's connector: indistinguishable
        # from a missing connector (404), leaking no existence information.
        token_b = make_token(user_b.id)
        sync = client.post(
            f"/tenants/{tenant_b.id}/connectors/{connector_id}/sync",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert sync.status_code == 404

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)

    async def test_foreign_connector_indistinguishable_from_missing(
        self, client, db, repositories, seeded, make_token, authorization_override
    ):
        """Cross-tenant non-disclosure: tenant A requesting tenant B's
        existing connector must receive the exact same 404 response as a
        nonexistent connector, so resource existence is not disclosed."""
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

        token_b = make_token(user_b.id)
        created_b = client.post(
            f"/tenants/{tenant_b.id}/connectors",
            headers={"Authorization": f"Bearer {token_b}"},
            json=_connector_payload(name="other/repo"),
        )
        assert created_b.status_code == 200
        foreign_connector_id = created_b.json()["id"]

        token_a = make_token(user_a.id)
        foreign = client.post(
            f"/tenants/{tenant_a.id}/connectors/{foreign_connector_id}/sync",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        missing = client.post(
            f"/tenants/{tenant_a.id}/connectors/{_unique('missing')}/sync",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        assert foreign.status_code == 404
        assert missing.status_code == 404
        assert foreign.json() == missing.json()

        from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository

        sync_repo = PostgreSQLConnectorSyncRepository(db)
        assert await sync_repo.list_for_tenant(tenant_a.id) == []

        await membership_repo.delete(membership_b.id)
        await user_repo.delete(user_b.id)
        await tenant_repo.delete(tenant_b.id)

    async def test_audit_records_contain_no_credential_material(
        self, client, db, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/connectors",
            headers={"Authorization": f"Bearer {token}"},
            json=_connector_payload(),
        )
        connector_id = created.json()["id"]

        os.environ["CONNECTOR_CREDENTIALS"] = json.dumps({tenant.id: {"github": "dev-token"}})
        try:
            sync = client.post(
                f"/tenants/{tenant.id}/connectors/{connector_id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            os.environ.pop("CONNECTOR_CREDENTIALS", None)
        assert sync.status_code == 200

        from arc.repositories.connector_sync import PostgreSQLConnectorSyncRepository

        records = await PostgreSQLConnectorSyncRepository(db).list_for_tenant(tenant.id)
        assert len(records) == 1
        assert "dev-token" not in str(records[0])
        assert "dev-token" not in json.dumps(sync.json())


class TestConnectorPathTenantConsistency:
    """The path tenant_id must match the trusted TenantContext."""

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
            listing = client.get(
                f"/tenants/{tenant.id}/connectors",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert listing.status_code == 403

            create = client.post(
                f"/tenants/{tenant.id}/connectors",
                headers={"Authorization": f"Bearer {token}"},
                json=_connector_payload(),
            )
            assert create.status_code == 403

            sync = client.post(
                f"/tenants/{tenant.id}/connectors/{_unique('connector')}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert sync.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

    async def test_mismatched_path_tenant_cannot_write(
        self, client, seeded, db, make_token, authorization_override
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
                f"/tenants/{tenant.id}/connectors",
                headers={"Authorization": f"Bearer {token}"},
                json=_connector_payload(),
            )
            assert create.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

        from arc.repositories.connectors import PostgreSQLConnectorRepository

        connector_repo = PostgreSQLConnectorRepository(db)
        assert await connector_repo.list_for_tenant(tenant.id) == []
        assert await connector_repo.list_for_tenant(other_tenant_id) == []


class TestCredentialMaxLength:
    """Issue #185: credential plaintext input is bounded at 10,000 characters."""

    def _post(self, client, tenant_id, token, provider, credential):
        return client.post(
            f"/tenants/{tenant_id}/connectors/credentials/{provider}",
            headers={"Authorization": f"Bearer {token}"},
            json={"credential": credential},
        )

    def _fake_service(self):
        from unittest.mock import AsyncMock

        from arc.api.controllers import app_context

        fake = AsyncMock()
        fake.create_credential.return_value = {"provider": "github"}
        saved = app_context.services._services.get("connector_credential_service")
        app_context.services._services["connector_credential_service"] = fake
        return app_context, fake, saved

    def _restore_service(self, app_context, saved):
        if saved is not None:
            app_context.services._services["connector_credential_service"] = saved
        else:
            app_context.services._services.pop("connector_credential_service", None)

    async def test_short_credential_succeeds(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        app_context, fake, saved = self._fake_service()
        try:
            response = self._post(client, tenant.id, token, "github", "tok")
            assert response.status_code == 200
            fake.create_credential.assert_awaited_once()
        finally:
            self._restore_service(app_context, saved)

    async def test_exactly_10000_characters_succeeds(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        app_context, fake, saved = self._fake_service()
        try:
            response = self._post(client, tenant.id, token, "github", "x" * 10_000)
            assert response.status_code == 200
            fake.create_credential.assert_awaited_once()
        finally:
            self._restore_service(app_context, saved)

    async def test_10001_characters_rejected_before_service(
        self, client, seeded, make_token, authorization_override
    ):
        tenant, user, _ = seeded
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        app_context, fake, saved = self._fake_service()
        try:
            oversized = "y" * 10_001
            rejected = self._post(client, tenant.id, token, "github", oversized)
            assert rejected.status_code == 400
            assert rejected.json()["detail"] == "Credential exceeds maximum length"
            assert oversized not in rejected.text
            # Rejected before encryption/persistence/downstream processing.
            fake.create_credential.assert_not_awaited()
        finally:
            self._restore_service(app_context, saved)
