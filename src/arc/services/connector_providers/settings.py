"""Environment-driven connector integration settings.

Credentials follow the established X-11 configuration pattern
(``APPLICATION_ROLE_ASSIGNMENTS``): a JSON environment value holding
development-only placeholders, never committed to the repository.
Production secret management remains a separate decision.

- ``CONNECTOR_CREDENTIALS``: JSON object mapping tenant IDs to provider
  tokens, for example::

      {"tenant-a": {"github": "dev-placeholder-token", "linear": "..."}}

- ``CONNECTOR_PROVIDER_MODE``: ``simulated`` (default) or ``live``.
  Simulated mode uses the deterministic controlled/fake provider clients
  (TRD 33); live mode uses the httpx adapters against real provider APIs.

All settings fail closed: invalid JSON or an unknown provider name raises
a configuration error.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from arc.domain.models import ConnectorProvider

PROVIDER_MODES = ("simulated", "live")


class ConnectorConfigurationError(Exception):
    """Raised when the connector configuration is missing or invalid."""


@dataclass(frozen=True)
class ConnectorSettings:
    """Connector integration configuration derived from the environment."""

    provider_mode: str = "simulated"

    def __post_init__(self) -> None:
        if self.provider_mode not in PROVIDER_MODES:
            raise ConnectorConfigurationError(
                f"CONNECTOR_PROVIDER_MODE must be one of {PROVIDER_MODES}"
            )


def _parse_connector_credentials(raw: str) -> Dict[str, Dict[ConnectorProvider, str]]:
    """Parse the CONNECTOR_CREDENTIALS JSON into tenant-scoped provider tokens."""
    credentials: Dict[str, Dict[ConnectorProvider, str]] = {}
    if not raw:
        return credentials
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorConfigurationError("CONNECTOR_CREDENTIALS must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ConnectorConfigurationError("CONNECTOR_CREDENTIALS must be a JSON object")
    for tenant_id, providers in parsed.items():
        if not isinstance(providers, dict):
            raise ConnectorConfigurationError(
                f"Connector credentials for tenant {tenant_id} must be a JSON object"
            )
        per_provider: Dict[ConnectorProvider, str] = {}
        for provider_name, token in providers.items():
            try:
                provider = ConnectorProvider(provider_name)
            except ValueError as exc:
                raise ConnectorConfigurationError(
                    f"Unknown connector provider for tenant {tenant_id}: {provider_name}"
                ) from exc
            if not isinstance(token, str) or not token:
                raise ConnectorConfigurationError(
                    f"Connector credential for tenant {tenant_id} and provider "
                    f"{provider_name} must be a non-empty string"
                )
            per_provider[provider] = token
        credentials[tenant_id] = per_provider
    return credentials


class ConnectorCredentialStore:
    """Tenant-scoped provider credentials resolved from the environment.

    Credentials are read lazily from the environment on every lookup and
    are never exposed through any API, log, error, or audit record. A
    missing credential fails closed (the caller receives None).
    """

    def __init__(self, raw: Optional[str] = None):
        self._raw = raw

    def get(self, tenant_id: str, provider: ConnectorProvider) -> Optional[str]:
        """Return the provider token for a tenant, or None when absent."""
        raw = self._raw if self._raw is not None else os.getenv("CONNECTOR_CREDENTIALS", "")
        credentials = _parse_connector_credentials(raw)
        return credentials.get(tenant_id, {}).get(provider)


def get_connector_settings() -> ConnectorSettings:
    """Build connector settings from the environment (simulated by default).

    An empty ``CONNECTOR_PROVIDER_MODE`` is treated as unset (compose
    injects empty variables); the safe simulated default is used.
    """
    return ConnectorSettings(provider_mode=os.getenv("CONNECTOR_PROVIDER_MODE") or "simulated")
