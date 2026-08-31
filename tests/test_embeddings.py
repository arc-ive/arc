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
    EmbeddingConfigurationError,
    EmbeddingProvider,
    build_embedding_provider,
    get_embedding_settings,
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


class TestEmbeddingSettings:
    def test_defaults_are_the_deterministic_provider(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)

        settings = get_embedding_settings()

        assert settings.provider == "deterministic"
        assert settings.model is None
        assert settings.dimensions == EMBEDDING_DIMENSIONS

    def test_environment_values_are_read(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
        monkeypatch.setenv("EMBEDDING_MODEL", "local-test")
        monkeypatch.setenv("EMBEDDING_DIMENSION", "1536")

        settings = get_embedding_settings()

        assert settings.provider == "deterministic"
        assert settings.model == "local-test"
        assert settings.dimensions == EMBEDDING_DIMENSIONS

    def test_non_integer_dimension_fails_closed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIMENSION", "not-a-number")

        with pytest.raises(EmbeddingConfigurationError):
            get_embedding_settings()

    def test_dimension_disagreeing_with_storage_fails_closed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIMENSION", "128")

        with pytest.raises(EmbeddingConfigurationError):
            get_embedding_settings()

    def test_empty_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "  ")

        with pytest.raises(EmbeddingConfigurationError):
            get_embedding_settings()


class TestEmbeddingProviderFactory:
    def test_deterministic_provider_is_built_from_settings(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)

        provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, DeterministicEmbeddingProvider)
        assert len(provider.embed("policy handbook")) == EMBEDDING_DIMENSIONS

    def test_unknown_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")

        with pytest.raises(EmbeddingConfigurationError):
            build_embedding_provider(get_embedding_settings())
