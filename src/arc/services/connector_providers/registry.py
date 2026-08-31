"""Static provider registry following the AI Tools ToolRegistry pattern.

The registry is built once from the code-defined catalog (GitHub, Slack,
Linear per ADR-002) and exposes only read operations. There is no
registration or mutation API: a provider is usable if and only if it is
part of this static catalog.
"""

from typing import Dict, FrozenSet, Mapping, Optional

from arc.domain.models import ConnectorProvider
from arc.services.connector_providers.base import ProviderAdapter
from arc.services.connector_providers.fake import (
    FakeGitHubProvider,
    FakeLinearProvider,
    FakeSlackProvider,
)
from arc.services.connector_providers.github import GitHubProviderAdapter
from arc.services.connector_providers.linear import LinearProviderAdapter
from arc.services.connector_providers.settings import ConnectorSettings
from arc.services.connector_providers.slack import SlackProviderAdapter


class ProviderRegistry:
    """Code-defined catalog of provider adapters; no runtime registration."""

    def __init__(self, adapters: Optional[Mapping[ConnectorProvider, ProviderAdapter]] = None):
        self._adapters: Dict[ConnectorProvider, ProviderAdapter] = (
            dict(adapters) if adapters else {}
        )

    def get(self, provider: ConnectorProvider) -> Optional[ProviderAdapter]:
        """Return the adapter for ``provider``, or None."""
        return self._adapters.get(provider)

    def providers(self) -> FrozenSet[ConnectorProvider]:
        """Return the set of supported provider adapters."""
        return frozenset(self._adapters.keys())


def build_provider_registry(settings: ConnectorSettings) -> ProviderRegistry:
    """Build the provider registry from the code-defined catalog.

    Simulated mode (default) uses the deterministic controlled/fake
    clients (TRD 33); live mode uses the httpx adapters against the real
    provider APIs.
    """
    if settings.provider_mode == "live":
        adapters = {
            ConnectorProvider.GITHUB: GitHubProviderAdapter(),
            ConnectorProvider.SLACK: SlackProviderAdapter(),
            ConnectorProvider.LINEAR: LinearProviderAdapter(),
        }
    else:
        adapters = {
            ConnectorProvider.GITHUB: FakeGitHubProvider(),
            ConnectorProvider.SLACK: FakeSlackProvider(),
            ConnectorProvider.LINEAR: FakeLinearProvider(),
        }
    return ProviderRegistry(adapters)
