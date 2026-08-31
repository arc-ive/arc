"""Strict provider endpoint allowlist (SSRF protection).

Arc supports exactly the ADR-002 providers (GitHub, Slack, Linear), and
every outbound request goes to one of the code-defined endpoints below.
Tenant input never selects a network destination: connector targets are
names (``owner/repo``, channel name, team key) validated separately.

``assert_approved_provider_url`` is defense in depth: even though the
adapter URLs are code-defined constants, every request URL is checked
against the allowlist before it is sent, so an accidental constant edit
or a future tenant-supplied URL can never reach an unapproved host.

Denied by construction:

- any scheme other than ``https``
- any host that is not an exact approved provider host
- IP literals (including private ranges, loopback, and the cloud
  metadata address ``169.254.169.254``)
- localhost and internal DNS names (they are not approved hosts)
- userinfo embedded in the URL
"""

from typing import Dict, FrozenSet, Mapping

from arc.domain.models import ConnectorProvider
from arc.services.connector_providers.base import ProviderValidationError

APPROVED_PROVIDER_HOSTS: Dict[ConnectorProvider, FrozenSet[str]] = {
    ConnectorProvider.GITHUB: frozenset({"api.github.com"}),
    ConnectorProvider.SLACK: frozenset({"slack.com"}),
    ConnectorProvider.LINEAR: frozenset({"api.linear.app"}),
}


def assert_approved_provider_url(provider: ConnectorProvider, url: str) -> str:
    """Validate that ``url`` is an approved ``https`` endpoint for ``provider``.

    Raises ``ProviderValidationError`` for any URL that is not on the
    provider's approved allowlist. Returns the URL unchanged on success.
    """
    if provider not in APPROVED_PROVIDER_HOSTS:
        raise ProviderValidationError(
            f"Connector provider is not in the approved endpoint allowlist: {provider!r}"
        )
    if not isinstance(url, str) or not url:
        raise ProviderValidationError("Provider URL cannot be empty")
    if not url.startswith("https://"):
        raise ProviderValidationError("Provider URL must use https")
    rest = url[len("https://") :]
    host = rest.split("/", 1)[0]
    if not host:
        raise ProviderValidationError("Provider URL has no host")
    if "@" in host:
        raise ProviderValidationError("Provider URL must not contain credentials")
    if host not in APPROVED_PROVIDER_HOSTS[provider]:
        raise ProviderValidationError("Provider URL is not an approved endpoint")
    return url


def approved_provider_hosts() -> Mapping[ConnectorProvider, FrozenSet[str]]:
    """Return the provider host allowlist (read-only view)."""
    return APPROVED_PROVIDER_HOSTS
