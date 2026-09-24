"""External action boundary (ADR-013).

Arc's connectors were read-only: every adapter implemented ``fetch`` and
nothing else, so "post to a channel" had no path at any layer. This
service is the write side, and it is deliberately narrow.

An external action is the one thing Arc does that a customer cannot undo
by deleting a row. So the path to one is longer than the path to a read,
and every step of it is somewhere a human already made a decision:

1. **The platform allows it.** ``external_action`` is a capability, so a
   platform administrator can switch off every outbound action for a
   tenant, or for all tenants, without a deploy.
2. **The caller is authorized.** The tool declares ``connector:act``, so
   ``tool:execute`` alone is not enough -- and ``ToolExecutionService``
   checks it before any handler runs.
3. **A human approved this exact call.** Every action tool is HIGH risk
   with ``REQUIRE_HUMAN_APPROVAL``. The approval binds tenant, tool,
   version and a digest of the validated arguments, and is single-use
   (ADR-005), so the approval IS the idempotency guarantee: the same
   approval cannot post twice.
4. **An administrator chose the destination.** The target must match an
   ACTIVE connector the tenant configured. A channel name proposed by a
   model -- or by anything that reached the model's input -- cannot
   address a destination nobody set up.
5. **The credential is the act credential.** Resolution asks for
   ``CredentialScope.ACT``. A tenant with only a read credential cannot
   act: the read token is never borrowed, and there is no ENV fallback
   here, because a development convenience that posts to a real workspace
   is not a convenience.

The service never sees a URL. It hands the adapter a validated target
name and body; the adapter's endpoints are code-defined constants checked
against the provider allowlist.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from arc.domain.models import ConnectorProvider, CredentialScope, TenantContext
from arc.services.connector_providers.base import (
    ProviderAction,
    ProviderAuthError,
    ProviderCredential,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)

logger = logging.getLogger("arc.external_actions")

#: Capability id gating every outbound action (V2-ADR-004 hard ceiling).
EXTERNAL_ACTION_CAPABILITY = "external_action"

_ERROR_KINDS = {
    ProviderValidationError: "invalid_action",
    ProviderAuthError: "provider_auth_failed",
    ProviderRateLimitError: "provider_rate_limited",
    ProviderTransportError: "provider_unavailable",
    ProviderResponseError: "provider_response_invalid",
}


class ExternalActionError(Exception):
    """A controlled failure of an external action.

    ``error_kind`` is a safe, hardcoded category -- never a provider
    message, which could carry content Arc did not author.
    """

    def __init__(self, message: str, error_kind: str):
        super().__init__(message)
        self.error_kind = error_kind


@dataclass(frozen=True)
class ExternalActionOutcome:
    """What Arc actually did outside itself."""

    provider: ConnectorProvider
    target: str
    reference: str
    url: Optional[str] = None


class ExternalActionService:
    """Resolve, authorize by configuration, and perform one external action."""

    def __init__(
        self,
        connector_repo,
        provider_registry,
        credential_service,
        capability_service=None,
    ):
        self._connector_repo = connector_repo
        self._registry = provider_registry
        self._credential_service = credential_service
        self._capability_service = capability_service

    async def perform(
        self,
        context: TenantContext,
        provider: ConnectorProvider,
        target: str,
        body: str,
    ) -> ExternalActionOutcome:
        """Perform one external action for the trusted tenant.

        Raises :class:`ExternalActionError` for every controlled failure,
        carrying a safe ``error_kind``. Nothing here reports success it
        did not get: a provider that refuses is a failure, not a no-op.
        """
        if self._capability_service is not None:
            enabled = await self._capability_service.is_enabled(
                context.tenant_id, EXTERNAL_ACTION_CAPABILITY
            )
            if not enabled:
                raise ExternalActionError(
                    "External actions are not enabled for this tenant",
                    "capability_disabled",
                )

        adapter = self._registry.get(provider)
        if adapter is None or not hasattr(adapter, "act"):
            # Not every provider has a write side. Answering by type
            # rather than by calling and catching keeps "can this act?"
            # a question with a definite answer.
            raise ExternalActionError(
                "This connector provider cannot perform actions",
                "provider_cannot_act",
            )

        connector = await self._connector_repo.find_active_by_provider_and_target(
            context.tenant_id, provider.value, target
        )
        if connector is None:
            raise ExternalActionError(
                "No active connector is configured for that destination",
                "destination_not_configured",
            )

        token = await self._credential_service.resolve_credential(
            context.tenant_id, provider, CredentialScope.ACT
        )
        if token is None:
            raise ExternalActionError(
                "No action credential is configured for this provider",
                "missing_act_credential",
            )

        credential = ProviderCredential(provider=provider, token=token)
        try:
            action = ProviderAction(target=target, body=body)
        except ValueError as exc:
            raise ExternalActionError("The action is not valid", "invalid_action") from exc

        try:
            result = await adapter.act(credential, action)
        except ProviderError as exc:
            error_kind = _ERROR_KINDS.get(type(exc), "provider_error")
            logger.warning(
                "external_action_failed tenant=%s provider=%s error_kind=%s",
                context.tenant_id,
                provider.value,
                error_kind,
            )
            raise ExternalActionError("The external action failed", error_kind) from exc

        logger.info(
            "external_action_performed tenant=%s provider=%s connector=%s reference=%s",
            context.tenant_id,
            provider.value,
            connector.id,
            result.reference,
        )
        return ExternalActionOutcome(
            provider=provider,
            target=target,
            reference=result.reference,
            url=result.url,
        )
