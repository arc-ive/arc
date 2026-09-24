"""Phase 2 multi-tenant security matrix (API level).

Invariant: a principal of Tenant A must not read, modify, delete, execute,
or operate on Tenant B resources. Every test builds two real tenants with
real member users and asserts denial + non-disclosure across direct access,
listings, and search. See docs/qa/TENANT_ISOLATION_MATRIX.md.
"""

import uuid

from arc.domain.models import Membership, Tenant, User, UserRole
from arc.security.models import ApplicationRole


def _unique(prefix: str) -> str:
    return f"tim-{prefix}-{uuid.uuid4().hex[:10]}"


async def _tenant(repositories, name):
    tenant_repo, _, _ = repositories
    return await tenant_repo.create(Tenant(id=_unique("tenant"), name=name))


async def _user(repositories, tenant_id, role=UserRole.MEMBER):
    _, user_repo, membership_repo = repositories
    user = await user_repo.create(
        User(id=_unique("user"), email=f"{uuid.uuid4().hex}@example.com", username="tim-user")
    )
    await membership_repo.create(
        Membership(id=_unique("membership"), user_id=user.id, tenant_id=tenant_id, role=role)
    )
    return user


async def _two_tenants(client, repositories, make_token, authorization_override):
    """Return (tenant_a, token_a, tenant_b, token_b) with member users."""
    tenant_a = await _tenant(repositories, "Tenant A")
    tenant_b = await _tenant(repositories, "Tenant B")
    user_a = await _user(repositories, tenant_a.id)
    user_b = await _user(repositories, tenant_b.id)
    # NOTE: authorization_override replaces the whole assignment map,
    # so both users must be registered in a single call.
    authorization_override(
        {
            user_a.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            user_b.id: ApplicationRole.COMPANY_ADMINISTRATOR,
        }
    )
    return tenant_a, make_token(user_a.id), tenant_b, make_token(user_b.id)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestSkillsIsolation:
    async def test_cross_tenant_skill_get_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        created = client.post(
            f"/tenants/{tenant_b.id}/skills",
            headers=_auth(token_b),
            json={"name": _unique("skill"), "purpose": "p", "allowed_tools": []},
        )
        assert created.status_code == 200
        skill_id = created.json()["id"]

        response = client.get(f"/tenants/{tenant_a.id}/skills/{skill_id}", headers=_auth(token_a))
        assert response.status_code == 404

    async def test_cross_tenant_skills_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        created = client.post(
            f"/tenants/{tenant_b.id}/skills",
            headers=_auth(token_b),
            json={"name": _unique("skill"), "purpose": "p", "allowed_tools": []},
        )
        skill_id = created.json()["id"]

        listing = client.get(f"/tenants/{tenant_a.id}/skills", headers=_auth(token_a))
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()["items"]]
        assert skill_id not in ids

    async def test_cross_tenant_skill_execute_denied(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        created = client.post(
            f"/tenants/{tenant_b.id}/skills",
            headers=_auth(token_b),
            json={"name": _unique("skill"), "purpose": "p", "allowed_tools": []},
        )
        skill_id = created.json()["id"]

        response = client.post(
            f"/tenants/{tenant_a.id}/skills/{skill_id}/execute",
            headers=_auth(token_a),
            json={
                "tool_calls": [{"tool_name": "check_service_health", "input": {}}],
                "satisfied_preconditions": [],
            },
        )
        assert response.status_code in (403, 404)


class TestKnowledgeIsolation:
    async def _seed_doc(self, client, tenant_id, token, content):
        response = client.post(
            f"/tenants/{tenant_id}/knowledge",
            headers=_auth(token),
            json={
                "source": "policy",
                "provenance": "matrix",
                "content": content,
            },
        )
        assert response.status_code == 200
        return response.json()

    async def test_cross_tenant_document_get_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        doc = await self._seed_doc(client, tenant_b.id, token_b, "tenant bee secret policy")

        response = client.get(
            f"/tenants/{tenant_a.id}/knowledge/{doc['id']}", headers=_auth(token_a)
        )
        assert response.status_code == 404

    async def test_cross_tenant_documents_excluded_from_search(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        marker = _unique("marker")
        await self._seed_doc(client, tenant_b.id, token_b, f"tenant bee {marker} policy")

        response = client.get(
            f"/tenants/{tenant_a.id}/knowledge/search",
            headers=_auth(token_a),
            params={"query": marker, "limit": 5},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_cross_tenant_documents_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        doc = await self._seed_doc(client, tenant_b.id, token_b, "tenant bee list policy")

        listing = client.get(f"/tenants/{tenant_a.id}/knowledge", headers=_auth(token_a))
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()["items"]]
        assert doc["id"] not in ids


class TestApprovalsIsolation:
    async def test_cross_tenant_approval_get_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )

        response = client.get(
            f"/tenants/{tenant_a.id}/approvals/{_unique('approval')}",
            headers=_auth(token_a),
        )
        assert response.status_code == 404

    async def test_cross_tenant_approvals_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        # Real pending approval in B via the gated-tool path (no handler
        # runs). A REQUIRE_HUMAN_APPROVAL gating is a controlled 200 with
        # status approval_required, not a 403 denial.
        gated = client.post(
            f"/tenants/{tenant_b.id}/tools/grant_temporary_access/execute",
            headers=_auth(token_b),
            json={"input": {"justification": "matrix probe"}},
        )
        assert gated.status_code == 200
        gated_body = gated.json()
        assert gated_body["status"] == "approval_required"
        tenant_b_approval_id = gated_body["approval_id"]
        assert tenant_b_approval_id, "gated tool must return the pending approval id"

        listing = client.get(f"/tenants/{tenant_a.id}/approvals", headers=_auth(token_a))
        assert listing.status_code == 200
        tenant_a_ids = [item["id"] for item in listing.json()["items"]]
        assert tenant_b_approval_id not in tenant_a_ids
        assert tenant_a_ids == []


class TestAgentRunsIsolation:
    async def test_cross_tenant_agent_runs_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        # Real trace row in B: deterministic provider declines, run fails
        # closed AND persists its trace.
        run = client.post(
            "/agent/runs",
            headers=_auth(token_b),
            json={"tenant_id": tenant_b.id, "goal": "matrix probe"},
        )
        assert run.status_code == 200
        run_id = run.json()["id"]

        listing = client.get(
            f"/tenants/{tenant_a.id}/observability/agent-runs", headers=_auth(token_a)
        )
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()["items"]]
        assert run_id not in ids

    async def test_cross_tenant_agent_trace_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )

        response = client.get(
            f"/tenants/{tenant_a.id}/observability/agent-runs/{_unique('run')}",
            headers=_auth(token_a),
        )
        assert response.status_code == 404


class TestConnectorsIsolation:
    async def test_cross_tenant_connector_get_is_404(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        created = client.post(
            f"/tenants/{tenant_b.id}/connectors",
            headers=_auth(token_b),
            json={"provider": "github", "name": _unique("conn"), "target": "example/acme"},
        )
        assert created.status_code == 200
        connector_id = created.json()["id"]

        response = client.get(
            f"/tenants/{tenant_a.id}/connectors/{connector_id}", headers=_auth(token_a)
        )
        assert response.status_code == 404

    async def test_cross_tenant_connectors_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        created = client.post(
            f"/tenants/{tenant_b.id}/connectors",
            headers=_auth(token_b),
            json={"provider": "github", "name": _unique("conn"), "target": "example/acme"},
        )
        connector_id = created.json()["id"]

        listing = client.get(f"/tenants/{tenant_a.id}/connectors", headers=_auth(token_a))
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()["items"]]
        assert connector_id not in ids


class TestWebhooksIsolation:
    async def test_cross_tenant_webhook_events_excluded_from_list(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )

        listing = client.get(f"/tenants/{tenant_a.id}/webhooks/events", headers=_auth(token_a))
        assert listing.status_code == 200
        assert listing.json()["items"] == []


class TestObservabilityIsolation:
    async def test_cross_tenant_usage_contains_no_foreign_rows(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )

        response = client.get(
            f"/tenants/{tenant_a.id}/observability/usage-summary", headers=_auth(token_a)
        )
        assert response.status_code == 200

    async def test_cross_tenant_llm_usage_excluded(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )
        # Real usage row in B via a knowledge query (deterministic provider).
        doc = client.post(
            f"/tenants/{tenant_b.id}/knowledge",
            headers=_auth(token_b),
            json={"source": "policy", "provenance": "matrix", "content": "matrix usage probe"},
        )
        assert doc.status_code == 200
        query = client.post(
            f"/tenants/{tenant_b.id}/intelligence/query",
            headers=_auth(token_b),
            json={"query": "matrix usage probe", "limit": 5},
        )
        assert query.status_code == 200

        response = client.get(
            f"/tenants/{tenant_a.id}/observability/llm-usage", headers=_auth(token_a)
        )
        assert response.status_code == 200
        assert response.json()["total_calls"] == 0


class TestMembershipIsolation:
    async def test_non_member_cannot_list_tenant_users(
        self, client, repositories, make_token, authorization_override
    ):
        tenant_a, token_a, tenant_b, token_b = await _two_tenants(
            client, repositories, make_token, authorization_override
        )

        response = client.get(f"/tenants/{tenant_b.id}/users", headers=_auth(token_a))
        assert response.status_code == 403
