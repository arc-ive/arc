"""Provider integration primitives for the Connector slice.

The provider boundary follows the AI Tools pattern: a static, code-defined
catalog of adapters (ADR-002 providers GitHub, Slack, Linear). Tenants
cannot register providers, supply endpoints, or upload code. Every
external request goes through an adapter that validates the response into
typed records; malformed or unexpected responses fail closed with
controlled errors. Credentials are never serialized or logged.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from arc.domain.models import ConnectorProvider


class ProviderError(Exception):
    """Base error for controlled connector provider failures."""


class ProviderValidationError(ProviderError):
    """Raised when the connector target/configuration is invalid."""


class ProviderAuthError(ProviderError):
    """Raised when the provider rejects the supplied credential."""


class ProviderRateLimitError(ProviderError):
    """Raised when the provider rate limit is exceeded."""


class ProviderTransportError(ProviderError):
    """Raised on network or provider availability failures."""


class ProviderResponseError(ProviderError):
    """Raised when the provider returns an unexpected or malformed response."""


@dataclass(frozen=True)
class ProviderCredential:
    """One provider credential; never serialized or logged."""

    provider: ConnectorProvider
    token: str

    def __post_init__(self):
        if not isinstance(self.provider, ConnectorProvider):
            raise ValueError(f"Invalid connector provider: {self.provider!r}")
        if not self.token:
            raise ValueError("Provider credential token cannot be empty")

    def __repr__(self) -> str:
        """Never expose the token through any representation."""
        return f"ProviderCredential(provider={self.provider.value!r}, token='***')"


@dataclass(frozen=True)
class ProviderRecord:
    """One validated, normalized record fetched from a provider."""

    source_id: str
    title: str
    content: str
    url: Optional[str] = None

    def __post_init__(self):
        if not self.source_id:
            raise ValueError("Provider record source_id cannot be empty")
        if not self.title:
            raise ValueError("Provider record title cannot be empty")
        if not self.content:
            raise ValueError("Provider record content cannot be empty")


@dataclass(frozen=True)
class ProviderFetchResult:
    """Outcome of one provider fetch."""

    provider: ConnectorProvider
    records: List[ProviderRecord] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.provider, ConnectorProvider):
            raise ValueError(f"Invalid connector provider: {self.provider!r}")
        for record in self.records:
            if not isinstance(record, ProviderRecord):
                raise ValueError("Provider fetch records must be ProviderRecord instances")


class ProviderAdapter(Protocol):
    """Contract for provider adapters (GitHub, Slack, Linear)."""

    provider: ConnectorProvider

    async def fetch(
        self,
        credential: ProviderCredential,
        target: str,
        limit: int = 25,
    ) -> ProviderFetchResult:
        """Fetch and validate provider records for ``target``.

        ``target`` is the tenant-configured connector name (for example
        ``owner/repo`` for GitHub, a channel name for Slack, or a team key
        for Linear). Endpoints are code-defined constants; tenant input is
        validated before any request is made.
        """
        ...
