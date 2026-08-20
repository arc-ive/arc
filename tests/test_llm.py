"""Unit tests for the LLM abstraction and deterministic provider.

The deterministic provider is the approved development/test implementation
of the configurable, provider-agnostic ``LlmProvider`` interface. A
production LLM provider (OpenRouter primary per TRD 34; exact model a
deferred decision) must not be silently substituted.
"""

import pytest

from arc.services.llm import (
    DeterministicLlmProvider,
    LlmConfigurationError,
    LlmProvider,
    build_llm_provider,
    get_llm_settings,
)


def _prompt_with_citations(*references):
    lines = ["APPROVED CONTEXT:"]
    for index, reference in enumerate(references, start=1):
        lines.append(f"[{index}] citation: {reference}")
        lines.append("approved content text")
    lines.append("QUERY: remote work policy")
    return "\n".join(lines)


class TestDeterministicLlmProvider:
    def test_completion_is_deterministic(self):
        provider = DeterministicLlmProvider()
        prompt = _prompt_with_citations("doc-1#c0", "doc-2#c1")
        assert provider.complete(prompt) == provider.complete(prompt)

    def test_completion_cites_exactly_the_approved_context(self):
        provider = DeterministicLlmProvider()
        prompt = _prompt_with_citations("doc-1#c0", "doc-2#c1")
        completion = provider.complete(prompt)
        assert "doc-1#c0" in completion
        assert "doc-2#c1" in completion
        assert "deterministic" in completion.lower()

    def test_completion_does_not_echo_content(self):
        provider = DeterministicLlmProvider()
        prompt = _prompt_with_citations("doc-1#c0")
        completion = provider.complete(prompt)
        # The deterministic provider cites references but never echoes the
        # approved content itself.
        assert "approved content text" not in completion

    def test_prompt_without_citations_reports_zero_items(self):
        provider = DeterministicLlmProvider()
        completion = provider.complete("QUERY: anything")
        assert "0 approved context item(s)" in completion

    def test_empty_prompt_is_rejected(self):
        provider = DeterministicLlmProvider()
        with pytest.raises(ValueError):
            provider.complete("")
        with pytest.raises(ValueError):
            provider.complete("   ")


class TestLlmProviderContract:
    def test_deterministic_provider_satisfies_the_contract(self):
        assert isinstance(DeterministicLlmProvider(), LlmProvider)


class TestLlmSettings:
    def test_defaults_are_the_deterministic_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        settings = get_llm_settings()

        assert settings.provider == "deterministic"
        assert settings.model is None

    def test_environment_values_are_read(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "deterministic")
        monkeypatch.setenv("LLM_MODEL", "local-test")

        settings = get_llm_settings()

        assert settings.provider == "deterministic"
        assert settings.model == "local-test"

    def test_empty_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "  ")

        with pytest.raises(LlmConfigurationError):
            get_llm_settings()


class TestLlmProviderFactory:
    def test_deterministic_provider_is_built_from_settings(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)

        provider = build_llm_provider(get_llm_settings())

        assert isinstance(provider, DeterministicLlmProvider)

    def test_unknown_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")

        with pytest.raises(LlmConfigurationError):
            build_llm_provider(get_llm_settings())
