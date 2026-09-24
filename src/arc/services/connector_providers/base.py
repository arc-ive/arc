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


#: Maximum length for provider record attribution/metadata strings.
#: Keeps display-bound fields bounded; the knowledge layer enforces its
#: own limits (e.g. ``external_id`` <= 255 chars) on top of these.
_PROVIDER_RECORD_AUTHOR_MAX_CHARS = 255
_PROVIDER_RECORD_TIMESTAMP_MAX_CHARS = 64
_PROVIDER_RECORD_REFERENCE_MAX_CHARS = 255


@dataclass(frozen=True)
class ProviderRecord:
    """One validated, normalized record fetched from a provider.

    Source metadata contract (Issue #326): the required fields carry the
    quotable content; the optional fields preserve provider-origin
    metadata the adapters already fetch but previously dropped. Every
    optional field has a named downstream consumer:

    - ``author``: citation attribution ("who said/wrote this") for Ask
      Arc answers; travels with content through the PII Guard boundary
      (never bypassed to preserve attribution).
    - ``external_created_at`` / ``external_updated_at``: provider-side
      timestamps as opaque strings (formats differ per provider, so no
      datetime parsing here); future recency display and incremental-sync
      cursors (Issues #332/#333).
    - ``parent_source_id``: containing object for replies/comments
      (Slack ``thread_ts``; GitHub comment linkage in a later scope).
    - ``container_id``: the synced container's stable identity
      (``owner/repo``, channel name, team key); survives renames because
      the sync target is re-resolved at sync time.

    Deliberately absent: ``provider`` (redundant — ``ProviderFetchResult``
    and the connector config already carry it exactly once), and any
    credential/token material (never metadata). Queryable persistence of
    these fields is deferred to the retrieval-integration issue, which
    owns a consumer for them; this contract defines, validates, maps, and
    carries them to the ingestion boundary.
    """

    source_id: str
    title: str
    content: str
    url: Optional[str] = None
    author: Optional[str] = None
    external_created_at: Optional[str] = None
    external_updated_at: Optional[str] = None
    parent_source_id: Optional[str] = None
    container_id: Optional[str] = None

    def __post_init__(self):
        if not self.source_id:
            raise ValueError("Provider record source_id cannot be empty")
        if not self.title:
            raise ValueError("Provider record title cannot be empty")
        if not self.content:
            raise ValueError("Provider record content cannot be empty")
        _reject_empty_optional("author", self.author, _PROVIDER_RECORD_AUTHOR_MAX_CHARS)
        _reject_empty_optional(
            "external_created_at",
            self.external_created_at,
            _PROVIDER_RECORD_TIMESTAMP_MAX_CHARS,
        )
        _reject_empty_optional(
            "external_updated_at",
            self.external_updated_at,
            _PROVIDER_RECORD_TIMESTAMP_MAX_CHARS,
        )
        _reject_empty_optional(
            "parent_source_id", self.parent_source_id, _PROVIDER_RECORD_REFERENCE_MAX_CHARS
        )
        _reject_empty_optional(
            "container_id", self.container_id, _PROVIDER_RECORD_REFERENCE_MAX_CHARS
        )


def _reject_empty_optional(field_name: str, value: Optional[str], max_chars: int) -> None:
    """Reject empty or over-long optional metadata (``None`` means absent)."""
    if value is None:
        return
    if not isinstance(value, str) or not value:
        raise ValueError(f"Provider record {field_name} must be a non-empty string when provided")
    if len(value) > max_chars:
        raise ValueError(f"Provider record {field_name} cannot exceed {max_chars} characters")


def build_connector_external_id(provider: ConnectorProvider, source_id: str) -> str:
    """Build the knowledge-layer identity for one synced record.

    Grammar (Issue #326, frozen): ``{provider}:{source_id}``. This string
    is the ADR-003 logical identity together with tenant and source, so
    it must stay byte-stable: changing it orphans every previously synced
    document into duplicates. Produces byte-for-byte the legacy string.
    """
    return f"{provider.value}:{source_id}"


def build_connector_provenance(provider: ConnectorProvider, source_id: str) -> str:
    """Build the citation provenance for one synced record.

    Grammar (Issue #326, frozen): ``connector:{provider}:{source_id}``.
    Provenance is write-once (re-ingestion preserves the stored value),
    so this grammar is pinned, never enriched: enrichment would fork the
    corpus into legacy and new shapes with no consumer. Produces
    byte-for-byte the legacy string.
    """
    return f"connector:{provider.value}:{source_id}"


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
