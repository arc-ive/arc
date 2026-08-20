"""Unit tests for the embedding abstraction and deterministic provider.

The deterministic provider is the approved development/test implementation
of the configurable, provider-agnostic ``EmbeddingProvider`` interface. A
production embedding provider is a deferred decision.
"""

import math

import pytest

from arc.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # both vectors are L2-normalized, so dot product == cosine


class TestDeterministicEmbeddingProvider:
    def test_embeddings_have_storage_dimensions(self):
        provider = DeterministicEmbeddingProvider()
        vector = provider.embed("policy handbook")
        assert len(vector) == EMBEDDING_DIMENSIONS

    def test_embeddings_are_deterministic(self):
        provider = DeterministicEmbeddingProvider()
        assert provider.embed("remote work policy") == provider.embed("remote work policy")

    def test_embeddings_are_case_insensitive(self):
        provider = DeterministicEmbeddingProvider()
        assert provider.embed("Policy") == provider.embed("policy")

    def test_embeddings_are_l2_normalized(self):
        provider = DeterministicEmbeddingProvider()
        vector = provider.embed("approved remote work policy")
        norm = math.sqrt(sum(value * value for value in vector))
        assert norm == pytest.approx(1.0)

    def test_shared_words_produce_similar_vectors(self):
        provider = DeterministicEmbeddingProvider()
        same_topic = _cosine(
            provider.embed("remote work policy"),
            provider.embed("remote work handbook"),
        )
        unrelated = _cosine(
            provider.embed("remote work policy"),
            provider.embed("quantum physics laboratory"),
        )
        assert same_topic > unrelated
        assert same_topic > 0.0

    def test_empty_text_returns_zero_vector(self):
        provider = DeterministicEmbeddingProvider()
        assert provider.embed("") == [0.0] * EMBEDDING_DIMENSIONS

    def test_embed_many_preserves_order(self):
        provider = DeterministicEmbeddingProvider()
        texts = ["one", "two three", "four five six"]
        vectors = provider.embed_many(texts)
        assert len(vectors) == 3
        assert vectors[0] == provider.embed(texts[0])
        assert vectors[2] == provider.embed(texts[2])

    def test_invalid_dimensions_are_rejected(self):
        with pytest.raises(ValueError):
            DeterministicEmbeddingProvider(dimensions=0)
        with pytest.raises(ValueError):
            DeterministicEmbeddingProvider(dimensions=-1)


class TestEmbeddingProviderContract:
    def test_deterministic_provider_satisfies_the_contract(self):
        provider = DeterministicEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)
