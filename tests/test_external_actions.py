"""External action boundary tests (ADR-013, Issue #304).

Arc's connectors were read-only, so "post to a channel" had no path at
any layer. These tests cover the boundary that path now goes through, and
they are written around one question: what stops an action that should
not happen?

Every refusal test asserts that the fake provider recorded NOTHING. A
service that returned an error after posting would pass a test that only
checked the error, and for an action tool the side effect is the whole
point.
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from arc.domain.models import (
    ConnectorConfig,
    ConnectorProvider,
    ConnectorStatus,
    CredentialScope,
    TenantContext,
    UserRole,
)
from arc.services.connector_providers.fake import (
    FAILURE_AUTH,
    FAILURE_RATE_LIMIT,
    FakeLinearProvider,
    FakeSlackProvider,
)
from arc.services.connector_providers.registry import ProviderRegistry
from arc.services.external_actions import (
    EXTERNAL_ACTION_CAPABILITY,
    ExternalActionError,
    ExternalActionService,
)

TENANT = "act-tenant"
ACT_TOKEN = "xoxb-act-token"
READ_TOKEN = "xoxb-read-token"


def _context(tenant_id: str = TENANT) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_name="Act Tenant",
        user_id="act-user",
        role=UserRole.MEMBER,
    )


class _FakeConnectorRepo:
    """Only the one lookup the boundary makes, matched the way SQL does."""

    def __init__(self, configs=()):
        self._configs = list(configs)

    async def find_active_by_provider_and_target(self, tenant_id, provider, target):
        for config in self._configs:
            if (
                config.tenant_id == tenant_id
                and config.provider.value == provider
                and config.target == target
                and config.status == ConnectorStatus.ACTIVE
            ):
                return config
        return None


@dataclass
class _FakeCredentialService:
    """Resolves per (tenant, provider, scope), like the real one."""

    act_token: Optional[str] = ACT_TOKEN
    read_token: Optional[str] = READ_TOKEN
    asked: Optional[list] = None

    async def resolve_credential(self, tenant_id, provider, scope=CredentialScope.READ):
        if self.asked is None:
            self.asked = []
        self.asked.append((tenant_id, provider.value, scope.value))
        return self.act_token if scope == CredentialScope.ACT else self.read_token


class _FakeCapabilityService:
    def __init__(self, enabled=True):
        self.enabled = enabled

    async def is_enabled(self, tenant_id, capability_id):
        assert capability_id == EXTERNAL_ACTION_CAPABILITY
        return self.enabled


def _connector(target="ops", provider=ConnectorProvider.SLACK, status=ConnectorStatus.ACTIVE):
    return ConnectorConfig(
        id=f"conn-{target}",
        tenant_id=TENANT,
        provider=provider,
        name=f"{provider.value}-{target}",
        target=target,
        status=status,
    )


def _service(
    *,
    slack=None,
    configs=(_connector(),),
    credentials=None,
    capability=None,
):
    slack = slack if slack is not None else FakeSlackProvider()
    registry = ProviderRegistry({ConnectorProvider.SLACK: slack})
    return (
        ExternalActionService(
            connector_repo=_FakeConnectorRepo(configs),
            provider_registry=registry,
            credential_service=credentials or _FakeCredentialService(),
            capability_service=capability or _FakeCapabilityService(),
        ),
        slack,
    )


@pytest.mark.asyncio
async def test_posts_to_a_configured_destination():
    service, slack = _service()

    outcome = await service.perform(_context(), ConnectorProvider.SLACK, "ops", "Deploy finished")

    assert outcome.provider == ConnectorProvider.SLACK
    assert outcome.target == "ops"
    assert outcome.reference
    assert slack.posted == [("ops", "Deploy finished")]


@pytest.mark.asyncio
async def test_uses_the_act_credential_and_never_the_read_one():
    """The headline rule of ADR-013, asserted on the token that was used."""
    credentials = _FakeCredentialService()
    service, slack = _service(credentials=credentials)

    await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert credentials.asked == [(TENANT, "slack", "act")]
    assert slack.posted == [("ops", "hello")]


@pytest.mark.asyncio
async def test_a_tenant_with_only_a_read_credential_cannot_act():
    """No silent fallback: the read token is not borrowed to post."""
    credentials = _FakeCredentialService(act_token=None, read_token=READ_TOKEN)
    service, slack = _service(credentials=credentials)

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "missing_act_credential"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_an_unconfigured_destination_is_refused():
    """A channel nobody configured is not a destination Arc will use."""
    service, slack = _service(configs=(_connector(target="ops"),))

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "finance", "hello")

    assert exc.value.error_kind == "destination_not_configured"
    assert slack.posted == []


@pytest.mark.parametrize("status", [ConnectorStatus.INACTIVE, ConnectorStatus.ERROR])
@pytest.mark.asyncio
async def test_a_connector_that_is_not_active_is_not_a_destination(status):
    service, slack = _service(configs=(_connector(target="ops", status=status),))

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "destination_not_configured"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_another_tenants_connector_is_not_a_destination():
    """Tenant isolation, at the destination check as well as in SQL."""
    service, slack = _service()

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context("someone-else"), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "destination_not_configured"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_the_platform_can_switch_external_actions_off():
    service, slack = _service(capability=_FakeCapabilityService(enabled=False))

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "capability_disabled"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_the_capability_is_checked_before_the_credential_is_touched():
    """A disabled capability must not decrypt anything."""
    credentials = _FakeCredentialService()
    service, _ = _service(credentials=credentials, capability=_FakeCapabilityService(enabled=False))

    with pytest.raises(ExternalActionError):
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert credentials.asked is None


@pytest.mark.asyncio
async def test_a_provider_with_no_write_side_cannot_act():
    """Answered by shape, not by calling and catching."""
    registry = ProviderRegistry({ConnectorProvider.LINEAR: FakeLinearProvider()})
    service = ExternalActionService(
        connector_repo=_FakeConnectorRepo(
            (_connector(target="ENG", provider=ConnectorProvider.LINEAR),)
        ),
        provider_registry=registry,
        credential_service=_FakeCredentialService(),
        capability_service=_FakeCapabilityService(),
    )

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.LINEAR, "ENG", "hello")

    assert exc.value.error_kind == "provider_cannot_act"


@pytest.mark.asyncio
async def test_an_unknown_provider_cannot_act():
    service = ExternalActionService(
        connector_repo=_FakeConnectorRepo((_connector(),)),
        provider_registry=ProviderRegistry({}),
        credential_service=_FakeCredentialService(),
        capability_service=_FakeCapabilityService(),
    )

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "provider_cannot_act"


@pytest.mark.parametrize(
    "failure,expected_kind",
    [
        (FAILURE_AUTH, "provider_auth_failed"),
        (FAILURE_RATE_LIMIT, "provider_rate_limited"),
    ],
)
@pytest.mark.asyncio
async def test_provider_failures_map_to_safe_error_kinds(failure, expected_kind):
    """The caller learns the category, never the provider's own words."""
    service, slack = _service(slack=FakeSlackProvider(failure=failure))

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == expected_kind
    assert slack.posted == []


@pytest.mark.asyncio
async def test_an_invalid_channel_name_never_reaches_the_provider():
    """Slack target validation happens before any request would be made."""
    service, slack = _service(configs=(_connector(target="Not A Channel"),))

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "Not A Channel", "hello")

    assert exc.value.error_kind == "invalid_action"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_an_over_long_message_is_refused_rather_than_truncated():
    """Posting a shortened version of what the caller wrote is not success."""
    service, slack = _service()

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "x" * 5000)

    assert exc.value.error_kind == "invalid_action"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_an_empty_message_is_refused():
    service, slack = _service()

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "")

    assert exc.value.error_kind == "invalid_action"
    assert slack.posted == []


@pytest.mark.asyncio
async def test_no_capability_service_still_enforces_everything_else():
    """Wiring without a capability service must not become wide open."""
    slack = FakeSlackProvider()
    credentials = _FakeCredentialService(act_token=None)
    service = ExternalActionService(
        connector_repo=_FakeConnectorRepo((_connector(),)),
        provider_registry=ProviderRegistry({ConnectorProvider.SLACK: slack}),
        credential_service=credentials,
        capability_service=None,
    )

    with pytest.raises(ExternalActionError) as exc:
        await service.perform(_context(), ConnectorProvider.SLACK, "ops", "hello")

    assert exc.value.error_kind == "missing_act_credential"
    assert slack.posted == []
