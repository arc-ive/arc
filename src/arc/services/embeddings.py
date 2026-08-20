"""Configurable, provider-agnostic embedding abstraction (Secure RAG).

The abstraction must not hard-code any production provider (OpenAI,
OpenRouter, OpenCode Zen, or any other). Production embedding
provider/model selection is intentionally deferred to a separate future
decision; this foundation ships with a deterministic local provider that
is suitable for repository, service, and API tests.

Embedding storage is fixed at ``EMBEDDING_DIMENSIONS`` dimensions
(``vector(64)`` in the schema); the deterministic provider produces
exactly this dimension, and the retrieval service validates provider
output against it so that storage-dimension mismatches fail fast with a
clear error instead of a database error.
"""

import math
import re
import zlib
from typing import List, Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 64


class EmbeddingError(Exception):
    """Raised when an embedding provider cannot produce a vector.

    Embedding failures are fail-closed: nothing is persisted and no
    partial or misleading retrieval results are produced.
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
