"""End-to-end test of Arc's first external action (ADR-013, Issue #304).

`AGENT_TOOLS.md` recorded that Arc could do nothing externally: every
connector adapter implemented ``fetch`` and nothing else, so "post to a
channel" had no path at any layer. This exercises the path that now
exists, through the real chain:

    ToolExecutionService (authorization, policy, approval, audit)
        -> post_channel_message tool
        -> ExternalActionService (capability, destination, act credential)
        -> Slack adapter

with real PostgreSQL for approvals, credentials, connectors and audit
records, a real ``EncryptionService``, and the deterministic fake provider
standing in for exactly one thing: the network. Everything Arc decides is
the real code.

Every test asserts what the fake provider RECORDED, not only what the
service returned. For an action tool the side effect is the deliverable,
so a test that checks the return value alone would not notice a message
that was posted twice, or posted when it should not have been.
"""

import uuid

import pytest

from arc.domain.models import (
    ApprovalStatus,
    ConnectorConfig,
    ConnectorProvider,
    ConnectorStatus,
    CredentialScope,
    Tenant,
    TenantContext,
    UserRole,
)
from arc.repositories.approvals import PostgreSQLApprovalRequestRepository
from arc.repositories.connector_credentials import PostgreSQLConnectorCredentialRepository
from arc.repositories.connectors import PostgreSQLConnectorRepository
from arc.repositories.tenancy import PostgreSQLTenantRepository
from arc.repositories.tools import PostgreSQLToolExecutionRepository
from arc.security.authorization import AuthorizationService
from arc.security.encryption import EncryptionService
from arc.security.models import ApplicationRole, AuthenticatedPrincipal
from arc.services.approvals import HumanApprovalService
from arc.services.connector_credentials import ConnectorCredentialService
from arc.services.connector_providers.fake import FakeSlackProvider
from arc.services.connector_providers.registry import ProviderRegistry
from arc.services.external_actions import ExternalActionService
from arc.services.tools import (
    ToolDeniedError,
    ToolExecutionError,
    ToolExecutionService,
    build_platform_tool_registry,
)

TOOL = "post_channel_message"
CHANNEL = "ops"
MESSAGE = "Deploy 4.2 finished. No rollbacks."


def _unique(prefix: str) -> str:
    return f"extact-{prefix}-{uuid.uuid4().hex[:8]}"


def _context(tenant_id: str, user_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="External Action Tenant",
        user_id=user_id,
        role=UserRole.MEMBER,
    )


def _authorization(**assignments) -> AuthorizationService:
    return AuthorizationService(assignments)


class _AlwaysEnabled:
    async def is_enabled(self, tenant_id, capability_id):
        return True


class _Harness:
    """The whole chain, assembled the way the application assembles it."""

    def __init__(self, tenant, requester, approver, slack, tool_svc, approval_svc, tool_repo):
        self.tenant = tenant
        self.requester = requester
        self.approver = approver
        self.slack = slack
        self.tool_svc = tool_svc
        self.approval_svc = approval_svc
        self.tool_repo = tool_repo

    @property
    def context(self):
        return _context(self.tenant.id, self.requester)

    @property
    def principal(self):
        return AuthenticatedPrincipal(user_id=self.requester)

    @property
    def authorization(self):
        return _authorization(
            **{
                self.requester: ApplicationRole.OPERATIONS_USER,
                self.approver: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )

    async def request(self, channel=CHANNEL, message=MESSAGE):
        """Attempt the action; returns the approval id the gate created."""
        with pytest.raises(ToolDeniedError) as exc:
            await self.tool_svc.execute_tool(
                self.context,
                self.principal,
                TOOL,
                {"channel": channel, "message": message},
                self.authorization,
            )
        return exc.value.approval_id

    async def approve(self, approval_id):
        return await self.approval_svc.decide_request(
            self.context,
            self.approver,
            approval_id,
            ApprovalStatus.APPROVED,
        )

    async def resume(self, approval_id, channel=CHANNEL, message=MESSAGE):
        """Spend the approval at the service boundary.

        The service contract takes the arguments and re-validates them
        against the approval's digest. (The HTTP layer additionally reads
        the encrypted approved arguments so the browser sends none; that
        path is covered in ``TestThroughTheApi`` below.)
        """
        return await self.tool_svc.execute_tool(
            self.context,
            self.principal,
            TOOL,
            {"channel": channel, "message": message},
            self.authorization,
            approval_id=approval_id,
        )


@pytest.fixture
async def harness(db):
    """A tenant with an ACTIVE Slack connector and an ACT credential."""
    tenants = PostgreSQLTenantRepository(db)
    connectors = PostgreSQLConnectorRepository(db)
    credentials = PostgreSQLConnectorCredentialRepository(db)

    tenant = await tenants.create(Tenant(id=_unique("tenant"), name="Acting Tenant"))
    requester = _unique("requester")
    approver = _unique("approver")

    await connectors.create(
        ConnectorConfig(
            id=_unique("conn"),
            tenant_id=tenant.id,
            provider=ConnectorProvider.SLACK,
            name="slack-ops",
            target=CHANNEL,
            status=ConnectorStatus.ACTIVE,
        )
    )

    encryption = EncryptionService(key=b"\x07" * 32, key_version=1)
    credential_service = ConnectorCredentialService(credentials, encryption)
    await credential_service.create_credential(
        _context(tenant.id, requester),
        ConnectorProvider.SLACK,
        "xoxb-act-token",
        CredentialScope.ACT,
    )

    slack = FakeSlackProvider()
    external_actions = ExternalActionService(
        connector_repo=connectors,
        provider_registry=ProviderRegistry({ConnectorProvider.SLACK: slack}),
        credential_service=credential_service,
        capability_service=_AlwaysEnabled(),
    )

    approval_svc = HumanApprovalService(PostgreSQLApprovalRequestRepository(db))
    tool_repo = PostgreSQLToolExecutionRepository(db)
    tool_svc = ToolExecutionService(
        registry=build_platform_tool_registry(),
        record_repo=tool_repo,
        approval_service=approval_svc,
        capability_service=None,
        encryption_service=encryption,
        external_action_service=external_actions,
    )

    yield _Harness(tenant, requester, approver, slack, tool_svc, approval_svc, tool_repo)

    await tenants.delete(tenant.id)


class TestTheApprovedPath:
    async def test_the_attempt_alone_posts_nothing(self, harness):
        """The gate is not advisory: nothing is sent before a human decides."""
        approval_id = await harness.request()

        assert approval_id is not None
        assert harness.slack.posted == []
        pending = await harness.approval_svc.get_request(harness.context, approval_id)
        assert pending.status == ApprovalStatus.PENDING
        assert pending.tool_name == TOOL

    async def test_approval_alone_still_posts_nothing(self, harness):
        """Approving authorises the action; it does not perform it (ADR-012)."""
        approval_id = await harness.request()

        await harness.approve(approval_id)

        assert harness.slack.posted == []

    async def test_the_requester_spends_the_approval_and_the_message_is_sent(self, harness):
        approval_id = await harness.request()
        await harness.approve(approval_id)

        result = await harness.resume(approval_id)

        assert harness.slack.posted == [(CHANNEL, MESSAGE)]
        assert result.output["channel"] == CHANNEL
        assert result.output["provider"] == "slack"
        assert result.output["reference"]
        assert result.output["tenant_id"] == harness.tenant.id

    async def test_the_message_posted_is_the_message_that_was_approved(self, harness):
        """Editing the text after approval is refused, not quietly posted.

        The approval binds a digest of the validated arguments (ADR-005),
        so the approver's decision covers this exact message and no other.
        """
        approval_id = await harness.request(message="Original text")
        await harness.approve(approval_id)

        with pytest.raises(Exception):
            await harness.resume(approval_id, message="Something else entirely")
        assert harness.slack.posted == []

        await harness.resume(approval_id, message="Original text")
        assert harness.slack.posted == [(CHANNEL, "Original text")]

    async def test_the_channel_cannot_be_changed_after_approval(self, harness):
        """The approver decided WHERE as well as what."""
        approval_id = await harness.request()
        await harness.approve(approval_id)

        with pytest.raises(Exception):
            await harness.resume(approval_id, channel="finance")

        assert harness.slack.posted == []

    async def test_a_second_resume_cannot_post_the_message_twice(self, harness):
        """Single-use approval IS the idempotency guarantee for an action."""
        approval_id = await harness.request()
        await harness.approve(approval_id)
        await harness.resume(approval_id)

        with pytest.raises(Exception):
            await harness.resume(approval_id)

        assert harness.slack.posted == [(CHANNEL, MESSAGE)]


class TestRefusals:
    async def test_a_rejected_request_never_posts(self, harness):
        approval_id = await harness.request()
        await harness.approval_svc.decide_request(
            harness.context, harness.approver, approval_id, ApprovalStatus.REJECTED
        )

        with pytest.raises(Exception):
            await harness.resume(approval_id)

        assert harness.slack.posted == []

    async def test_a_caller_holding_tool_execute_but_not_connector_act_is_denied(self, harness):
        """``tool:execute`` is not enough: the tool declares ``connector:act``.

        WEBHOOK_PROCESSOR is the role that makes this test mean something:
        it is the only one holding ``tool:execute`` WITHOUT
        ``connector:act``, so the denial can only come from the permission
        this tool added. A role lacking ``tool:execute`` would be refused
        either way and would prove nothing.
        """
        actor = _unique("webhook")
        authorization = _authorization(**{actor: ApplicationRole.WEBHOOK_PROCESSOR})
        from arc.security.authorization import (
            CONNECTOR_ACT,
            ROLE_PERMISSIONS,
            TOOL_EXECUTE,
        )

        assert TOOL_EXECUTE in ROLE_PERMISSIONS[ApplicationRole.WEBHOOK_PROCESSOR]
        assert CONNECTOR_ACT not in ROLE_PERMISSIONS[ApplicationRole.WEBHOOK_PROCESSOR]

        with pytest.raises(ToolDeniedError):
            await harness.tool_svc.execute_tool(
                _context(harness.tenant.id, actor),
                AuthenticatedPrincipal(user_id=actor),
                TOOL,
                {"channel": CHANNEL, "message": MESSAGE},
                authorization,
            )

        assert harness.slack.posted == []
        # And the denial is recorded as a denial, not as a policy stop.
        records = await harness.tool_repo.list_for_tenant(harness.tenant.id)
        denied = [r for r in records if r.user_id == actor]
        assert denied and denied[0].error_kind == "authorization_denied"

    async def test_an_employee_cannot_reach_the_action_through_agent(self, harness):
        """EMPLOYEE holds agent:execute but neither tool permission."""
        employee = _unique("employee")
        authorization = _authorization(**{employee: ApplicationRole.EMPLOYEE})

        with pytest.raises(ToolDeniedError):
            await harness.tool_svc.execute_tool(
                _context(harness.tenant.id, employee),
                AuthenticatedPrincipal(user_id=employee),
                TOOL,
                {"channel": CHANNEL, "message": MESSAGE},
                authorization,
            )

        assert harness.slack.posted == []

    async def test_a_destination_nobody_configured_is_refused_after_approval(self, harness):
        """The destination check is not a UI nicety; it runs at execution."""
        approval_id = await harness.request(channel="finance")
        await harness.approve(approval_id)

        with pytest.raises(ToolExecutionError):
            await harness.resume(approval_id, channel="finance")

        assert harness.slack.posted == []

    async def test_a_failed_action_burns_the_approval_rather_than_retrying_blind(self, harness):
        """Documented consequence of consuming before the handler runs.

        The approval is single-use and is consumed BEFORE the action is
        attempted, so a provider failure leaves the approval spent. That
        direction is deliberate: it can cost a re-request, and it can
        never cost a duplicate message.
        """
        approval_id = await harness.request(channel="finance")
        await harness.approve(approval_id)
        with pytest.raises(ToolExecutionError):
            await harness.resume(approval_id, channel="finance")

        spent = await harness.approval_svc.get_request(harness.context, approval_id)
        assert spent.status == ApprovalStatus.CONSUMED
        assert harness.slack.posted == []

    async def test_an_unwired_action_boundary_fails_closed(self, db, harness):
        """A registry built without the boundary must not look successful."""
        unwired = ToolExecutionService(
            registry=build_platform_tool_registry(),
            record_repo=harness.tool_repo,
            approval_service=harness.approval_svc,
            capability_service=None,
            encryption_service=EncryptionService(key=b"\x07" * 32, key_version=1),
            external_action_service=None,
        )
        approval_id = await harness.request()
        await harness.approve(approval_id)

        with pytest.raises(ToolExecutionError):
            await unwired.execute_tool(
                harness.context,
                harness.principal,
                TOOL,
                {"channel": CHANNEL, "message": MESSAGE},
                harness.authorization,
                approval_id=approval_id,
            )

        assert harness.slack.posted == []


class TestAudit:
    async def test_the_successful_action_is_recorded(self, harness):
        approval_id = await harness.request()
        await harness.approve(approval_id)
        await harness.resume(approval_id)

        records = await harness.tool_repo.list_for_tenant(harness.tenant.id)
        successes = [r for r in records if r.tool_name == TOOL and r.status.value == "success"]
        assert len(successes) == 1

    async def test_the_audit_record_carries_no_message_body_verbatim_secret(self, harness):
        """Summaries only (TRD 14.2); the act token never appears anywhere."""
        approval_id = await harness.request()
        await harness.approve(approval_id)
        await harness.resume(approval_id)

        records = await harness.tool_repo.list_for_tenant(harness.tenant.id)
        serialized = " ".join(f"{r.input_summary} {r.output_summary or ''}" for r in records)
        assert "xoxb-act-token" not in serialized


class TestThroughTheApi:
    """The product path, over HTTP, with the application's own wiring.

    The class above assembles the chain itself. This one uses the services
    the application container built at startup -- including the controller
    resume path, which reads the encrypted approved arguments so the
    browser sends none. That is the only place "Run it now" can be proved
    to work for an action tool.

    In simulated provider mode (the default, TRD 33) the app's Slack
    adapter is the deterministic fake, so the assertion is the same one
    that matters everywhere else: what did it record.
    """

    @staticmethod
    def _app_slack():
        """The fake Slack adapter the running application is wired to."""
        from arc.api.controllers import app_context

        service = app_context.services.get("external_action_service")
        assert service is not None, (
            "the application should wire ExternalActionService when "
            "CONNECTOR_ENCRYPTION_KEY is configured"
        )
        adapter = service._registry.get(ConnectorProvider.SLACK)
        assert isinstance(adapter, FakeSlackProvider), (
            "this test requires simulated provider mode so nothing leaves the process"
        )
        adapter.posted.clear()
        return adapter

    @staticmethod
    async def _tenant_with_connector(db, repositories):
        tenant_repo, user_repo, membership_repo = repositories
        from arc.domain.models import Membership, User

        tenant = await tenant_repo.create(Tenant(id=_unique("tenant"), name="API Acting Tenant"))
        requester = await user_repo.create(
            User(
                id=_unique("requester"),
                email=f"{uuid.uuid4().hex}@example.com",
                username="act-requester",
            )
        )
        approver = await user_repo.create(
            User(
                id=_unique("approver"),
                email=f"{uuid.uuid4().hex}@example.com",
                username="act-approver",
            )
        )
        for user in (requester, approver):
            await membership_repo.create(
                Membership(
                    id=_unique("membership"),
                    user_id=user.id,
                    tenant_id=tenant.id,
                    role=UserRole.MEMBER,
                )
            )

        await PostgreSQLConnectorRepository(db).create(
            ConnectorConfig(
                id=_unique("conn"),
                tenant_id=tenant.id,
                provider=ConnectorProvider.SLACK,
                name="slack-ops",
                target=CHANNEL,
                status=ConnectorStatus.ACTIVE,
            )
        )
        return tenant, requester, approver

    async def test_request_approve_and_run_it_now(
        self, client, db, repositories, make_token, authorization_override
    ):
        slack = self._app_slack()
        tenant, requester, approver = await self._tenant_with_connector(db, repositories)
        authorization_override(
            {
                requester.id: ApplicationRole.OPERATIONS_USER,
                approver.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )
        requester_token = make_token(requester.id)
        approver_token = make_token(approver.id)
        headers = {"Authorization": f"Bearer {requester_token}"}

        # The act credential, stored through the real endpoint.
        stored = client.post(
            f"/tenants/{tenant.id}/connectors/credentials/slack?scope=act",
            headers={"Authorization": f"Bearer {approver_token}"},
            json={"credential": "xoxb-api-act-token"},
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["scope"] == "act"

        # 1. Attempting the action files an approval and posts nothing.
        attempt = client.post(
            f"/tenants/{tenant.id}/tools/{TOOL}/execute",
            headers=headers,
            json={"input": {"channel": CHANNEL, "message": MESSAGE}},
        )
        assert attempt.status_code == 200, attempt.text
        assert attempt.json()["status"] == "approval_required"
        approval_id = attempt.json()["approval_id"]
        assert approval_id
        assert slack.posted == []

        # 2. Someone else approves it (four-eyes).
        decision = client.post(
            f"/tenants/{tenant.id}/approvals/{approval_id}/decisions",
            headers={"Authorization": f"Bearer {approver_token}"},
            json={"decision": "approve"},
        )
        assert decision.status_code == 200, decision.text
        assert slack.posted == []

        # 3. "Run it now": the requester spends it, sending NO arguments.
        run = client.post(
            f"/tenants/{tenant.id}/tools/{TOOL}/execute",
            headers=headers,
            json={"input": {}, "approval_id": approval_id},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["status"] == "executed"
        assert body["output"]["channel"] == CHANNEL
        assert body["output"]["reference"]
        assert slack.posted == [(CHANNEL, MESSAGE)]

        # 4. The approval is spent; the message cannot be posted twice.
        again = client.post(
            f"/tenants/{tenant.id}/tools/{TOOL}/execute",
            headers=headers,
            json={"input": {}, "approval_id": approval_id},
        )
        assert again.status_code != 200 or again.json().get("status") != "executed"
        assert slack.posted == [(CHANNEL, MESSAGE)]

    async def test_without_an_act_credential_the_action_fails_after_approval(
        self, client, db, repositories, make_token, authorization_override
    ):
        """A read credential alone is not enough, over HTTP as well."""
        slack = self._app_slack()
        tenant, requester, approver = await self._tenant_with_connector(db, repositories)
        authorization_override(
            {
                requester.id: ApplicationRole.OPERATIONS_USER,
                approver.id: ApplicationRole.COMPANY_ADMINISTRATOR,
            }
        )
        requester_token = make_token(requester.id)
        approver_token = make_token(approver.id)

        # Only a READ credential is configured.
        stored = client.post(
            f"/tenants/{tenant.id}/connectors/credentials/slack",
            headers={"Authorization": f"Bearer {approver_token}"},
            json={"credential": "xoxb-read-only"},
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["scope"] == "read"

        attempt = client.post(
            f"/tenants/{tenant.id}/tools/{TOOL}/execute",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={"input": {"channel": CHANNEL, "message": MESSAGE}},
        )
        approval_id = attempt.json()["approval_id"]
        client.post(
            f"/tenants/{tenant.id}/approvals/{approval_id}/decisions",
            headers={"Authorization": f"Bearer {approver_token}"},
            json={"decision": "approve"},
        )

        run = client.post(
            f"/tenants/{tenant.id}/tools/{TOOL}/execute",
            headers={"Authorization": f"Bearer {requester_token}"},
            json={"input": {}, "approval_id": approval_id},
        )

        assert run.status_code != 200 or run.json().get("status") != "executed"
        assert slack.posted == []

    async def test_the_tool_appears_in_the_catalog_with_its_real_risk(
        self, client, db, repositories, make_token, authorization_override
    ):
        """A tool nobody can see is a tool nobody can ask for."""
        tenant, requester, _ = await self._tenant_with_connector(db, repositories)
        authorization_override({requester.id: ApplicationRole.OPERATIONS_USER})
        token = make_token(requester.id)

        listing = client.get(
            f"/tenants/{tenant.id}/tools",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert listing.status_code == 200, listing.text
        tools = {item["name"]: item for item in listing.json()["items"]}
        assert TOOL in tools
        assert tools[TOOL]["risk_level"] == "high"
