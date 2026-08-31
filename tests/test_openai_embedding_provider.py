"""Unit tests for the OpenAI embedding provider.

Tests mock the OpenAI client to avoid network dependency. They cover:
- successful embed() and embed_many()
- input/output ordering
- correct model and dimensions parameter
- configured base_url/gateway usage
- missing credential failure
- timeout/error translation
- malformed response
- wrong output dimension
- empty input behavior
- factory integration
- credential model (ADR-007 Option A): OPENAI_API_KEY optional when base_url set
"""

from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from arc.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
    get_embedding_settings,
)


def _fake_embedding(dimensions: int = EMBEDDING_DIMENSIONS) -> List[float]:
    """Return a deterministic fake embedding vector."""
    return [1.0 / (i + 1) for i in range(dimensions)]


def _fake_response(embeddings: List[List[float]]):
    """Build a fake OpenAI embedding response."""
    data = [SimpleNamespace(embedding=vec) for vec in embeddings]
    return SimpleNamespace(data=data)


def _fake_client(responses: List[List[float]]):
    """Build a mock OpenAI client returning the given embeddings."""
    client = MagicMock()
    client.embeddings.create.return_value = _fake_response(responses)
    return client


class TestOpenAIEmbeddingProviderContract:
    def test_satisfies_embedding_provider_protocol(self):
        client = _fake_client([_fake_embedding()])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            assert isinstance(provider, EmbeddingProvider)


class TestOpenAIEmbeddingProviderEmbed:
    def test_successful_embed(self):
        expected = _fake_embedding()
        client = _fake_client([expected])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            result = provider.embed("test text")

        assert result == expected
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="test text",
            dimensions=EMBEDDING_DIMENSIONS,
        )

    def test_embed_uses_configured_model(self):
        expected = _fake_embedding()
        client = _fake_client([expected])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key", model="custom-model")
            provider.embed("text")

        call_kwargs = client.embeddings.create.call_args
        assert call_kwargs.kwargs["model"] == "custom-model"

    def test_embed_passes_base_url(self):
        client = _fake_client([_fake_embedding()])
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = client
            provider = OpenAIEmbeddingProvider(
                api_key="test-key", base_url="http://gateway:8080/v1"
            )
            provider.embed("text")

        mock_openai.assert_called_once_with(
            api_key="test-key", timeout=30.0, base_url="http://gateway:8080/v1"
        )

    def test_embed_without_base_url(self):
        client = _fake_client([_fake_embedding()])
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = client
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            provider.embed("text")

        mock_openai.assert_called_once_with(api_key="test-key", timeout=30.0)

    def test_embed_empty_text(self):
        expected = _fake_embedding()
        client = _fake_client([expected])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            result = provider.embed("")

        assert result == expected

    def test_embed_returns_correct_dimension(self):
        expected = _fake_embedding()
        client = _fake_client([expected])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            result = provider.embed("text")

        assert len(result) == EMBEDDING_DIMENSIONS


class TestOpenAIEmbeddingProviderEmbedMany:
    def test_successful_embed_many(self):
        vectors = [_fake_embedding(), _fake_embedding(), _fake_embedding()]
        client = _fake_client(vectors)
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            results = provider.embed_many(["a", "b", "c"])

        assert len(results) == 3
        assert results == vectors

    def test_embed_many_preserves_order(self):
        vec_a = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        vec_b = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        client = _fake_client([vec_a, vec_b])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            results = provider.embed_many(["first", "second"])

        assert results[0] == vec_a
        assert results[1] == vec_b

    def test_embed_many_empty_input(self):
        client = _fake_client([])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            results = provider.embed_many([])

        assert results == []
        client.embeddings.create.assert_not_called()

    def test_embed_many_single_input(self):
        expected = [_fake_embedding()]
        client = _fake_client(expected)
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            results = provider.embed_many(["only"])

        assert len(results) == 1

    def test_embed_many_validates_all_vectors(self):
        good = _fake_embedding()
        bad = [0.0] * (EMBEDDING_DIMENSIONS - 1)  # wrong dimension
        client = _fake_client([good, bad])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            with pytest.raises(EmbeddingError, match="dimensions"):
                provider.embed_many(["ok", "bad"])


class TestOpenAIEmbeddingProviderConfiguration:
    def test_missing_api_key_fails(self):
        with pytest.raises(ValueError, match="api_key"):
            OpenAIEmbeddingProvider(api_key=None)

    def test_empty_api_key_fails(self):
        with pytest.raises(ValueError, match="api_key"):
            OpenAIEmbeddingProvider(api_key="")

    def test_invalid_dimensions_fails(self):
        with pytest.raises(ValueError, match="dimensions"):
            OpenAIEmbeddingProvider(api_key="test-key", dimensions=0)


class TestOpenAIEmbeddingProviderErrorTranslation:
    def test_api_error_translates_to_embedding_error(self):
        client = MagicMock()
        client.embeddings.create.side_effect = Exception("API connection failed")
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            with pytest.raises(EmbeddingError, match="OpenAI embedding request failed"):
                provider.embed("text")

    def test_empty_response_data_translates(self):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(data=[])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            with pytest.raises(EmbeddingError, match="no data"):
                provider.embed("text")

    def test_wrong_dimension_translates(self):
        wrong_dim = [0.0] * (EMBEDDING_DIMENSIONS + 1)
        client = _fake_client([wrong_dim])
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            with pytest.raises(EmbeddingError, match="dimensions"):
                provider.embed("text")

    def test_mismatched_count_translates(self):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=_fake_embedding())]
        )
        with patch("openai.OpenAI", return_value=client):
            provider = OpenAIEmbeddingProvider(api_key="test-key")
            with pytest.raises(EmbeddingError, match="1 embeddings for 3 inputs"):
                provider.embed_many(["a", "b", "c"])


class TestOpenAIEmbeddingProviderConfigurationError:
    def test_missing_package_fails_closed(self):
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(EmbeddingConfigurationError, match="openai package"):
                OpenAIEmbeddingProvider(api_key="test-key")


class TestEmbeddingProviderFactoryOpenAI:
    def test_factory_builds_openai_provider(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with patch("openai.OpenAI"):
            provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_factory_builds_openai_with_base_url(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))
        monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://gateway:8080/v1")

        with patch("openai.OpenAI"):
            provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_factory_still_builds_deterministic(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)

        from arc.services.embeddings import DeterministicEmbeddingProvider

        provider = build_embedding_provider(get_embedding_settings())
        assert isinstance(provider, DeterministicEmbeddingProvider)

    def test_factory_unknown_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "unknown-provider")

        with pytest.raises(EmbeddingConfigurationError, match="Unsupported"):
            build_embedding_provider(get_embedding_settings())

    def test_factory_openai_without_api_key_or_base_url_fails(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with pytest.raises(EmbeddingConfigurationError, match="OPENAI_API_KEY"):
            build_embedding_provider(get_embedding_settings())


class TestCredentialModel:
    """Credential model tests per ADR-007 Option A.

    When OMNIROUTE_BASE_URL is configured, OPENAI_API_KEY is optional
    because the gateway manages the upstream provider credential.
    When OMNIROUTE_BASE_URL is NOT configured, OPENAI_API_KEY is required.
    """

    def test_direct_openai_with_key_succeeds(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with patch("openai.OpenAI"):
            provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_direct_openai_without_key_fails(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with pytest.raises(EmbeddingConfigurationError, match="OPENAI_API_KEY"):
            build_embedding_provider(get_embedding_settings())

    def test_gateway_without_key_succeeds(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://gateway:8080/v1")
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with patch("openai.OpenAI"):
            provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_gateway_with_optional_key_succeeds(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "optional-key")
        monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://gateway:8080/v1")
        monkeypatch.setenv("EMBEDDING_DIMENSION", str(EMBEDDING_DIMENSIONS))

        with patch("openai.OpenAI"):
            provider = build_embedding_provider(get_embedding_settings())

        assert isinstance(provider, OpenAIEmbeddingProvider)
