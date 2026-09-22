"""Skills Engine HTTP API tests (tenant-scoped, X-11 RBAC).

Covers the approved Skills management endpoints:

- POST /tenants/{tenant_id}/skills                (requires ``skill:create``)
- GET /tenants/{tenant_id}/skills                 (requires ``skill:read``)
- GET /tenants/{tenant_id}/skills/{skill_id}      (requires ``skill:read``)
- DELETE /tenants/{tenant_id}/skills/{skill_id}   (requires ``skill:delete``)

The client-supplied ``tenant_id`` (path) is request input only: the X-10
trusted tenant context verifies the authenticated principal's persisted
membership, and the SkillService derives tenant ownership exclusively from
that context. Cross-tenant access never reveals resource existence.

Consistency invariant: a client-supplied ``tenant_id`` that does not match
the trusted ``TenantContext`` is rejected with 403 on every Skills
endpoint (the trusted context is never overridden by the path parameter).
"""

import uuid

import pytest

from arc.domain.models import (
    Membership,
    Tenant,
    TenantContext,
    User,
    UserRole,
)
from arc.main import app
from arc.security.dependencies import get_trusted_tenant_context
from arc.security.models import ApplicationRole

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _unique(prefix: str) -> str:
    """Return a unique identifier for test data."""
    return f"skill-api-{prefix}-{uuid.uuid4().hex[:10]}"


def _skill_payload(**overrides) -> dict:
    """Return a valid Skill creation payload with overridable fields."""
    values = {
        "name": "Service Recovery",
        "purpose": "Recover a degraded service",
    }
    values.update(overrides)
    return values


async def _seed_tenant(repositories, name="Skills Tenant"):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _seed_user(repositories):
    _, user_repo, _ = repositories
    return await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="skills-user")
    )


async def _seed_membership(repositories, user_id, tenant_id):
    _, _, membership_repo = repositories
    return await membership_repo.create(
        Membership(
            id=_unique("membership"), user_id=user_id, tenant_id=tenant_id, role=UserRole.MEMBER
        )
    )


async def _create_skill_via_api(client, tenant_id, token):
    """Create a Skill through the API and return the created response."""
    return client.post(
        f"/tenants/{tenant_id}/skills",
        headers={"Authorization": f"Bearer {token}"},
        json=_skill_payload(),
    )


class TestSkillRolePermissions:
    """Requirements 1-4: the approved role-to-permission mapping holds at the API."""

    @pytest.mark.parametrize(
        "role",
        [
            ApplicationRole.PLATFORM_ADMINISTRATOR,
            ApplicationRole.COMPANY_ADMINISTRATOR,
        ],
    )
    async def test_administrator_roles_can_create_read_delete(
        self, client, repositories, make_token, authorization_override, role
    ):
        """PLATFORM_ADMINISTRATOR and COMPANY_ADMINISTRATOR may create/read/delete."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: role})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        listed = client.get(f"/tenants/{tenant.id}/skills", headers=headers)
        assert listed.status_code == 200
        assert any(skill["id"] == skill_id for skill in listed.json()["items"])

        fetched = client.get(f"/tenants/{tenant.id}/skills/{skill_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == skill_id

        deleted = client.delete(f"/tenants/{tenant.id}/skills/{skill_id}", headers=headers)
        assert deleted.status_code == 204

        gone = client.get(f"/tenants/{tenant.id}/skills/{skill_id}", headers=headers)
        assert gone.status_code == 404

    async def test_operations_user_can_read_but_not_create_or_delete(
        self, client, repositories, make_token, authorization_override
    ):
        """OPERATIONS_USER may read; create and delete are denied with 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(f"/tenants/{tenant.id}/skills", headers=headers)
        assert response.status_code == 200

        response = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert response.status_code == 403

        response = client.delete(f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers)
        assert response.status_code == 403

    async def test_employee_cannot_create_read_or_delete(
        self, client, repositories, make_token, authorization_override
    ):
        """EMPLOYEE is denied every Skills endpoint with 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get(f"/tenants/{tenant.id}/skills", headers=headers).status_code == 403
        assert (
            client.get(
                f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers
            ).status_code
            == 403
        )


class TestSkillAuthentication:
    """Requirement 5: missing/invalid JWT produces the existing 401 behavior."""

    def test_missing_credentials_are_rejected_on_all_skill_endpoints(self, client):
        """Every Skills endpoint returns 401 without credentials."""
        assert client.get(f"/tenants/{_unique('tenant')}/skills").status_code == 401
        assert (
            client.get(f"/tenants/{_unique('tenant')}/skills/{_unique('skill')}").status_code == 401
        )
        assert (
            client.put(
                f"/tenants/{_unique('tenant')}/skills/{_unique('skill')}",
                json={"name": "Updated"},
            ).status_code
            == 401
        )
        assert (
            client.delete(f"/tenants/{_unique('tenant')}/skills/{_unique('skill')}").status_code
            == 401
        )
        assert (
            client.post(f"/tenants/{_unique('tenant')}/skills", json=_skill_payload()).status_code
            == 401
        )

    def test_malformed_credentials_are_rejected(self, client):
        """A malformed bearer token produces a generic 401."""
        response = client.get(
            f"/tenants/{_unique('tenant')}/skills",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401

    def test_invalid_signature_is_rejected(self, client, wrong_secret_token):
        """A token signed with a different secret produces a generic 401."""
        token = wrong_secret_token("user-1")
        response = client.get(
            f"/tenants/{_unique('tenant')}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


class TestSkillAuthorization:
    """Requirement 6: authentication never grants permission (fail closed)."""

    async def test_authenticated_user_without_role_is_denied(
        self, client, repositories, make_token, authorization_override
    ):
        """A valid JWT with no role assignment is denied with 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/skills", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    async def test_membership_alone_never_grants_skill_permissions(
        self, client, repositories, make_token, authorization_override
    ):
        """A valid membership without an application role never authorizes."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
            json=_skill_payload(),
        )
        assert response.status_code == 403


class TestSkillTenantIsolation:
    """Requirements 7-13: tenant-scoped persistence and cross-tenant non-disclosure."""

    async def test_create_persists_trusted_tenant_id(
        self, client, repositories, make_token, authorization_override
    ):
        """Create persists the trusted tenant ID, not any caller-supplied value."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
            json=_skill_payload(tenant_id="malicious-tenant"),
        )
        assert created.status_code == 200
        assert created.json()["tenant_id"] == tenant.id

        listed = client.get(
            f"/tenants/{tenant.id}/skills", headers={"Authorization": f"Bearer {token}"}
        )
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert len(items) == 1
        assert items[0]["tenant_id"] == tenant.id

    async def test_caller_supplied_tenant_id_cannot_override_trusted_context(
        self, client, repositories, make_token, authorization_override
    ):
        """A tenant the principal is not a member of is denied with 403."""
        tenant_a = await _seed_tenant(repositories, "Tenant A")
        tenant_b = await _seed_tenant(repositories, "Tenant B")
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant_a.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(f"/tenants/{tenant_b.id}/skills", headers=headers)
        assert response.status_code == 403

        response = client.post(
            f"/tenants/{tenant_b.id}/skills", headers=headers, json=_skill_payload()
        )
        assert response.status_code == 403

        response = client.delete(
            f"/tenants/{tenant_b.id}/skills/{_unique('skill')}", headers=headers
        )
        assert response.status_code == 403

    async def test_list_returns_only_current_tenant_skills(
        self, client, repositories, make_token, authorization_override
    ):
        """Listing returns only Skills of the trusted tenant."""
        tenant_a = await _seed_tenant(repositories, "Tenant A")
        tenant_b = await _seed_tenant(repositories, "Tenant B")
        user_a = await _seed_user(repositories)
        user_b = await _seed_user(repositories)
        await _seed_membership(repositories, user_a.id, tenant_a.id)
        await _seed_membership(repositories, user_b.id, tenant_b.id)

        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_a = make_token(user_a.id)
        created_a = await _create_skill_via_api(client, tenant_a.id, token_a)
        assert created_a.status_code == 200

        authorization_override({user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_b = make_token(user_b.id)
        created_b = await _create_skill_via_api(client, tenant_b.id, token_b)
        assert created_b.status_code == 200

        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_a = make_token(user_a.id)
        listed = client.get(
            f"/tenants/{tenant_a.id}/skills", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert listed.status_code == 200
        assert [skill["id"] for skill in listed.json()["items"]] == [created_a.json()["id"]]

    async def test_get_returns_current_tenant_skill(
        self, client, repositories, make_token, authorization_override
    ):
        """Get returns a Skill belonging to the trusted tenant."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert created.status_code == 200

        fetched = client.get(f"/tenants/{tenant.id}/skills/{created.json()['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == created.json()["id"]
        assert fetched.json()["tenant_id"] == tenant.id

    async def test_get_another_tenants_skill_does_not_leak_existence(
        self, client, repositories, make_token, authorization_override
    ):
        """A Skill in another tenant is indistinguishable from a missing Skill."""
        tenant_a = await _seed_tenant(repositories, "Tenant A")
        tenant_b = await _seed_tenant(repositories, "Tenant B")
        user_a = await _seed_user(repositories)
        user_b = await _seed_user(repositories)
        await _seed_membership(repositories, user_a.id, tenant_a.id)
        await _seed_membership(repositories, user_b.id, tenant_b.id)

        authorization_override({user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_b = make_token(user_b.id)
        created_b = await _create_skill_via_api(client, tenant_b.id, token_b)
        assert created_b.status_code == 200

        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_a = make_token(user_a.id)
        response = client.get(
            f"/tenants/{tenant_a.id}/skills/{created_b.json()['id']}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 404

        response = client.get(
            f"/tenants/{tenant_b.id}/skills/{created_b.json()['id']}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 403

    async def test_delete_removes_current_tenant_skill(
        self, client, repositories, make_token, authorization_override
    ):
        """Delete removes a Skill belonging to the trusted tenant."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert created.status_code == 200

        deleted = client.delete(
            f"/tenants/{tenant.id}/skills/{created.json()['id']}", headers=headers
        )
        assert deleted.status_code == 204

        gone = client.get(f"/tenants/{tenant.id}/skills/{created.json()['id']}", headers=headers)
        assert gone.status_code == 404

    async def test_delete_another_tenants_skill_does_not_leak_existence(
        self, client, repositories, make_token, authorization_override
    ):
        """Deleting another tenant's Skill is a no-op that does not reveal existence."""
        tenant_a = await _seed_tenant(repositories, "Tenant A")
        tenant_b = await _seed_tenant(repositories, "Tenant B")
        user_a = await _seed_user(repositories)
        user_b = await _seed_user(repositories)
        await _seed_membership(repositories, user_a.id, tenant_a.id)
        await _seed_membership(repositories, user_b.id, tenant_b.id)

        authorization_override({user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_b = make_token(user_b.id)
        created_b = await _create_skill_via_api(client, tenant_b.id, token_b)
        assert created_b.status_code == 200

        authorization_override({user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_a = make_token(user_a.id)
        deleted = client.delete(
            f"/tenants/{tenant_a.id}/skills/{created_b.json()['id']}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert deleted.status_code == 204

        authorization_override({user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token_b = make_token(user_b.id)
        still_there = client.get(
            f"/tenants/{tenant_b.id}/skills/{created_b.json()['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert still_there.status_code == 200


class TestSkillTenantIdConsistency:
    """The query tenant_id must match the trusted TenantContext.

    The trusted context remains the authoritative tenant boundary; the
    client-supplied ``tenant_id`` is request input only and is explicitly
    validated for consistency against the context (403 on mismatch).
    """

    async def test_matching_query_tenant_succeeds(
        self, client, repositories, make_token, authorization_override
    ):
        """With a matching query tenant_id the trusted boundary is used."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
            json=_skill_payload(),
        )
        assert created.status_code == 200
        assert created.json()["tenant_id"] == tenant.id

    async def test_mismatched_query_tenant_is_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        """Every Skills endpoint rejects a tenant_id diverging from the context."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        # Establish a trusted context for a DIFFERENT tenant than the query.
        mismatched_context = TenantContext(
            tenant_id=_unique("other-tenant"),
            tenant_name="Other Tenant",
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_trusted_tenant_context] = lambda: mismatched_context
        try:
            create = client.post(
                f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
            )
            assert create.status_code == 403

            listing = client.get(f"/tenants/{tenant.id}/skills", headers=headers)
            assert listing.status_code == 403

            fetch = client.get(f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers)
            assert fetch.status_code == 403

            delete = client.delete(
                f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers
            )
            assert delete.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

    async def test_mismatched_query_tenant_cannot_write(
        self, client, repositories, db, make_token, authorization_override
    ):
        """A rejected request persists nothing in either tenant."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
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
                f"/tenants/{tenant.id}/skills",
                headers={"Authorization": f"Bearer {token}"},
                json=_skill_payload(),
            )
            assert create.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

        # The rejected request must not have persisted anything in either tenant.
        from arc.repositories.skills import PostgreSQLSkillRepository

        skill_repo = PostgreSQLSkillRepository(db)
        assert await skill_repo.list_for_tenant(tenant.id) == []
        assert await skill_repo.list_for_tenant(other_tenant_id) == []


class TestSkillNotFound:
    """Requirement 14: missing Skills follow the established 404 behavior."""

    async def test_missing_skill_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        """Get of a missing Skill within the trusted tenant returns 404."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/skills/{_unique('skill')}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestSkillNegativeCases:
    """Comprehensive negative tests for Skills endpoints.

    Covers: unauthenticated, invalid/expired JWT, wrong issuer/audience,
    missing subject, wrong role, missing permission, missing tenant membership,
    cross-tenant access.
    """

    async def test_unauthenticated_requests_rejected_on_all_endpoints(self, client):
        """Every Skills endpoint returns 401 without credentials."""
        tenant_id = _unique("tenant")
        assert client.get(f"/tenants/{tenant_id}/skills").status_code == 401
        assert client.get(f"/tenants/{tenant_id}/skills/{_unique('skill')}").status_code == 401
        assert client.post(f"/tenants/{tenant_id}/skills", json=_skill_payload()).status_code == 401
        assert client.delete(f"/tenants/{tenant_id}/skills/{_unique('skill')}").status_code == 401

    async def test_malformed_credentials_rejected(self, client, repositories):
        """A malformed bearer token produces a generic 401."""
        tenant = await _seed_tenant(repositories)
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401

    async def test_invalid_signature_rejected(self, client, repositories, wrong_secret_token):
        """A token signed with a different secret produces a generic 401."""
        tenant = await _seed_tenant(repositories)
        token = wrong_secret_token("user-1")
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_expired_token_rejected(self, client, repositories, make_token):
        """An expired token must be rejected even though the signature is valid."""
        tenant = await _seed_tenant(repositories)
        token = make_token("user-1", expires_in_seconds=-10)
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_wrong_issuer_rejected(self, client, repositories, make_token):
        """A token with wrong issuer must be rejected."""
        tenant = await _seed_tenant(repositories)
        token = make_token("user-1", issuer="other-issuer")
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_wrong_audience_rejected(self, client, repositories, make_token):
        """A token with wrong audience must be rejected."""
        tenant = await _seed_tenant(repositories)
        token = make_token("user-1", audience="other-audience")
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_missing_subject_rejected(self, client, repositories):
        """A token without a subject claim must be rejected."""
        import jwt as pyjwt

        from arc.security.settings import get_security_settings

        settings = get_security_settings()
        unsigned = pyjwt.encode({}, settings.jwt_secret, algorithm="HS256")
        tenant = await _seed_tenant(repositories)
        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {unsigned}"},
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "endpoint,method",
        [
            ("/tenants/{tenant_id}/skills", "GET"),
            ("/tenants/{tenant_id}/skills/{skill_id}", "GET"),
            ("/tenants/{tenant_id}/skills", "POST"),
            ("/tenants/{tenant_id}/skills/{skill_id}", "PUT"),
            ("/tenants/{tenant_id}/skills/{skill_id}", "DELETE"),
        ],
    )
    async def test_employee_role_denied_on_all_endpoints(
        self, client, repositories, make_token, authorization_override, endpoint, method
    ):
        """EMPLOYEE (no matrix permissions) is denied on all Skills endpoints."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        url = endpoint.format(tenant_id=tenant.id, skill_id=_unique("skill"))
        if method == "POST":
            response = client.post(url, headers=headers, json=_skill_payload())
        elif method == "DELETE":
            response = client.delete(url, headers=headers)
        elif method == "PUT":
            response = client.put(url, headers=headers, json={"name": "X"})
        else:
            response = client.get(url, headers=headers)
        assert response.status_code == 403

    async def test_authenticated_but_unassigned_user_denied(
        self, client, repositories, make_token, authorization_override
    ):
        """A valid JWT with no role assignment is denied with 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_membership_alone_never_grants_skill_permissions(
        self, client, repositories, make_token, authorization_override
    ):
        """A valid membership without an application role never authorizes."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({})
        token = make_token(user.id)

        response = client.post(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
            json=_skill_payload(),
        )
        assert response.status_code == 403

    async def test_operations_user_can_read_but_not_create_or_delete(
        self, client, repositories, make_token, authorization_override
    ):
        """OPERATIONS_USER may read; create and delete are denied with 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(f"/tenants/{tenant.id}/skills", headers=headers)
        assert response.status_code == 200

        response = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert response.status_code == 403

        response = client.delete(f"/tenants/{tenant.id}/skills/{_unique('skill')}", headers=headers)
        assert response.status_code == 403

    async def test_missing_tenant_membership_denied(
        self, client, repositories, make_token, authorization_override
    ):
        """A user without membership in the tenant is denied (403)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        # No membership created
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_cross_tenant_access_denied(
        self, client, repositories, make_token, authorization_override
    ):
        """A tenant member must not access another tenant they do not belong to."""
        tenant_a = await _seed_tenant(repositories, "Tenant A")
        tenant_b = await _seed_tenant(repositories, "Tenant B")
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant_a.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(f"/tenants/{tenant_b.id}/skills", headers=headers)
        assert response.status_code == 403

        response = client.post(
            f"/tenants/{tenant_b.id}/skills", headers=headers, json=_skill_payload()
        )
        assert response.status_code == 403

        response = client.delete(
            f"/tenants/{tenant_b.id}/skills/{_unique('skill')}", headers=headers
        )
        assert response.status_code == 403

    async def test_missing_tenant_is_denied_no_leakage(
        self, client, repositories, make_token, authorization_override
    ):
        """A nonexistent tenant must be denied: no data leakage about existence."""
        _, user, _ = await _seed_tenant(repositories), await _seed_user(repositories), None
        # Need to recreate properly
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{_unique('missing')}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403


class TestSkillDuplicateCreation:
    """Issue #62: duplicate Skill creation must return 409 Conflict.

    Creating a Skill with the same name and version within the same
    tenant violates the database unique constraint. The controller
    must return a safe, descriptive 409 response without exposing
    internal database details or tenant identifiers.
    """

    async def test_duplicate_skill_returns_409(
        self, client, repositories, make_token, authorization_override
    ):
        """Creating a Skill with the same name/version returns 409."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        payload = _skill_payload(name="test-skill", version="1")

        r1 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        assert r1.status_code == 200

        r2 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        assert r2.status_code == 409

    async def test_duplicate_skill_error_message_is_descriptive(
        self, client, repositories, make_token, authorization_override
    ):
        """The 409 response contains a safe, descriptive message."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        payload = _skill_payload(name="deploy-pipeline", version="2")

        client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        r2 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        assert r2.status_code == 409

        body = r2.json()
        detail = body["detail"]
        assert "deploy-pipeline" in detail
        assert "2" in detail
        assert "already exists in this tenant" in detail

    async def test_duplicate_skill_error_excludes_tenant_id(
        self, client, repositories, make_token, authorization_override
    ):
        """The 409 response does not expose the internal tenant_id."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        payload = _skill_payload(name="secret-skill", version="1")

        client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        r2 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        assert r2.status_code == 409

        detail = r2.json()["detail"]
        assert tenant.id not in detail

    async def test_duplicate_skill_error_excludes_database_details(
        self, client, repositories, make_token, authorization_override
    ):
        """The 409 response does not expose database internals."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        payload = _skill_payload(name="internal-skill", version="3")

        client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        r2 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        assert r2.status_code == 409

        detail = r2.json()["detail"].lower()
        assert "unique" not in detail
        assert "constraint" not in detail
        assert "asyncpg" not in detail

    async def test_original_skill_is_preserved_after_duplicate(
        self, client, repositories, make_token, authorization_override
    ):
        """The first Skill is unaffected by a duplicate creation attempt."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        payload = _skill_payload(name="stable-skill", version="1")

        r1 = client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)
        original_id = r1.json()["id"]

        client.post(f"/tenants/{tenant.id}/skills", headers=headers, json=payload)

        fetched = client.get(f"/tenants/{tenant.id}/skills/{original_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "stable-skill"


class TestSkillUpdate:
    """PUT /tenants/{tenant_id}/skills/{skill_id} endpoint tests."""

    async def test_update_skill_succeeds(
        self, client, repositories, make_token, authorization_override
    ):
        """A valid update returns 200 with the updated Skill."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        updated = client.put(
            f"/tenants/{tenant.id}/skills/{skill_id}",
            headers=headers,
            json={"name": "Updated Skill", "purpose": "Updated purpose"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Updated Skill"
        assert updated.json()["purpose"] == "Updated purpose"
        assert updated.json()["id"] == skill_id

    async def test_update_skill_preserves_unmodified_fields(
        self, client, repositories, make_token, authorization_override
    ):
        """Fields not provided in the update body are preserved."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(name="Original", purpose="Original purpose", version="3"),
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        updated = client.put(
            f"/tenants/{tenant.id}/skills/{skill_id}",
            headers=headers,
            json={"name": "Updated"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Updated"
        assert updated.json()["purpose"] == "Original purpose"
        assert updated.json()["version"] == "3"

    async def test_update_skill_returns_404_for_missing_skill(
        self, client, repositories, make_token, authorization_override
    ):
        """Updating a nonexistent Skill within the trusted tenant returns 404."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.put(
            f"/tenants/{tenant.id}/skills/{_unique('skill')}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Updated"},
        )
        assert response.status_code == 404

    async def test_update_skill_returns_403_for_unauthorized_user(
        self, client, repositories, make_token, authorization_override
    ):
        """OPERATIONS_USER cannot update Skills (no skill:update permission)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.put(
            f"/tenants/{tenant.id}/skills/{_unique('skill')}",
            headers=headers,
            json={"name": "Updated"},
        )
        assert response.status_code == 403

    async def test_update_skill_returns_403_for_employee(
        self, client, repositories, make_token, authorization_override
    ):
        """EMPLOYEE cannot update Skills."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.EMPLOYEE})
        token = make_token(user.id)

        response = client.put(
            f"/tenants/{tenant.id}/skills/{_unique('skill')}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Updated"},
        )
        assert response.status_code == 403

    async def test_update_skill_returns_403_for_mismatched_tenant(
        self, client, repositories, make_token, authorization_override
    ):
        """A tenant_id mismatch between path and trusted context returns 403."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills", headers=headers, json=_skill_payload()
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        mismatched_context = TenantContext(
            tenant_id=_unique("other-tenant"),
            tenant_name="Other Tenant",
            user_id=user.id,
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_trusted_tenant_context] = lambda: mismatched_context
        try:
            response = client.put(
                f"/tenants/{tenant.id}/skills/{skill_id}",
                headers=headers,
                json={"name": "Hacked"},
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_trusted_tenant_context, None)

    async def test_update_skill_returns_401_without_credentials(self, client):
        """PUT /tenants/{tenant_id}/skills/{skill_id} returns 401 without credentials."""
        response = client.put(
            f"/tenants/{_unique('tenant')}/skills/{_unique('skill')}",
            json={"name": "Updated"},
        )
        assert response.status_code == 401


class TestSkillRiskField:
    """Tests for the Skill risk field (Final PRD §11 Skill Model)."""

    async def test_create_skill_with_risk(
        self, client, repositories, make_token, authorization_override
    ):
        """Creating a Skill with a risk field persists it."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(risk="high"),
        )
        assert created.status_code == 200
        assert created.json()["risk"] == "high"

    async def test_create_skill_without_risk(
        self, client, repositories, make_token, authorization_override
    ):
        """Creating a Skill without risk field defaults to null."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(),
        )
        assert created.status_code == 200
        assert created.json()["risk"] is None

    async def test_update_skill_risk(
        self, client, repositories, make_token, authorization_override
    ):
        """Updating a Skill's risk field persists the change."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(),
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        updated = client.put(
            f"/tenants/{tenant.id}/skills/{skill_id}",
            headers=headers,
            json={"risk": "medium"},
        )
        assert updated.status_code == 200
        assert updated.json()["risk"] == "medium"

    async def test_create_skill_with_invalid_risk_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        """Creating a Skill with an invalid risk value returns 400."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(risk="critical"),
        )
        assert response.status_code == 422
        assert any("risk" in error["loc"] for error in response.json()["detail"])

    async def test_update_skill_with_invalid_risk_rejected(
        self, client, repositories, make_token, authorization_override
    ):
        """Updating a Skill with an invalid risk value returns 400."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            f"/tenants/{tenant.id}/skills",
            headers=headers,
            json=_skill_payload(),
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        response = client.put(
            f"/tenants/{tenant.id}/skills/{skill_id}",
            headers=headers,
            json={"risk": "invalid"},
        )
        assert response.status_code == 422
        assert any("risk" in error["loc"] for error in response.json()["detail"])


class TestSkillRouteSurface:
    """Requirement 15: the API surface contains exactly the intended endpoints."""

    def test_skills_route_surface_is_exactly_the_intended_endpoints(self):
        """Only the approved Skills management and execution routes are exposed."""
        from arc.api.controllers import api_router

        paths = {
            f"{method} {route.path}"
            for route in api_router.routes
            if hasattr(route, "methods") and hasattr(route, "path")
            for method in route.methods
            if method in HTTP_METHODS
        }
        skills_paths = {path for path in paths if "/skills" in path}
        assert skills_paths == {
            "POST /tenants/{tenant_id}/skills",
            "GET /tenants/{tenant_id}/skills",
            "GET /tenants/{tenant_id}/skills/{skill_id}",
            "PUT /tenants/{tenant_id}/skills/{skill_id}",
            "DELETE /tenants/{tenant_id}/skills/{skill_id}",
            "POST /tenants/{tenant_id}/skills/{skill_id}/execute",
            "POST /tenants/{tenant_id}/skills/{skill_id}/resume",
        }


class TestSkillsTenantPathContract:
    """Issue #242: tenant-scoped skills live under /tenants/{tenant_id}/skills."""

    async def test_old_query_scoped_route_is_gone(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /skills?tenant_id=... no longer matches any route (404)."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/skills?tenant_id={tenant.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_missing_tenant_segment_has_no_duplicate_validation_error(
        self, client, repositories, make_token, authorization_override
    ):
        """GET /skills matches nothing: 404, not a duplicated 422 tenant_id error."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get("/skills", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 404
        assert "Field required" not in response.text

    async def test_successful_list_is_attributed_to_tenant(
        self, client, db, repositories, make_token, authorization_override
    ):
        """Telemetry records the resolved tenant for the path-scoped route."""
        tenant = await _seed_tenant(repositories)
        user = await _seed_user(repositories)
        await _seed_membership(repositories, user.id, tenant.id)
        authorization_override({user.id: ApplicationRole.COMPANY_ADMINISTRATOR})
        token = make_token(user.id)

        response = client.get(
            f"/tenants/{tenant.id}/skills",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        request_id = response.headers["x-request-id"]

        async with db._connection_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tenant_id, route_template FROM api_request_records WHERE request_id = $1",
                request_id,
            )
        assert row is not None
        assert row["tenant_id"] == tenant.id
        assert row["route_template"] == "/tenants/{tenant_id}/skills"
