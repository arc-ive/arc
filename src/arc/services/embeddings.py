"""Configurable, provider-agnostic embedding abstraction (Secure RAG).

Provider selection is environment-driven (``EMBEDDING_PROVIDER`` /
``EMBEDDING_MODEL``, documented in ``.env.example``) and fails closed:
an unknown provider or an invalid configuration raises
``EmbeddingConfigurationError`` before any service is built.

Supported providers:

- ``deterministic`` — local word-hash provider for development and tests.
- ``openai`` — production OpenAI provider (text-embedding-3-small),
  routed through the project's configured gateway (OmniRoute/OpenRouter)
  or directly to OpenAI per ADR-007.

Embedding storage is fixed at ``EMBEDDING_DIMENSIONS`` dimensions
(``vector(1536)`` in the schema); providers produce exactly this dimension,
and the retrieval service validates provider output against it so that
storage-dimension mismatches fail fast with a clear error instead of a
database error.
"""

import math
import os
import re
import zlib
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 1536


class EmbeddingError(Exception):
    """Raised when an embedding provider cannot produce a vector.

    Embedding failures are fail-closed: nothing is persisted and no
    partial or misleading retrieval results are produced.
    """


class EmbeddingConfigurationError(Exception):
    """Raised when the embedding configuration is missing or invalid.

    Configuration failures fail closed: the application refuses to start
    with an unsupported provider, a dimension that disagrees with the
    storage schema, or an invalid value.
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Provider-agnostic embedding interface.

    Implementations must be deterministic for identical inputs and
    produce exactly ``EMBEDDING_DIMENSIONS``-dimensional vectors.
    """

    def embed(self, text: str) -> List[float]:
        """Return the embedding vector for ``text``."""
        ...

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Return the embedding vectors for ``texts`` (in order)."""
        ...


@dataclass(frozen=True)
class EmbeddingSettings:
    """Embedding configuration derived from the environment.

    ``provider`` selects the embedding implementation. Supported providers:
    ``deterministic`` (development/tests) and ``openai`` (production).

    ``model`` is the model identifier (e.g. ``text-embedding-3-small``).

    ``dimensions`` must equal ``EMBEDDING_DIMENSIONS``: the pgvector
    column is fixed at ``vector(1536)``, so a configured dimension that
    disagrees with storage fails closed instead of failing at query time.

    ``api_key`` is required for the ``openai`` provider when connecting
    directly to OpenAI. When routing through the configured gateway
    (OmniRoute/OpenRouter, ``base_url`` set), the gateway manages the
    provider credential per ADR-007 and ``OPENAI_API_KEY`` is optional.

    ``base_url`` configures the API endpoint. When set, embedding
    requests are routed through the configured gateway. When omitted,
    the OpenAI SDK default endpoint is used.
    """

    provider: str = "deterministic"
    model: Optional[str] = None
    dimensions: int = EMBEDDING_DIMENSIONS
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise EmbeddingConfigurationError("EMBEDDING_PROVIDER must not be empty")
        if not isinstance(self.dimensions, int) or self.dimensions < 1:
            raise EmbeddingConfigurationError("EMBEDDING_DIMENSION must be a positive integer")
        if self.dimensions != EMBEDDING_DIMENSIONS:
            raise EmbeddingConfigurationError(
                f"EMBEDDING_DIMENSION {self.dimensions} does not match the storage "
                f"dimension {EMBEDDING_DIMENSIONS} (vector({EMBEDDING_DIMENSIONS}) in "
                "the schema); changing the storage dimension requires a schema "
                "migration, which is a deferred decision"
            )
        if self.provider == "openai" and not self.api_key and not self.base_url:
            raise EmbeddingConfigurationError(
                "OPENAI_API_KEY is required when OMNIROUTE_BASE_URL is not configured"
            )


def _parse_dimension(raw: str) -> int:
    """Parse EMBEDDING_DIMENSION and fail closed on invalid values."""
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise EmbeddingConfigurationError("EMBEDDING_DIMENSION must be a valid integer") from exc


def get_embedding_settings() -> EmbeddingSettings:
    """Build embedding settings from the environment.

    Defaults to the deterministic provider at the storage dimension, so
    the application runs without configuration while keeping the
    configuration explicit.
    """
    return EmbeddingSettings(
        provider=os.getenv("EMBEDDING_PROVIDER", "deterministic"),
        model=os.getenv("EMBEDDING_MODEL") or None,
        dimensions=_parse_dimension(os.getenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))),
        api_key=os.getenv("OPENAI_API_KEY") or None,
        base_url=os.getenv("OMNIROUTE_BASE_URL") or None,
    )


def build_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    """Build the configured embedding provider.

    Raises:
        EmbeddingConfigurationError: for any unsupported provider.
            Fail closed: unknown providers are never silently substituted.
    """
    if settings.provider == "deterministic":
        return DeterministicEmbeddingProvider(dimensions=settings.dimensions)
    if settings.provider == "openai":
        # When routing through a gateway (base_url set), the gateway
        # manages the provider credential per ADR-007. The OpenAI SDK
        # requires a non-empty api_key; a placeholder suffices because
        # all requests route through the configured base_url.
        api_key = settings.api_key if settings.api_key else "gateway-managed"
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=settings.model or "text-embedding-3-small",
            dimensions=settings.dimensions,
            base_url=settings.base_url,
        )
    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER: {settings.provider!r} "
        "(supported providers: deterministic, openai)"
    )


class DeterministicEmbeddingProvider:
    """Local, deterministic embedding provider for development and tests.

    Produces a fixed-dimension vector from word hashing: text is
    lowercased, split into alphanumeric words, each word is hashed
    (``zlib.crc32``, stable across processes) into a bucket, and the
    resulting histogram is L2-normalized.

    Properties:

    - identical inputs always produce identical vectors
    - texts sharing words produce similar (cosine) vectors
    - unrelated texts produce near-orthogonal vectors

    This is NOT a semantic model and is never a production provider.
    """

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS):
        if dimensions < 1:
            raise ValueError("dimensions must be a positive integer")
        self._dimensions = dimensions

    def embed(self, text: str) -> List[float]:
        """Return the deterministic embedding vector for ``text``."""
        vector = [0.0] * self._dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = zlib.crc32(word.encode("utf-8")) % self._dimensions
            vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Return the deterministic embedding vectors for ``texts``."""
        return [self.embed(text) for text in texts]


class OpenAIEmbeddingProvider:
    """Production OpenAI embedding provider (ADR-007).

    Uses the OpenAI ``text-embedding-3-small`` model (or a configurable
    model) routed through the project's configured gateway
    (OmniRoute/OpenRouter) or directly to OpenAI.

    The provider validates output dimension against the expected
    ``EMBEDDING_DIMENSIONS`` and translates provider-specific errors into
    ``EmbeddingError`` so the application abstraction is not coupled to
    the OpenAI SDK.

    ADR-007 V1: no automatic retry/backoff. Transient errors surface as
    ``EmbeddingError`` in logs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dimensions: int = EMBEDDING_DIMENSIONS,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        if dimensions < 1:
            raise ValueError("dimensions must be a positive integer")
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingConfigurationError(
                "openai package is required for the openai embedding provider; "
                "install it with: pip install openai"
            ) from exc

        client_kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    def _validate_vector(self, vector: List[float]) -> None:
        """Validate a returned vector against the expected dimension."""
        if len(vector) != self._dimensions:
            raise EmbeddingError(
                f"Embedding provider returned {len(vector)} dimensions; expected {self._dimensions}"
            )

    def embed(self, text: str) -> List[float]:
        """Return the OpenAI embedding vector for ``text``."""
        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=text,
                dimensions=self._dimensions,
            )
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding request failed: {type(exc).__name__}") from exc

        if not response.data:
            raise EmbeddingError("OpenAI embedding response contained no data")

        vector = response.data[0].embedding
        self._validate_vector(vector)
        return vector

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Return the OpenAI embedding vectors for ``texts`` (in order)."""
        if not texts:
            return []

        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=texts,
                dimensions=self._dimensions,
            )
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding request failed: {type(exc).__name__}") from exc

        if not response.data:
            raise EmbeddingError("OpenAI embedding response contained no data")

        if len(response.data) != len(texts):
            raise EmbeddingError(
                f"OpenAI returned {len(response.data)} embeddings for {len(texts)} inputs"
            )

        vectors = [item.embedding for item in response.data]
        for vector in vectors:
            self._validate_vector(vector)
        return vectors
