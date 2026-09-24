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


@dataclass(frozen=True)
class ProviderAction:
    """One external action to perform through a provider (ADR-013).

    ``target`` is the same kind of tenant-configured name ``fetch`` takes
    (a Slack channel, a repository, a team key) and is validated by the
    adapter before any request is made. ``body`` is the already-validated
    payload from the tool's input model — an adapter never receives raw
    caller input, and never a free-form URL.
    """

    target: str
    body: str

    def __post_init__(self):
        if not self.target:
            raise ValueError("Provider action target cannot be empty")
        if not self.body:
            raise ValueError("Provider action body cannot be empty")


@dataclass(frozen=True)
class ProviderActionResult:
    """Outcome of one external action.

    ``reference`` is the provider's own identifier for what was created
    (a message timestamp, an issue key). It exists so the audit trail can
    point at the thing Arc caused in the outside world; it is never a
    secret and is safe to record.
    """

    provider: ConnectorProvider
    reference: str
    url: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.provider, ConnectorProvider):
            raise ValueError(f"Invalid connector provider: {self.provider!r}")
        if not self.reference:
            raise ValueError("Provider action reference cannot be empty")


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


class ProviderActionAdapter(Protocol):
    """Contract for adapters that can ACT on the outside world (ADR-013).

    Deliberately a SEPARATE protocol from :class:`ProviderAdapter`. Read
    adapters are not forced to grow a write method that raises, and an
    adapter that has no write side simply does not satisfy this protocol
    -- so "can this provider act?" is answerable by type, not by calling
    it and catching an error.

    An implementation receives an ``ACT``-scoped credential. It must never
    be handed a read credential: the scopes differ at the provider and the
    blast radius differs at Arc (ADR-013).
    """

    provider: ConnectorProvider

    async def act(
        self,
        credential: ProviderCredential,
        action: ProviderAction,
    ) -> ProviderActionResult:
        """Perform ``action`` and return a validated result.

        Endpoints are code-defined constants checked against the provider
        allowlist. Failures raise the same controlled ``ProviderError``
        subclasses ``fetch`` raises, so the caller distinguishes an auth
        failure from a rate limit from a malformed response without
        parsing strings.
        """
        ...
