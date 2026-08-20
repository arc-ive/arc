"""Configurable, provider-agnostic embedding abstraction (Secure RAG).

The abstraction must not hard-code any production provider (OpenAI,
OpenRouter, OpenCode Zen, or any other). Production embedding
provider/model selection is intentionally deferred to a separate future
decision; this foundation ships with a deterministic local provider that
is suitable for repository, service, and API tests.

Provider selection is environment-driven (``EMBEDDING_PROVIDER`` /
``EMBEDDING_MODEL``, documented in ``.env.example``) and fails closed:
an unknown provider or an invalid configuration raises
``EmbeddingConfigurationError`` before any service is built.

Embedding storage is fixed at ``EMBEDDING_DIMENSIONS`` dimensions
(``vector(64)`` in the schema); the deterministic provider produces
exactly this dimension, and the retrieval service validates provider
output against it so that storage-dimension mismatches fail fast with a
clear error instead of a database error.
"""

import math
import os
import re
import zlib
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 64


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

    ``provider`` selects the embedding implementation. Only
    ``deterministic`` is currently supported; any other value fails
    closed at configuration time (a production provider is a deferred
    decision, not silently substituted). ``model`` is metadata for
    future providers and has no effect on the deterministic provider.

    ``dimensions`` must equal ``EMBEDDING_DIMENSIONS``: the pgvector
    column is fixed at ``vector(64)``, so a configured dimension that
    disagrees with storage fails closed instead of failing at query time.
    """

    provider: str = "deterministic"
    model: Optional[str] = None
    dimensions: int = EMBEDDING_DIMENSIONS

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
    )


def build_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    """Build the configured embedding provider.

    Raises:
        EmbeddingConfigurationError: for any provider other than
            ``deterministic``. Fail closed: a production provider is a
            deferred decision and must never be silently substituted.
    """
    if settings.provider == "deterministic":
        return DeterministicEmbeddingProvider(dimensions=settings.dimensions)
    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER: {settings.provider!r} "
        "(supported providers: deterministic; a production provider is a deferred decision)"
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
