"""Connector provider integrations (GitHub, Slack, Linear).

PRD 22 / TRD 33 / ADR-002: provider adapters are code-defined and
provider-agnostic at the connector service boundary. Simulated mode uses
deterministic controlled/fake clients; live mode uses httpx adapters
behind the same interface.
"""

from arc.services.connector_providers.base import (
    ProviderAdapter,
    ProviderAuthError,
    ProviderCredential,
    ProviderError,
    ProviderFetchResult,
    ProviderRateLimitError,
    ProviderRecord,
    ProviderResponseError,
    ProviderTransportError,
    ProviderValidationError,
)
from arc.services.connector_providers.registry import ProviderRegistry, build_provider_registry
from arc.services.connector_providers.settings import (
    ConnectorConfigurationError,
    ConnectorCredentialStore,
    ConnectorSettings,
    get_connector_settings,
)
from arc.services.connector_providers.targets import (
    approved_provider_hosts,
    assert_approved_provider_url,
)

__all__ = [
    "ConnectorConfigurationError",
    "ConnectorCredentialStore",
    "ConnectorSettings",
    "ProviderAdapter",
    "ProviderAuthError",
    "ProviderCredential",
    "ProviderError",
    "ProviderFetchResult",
    "ProviderRateLimitError",
    "ProviderRecord",
    "ProviderRegistry",
    "ProviderResponseError",
    "ProviderTransportError",
    "ProviderValidationError",
    "approved_provider_hosts",
    "assert_approved_provider_url",
    "build_provider_registry",
    "get_connector_settings",
]
