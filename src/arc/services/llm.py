"""Configurable, provider-agnostic LLM abstraction (Unified Intelligence).

The abstraction must not hard-code any production provider (OpenRouter,
OmniRoute, OpenAI, or any other). Production LLM provider/model selection
is a deferred decision (ADR-001: exact AI model remains open; TRD 34:
OpenRouter is the primary configurable AI provider and the model must
remain configurable). This foundation ships with a deterministic local
provider that is suitable for service and API tests.

Provider selection is environment-driven (``LLM_PROVIDER`` /
``LLM_MODEL``, documented in ``.env.example``) and fails closed: an
unknown provider or an invalid configuration raises
``LlmConfigurationError`` before any service is built.

The LLM is NOT the authorization system (TRD 10.3, ADR-001): providers
receive only the prompt text assembled by UnifiedIntelligenceService
exclusively from the Approved Context Contract (sanitized content and
citation references). They never receive repository access, vectors, raw
documents, or authorization state.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


class LlmError(Exception):
    """Raised when an LLM provider cannot complete a request.

    LLM failures are fail-closed: no partial or misleading answer is
    produced and nothing is persisted.
    """


class LlmConfigurationError(Exception):
    """Raised when the LLM configuration is missing or invalid.

    Configuration failures fail closed: the application refuses to start
    with an unsupported provider or an invalid value.
    """


@runtime_checkable
class LlmProvider(Protocol):
    """Provider-agnostic LLM completion interface.

    Implementations receive a single deterministic prompt string and
    return a completion string. Production providers are deferred; the
    deterministic provider makes the reasoning contract testable and
    CI-safe without any external API, key, or network access.
    """

    def complete(self, prompt: str) -> str:
        """Return the completion for ``prompt``."""
        ...


class DeterministicLlmProvider:
    """Local, deterministic LLM provider for development and tests.

    This is NOT a production model. It returns a deterministic summary of
    the approved context items cited in the prompt (``[n] citation:
    <reference>`` lines), which makes the retrieval-to-reasoning contract
    verifiable: the completion always reflects exactly the approved
    context that was supplied, nothing more.
    """

    def __init__(self):
        self._citation_pattern = re.compile(r"^\[\d+\] citation:\s+(\S+)")

    def complete(self, prompt: str) -> str:
        """Return a deterministic completion derived from the prompt."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")
        citations = [
            match
            for match in (self._citation_pattern.match(line) for line in prompt.splitlines())
            if match
        ]
        references = [citation.group(1) for citation in citations]
        if references:
            return (
                f"Deterministic response using {len(references)} approved context "
                f"item(s): {', '.join(references)}"
            )
        return "Deterministic response using 0 approved context item(s)."


@dataclass(frozen=True)
class LlmSettings:
    """LLM configuration derived from the environment.

    ``provider`` selects the LLM implementation. Only ``deterministic``
    is currently supported; any other value fails closed at
    configuration time (a production provider such as OpenRouter is a
    deferred decision, not silently substituted). ``model`` is metadata
    for future providers and has no effect on the deterministic provider.
    """

    provider: str = "deterministic"
    model: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise LlmConfigurationError("LLM_PROVIDER must not be empty")


def get_llm_settings() -> LlmSettings:
    """Build LLM settings from the environment.

    Defaults to the deterministic provider so the application runs
    without configuration while keeping the configuration explicit.
    """
    return LlmSettings(
        provider=os.getenv("LLM_PROVIDER", "deterministic"),
        model=os.getenv("LLM_MODEL") or None,
    )


def build_llm_provider(settings: LlmSettings) -> LlmProvider:
    """Build the configured LLM provider.

    Raises:
        LlmConfigurationError: for any provider other than
            ``deterministic``. Fail closed: a production provider is a
            deferred decision and must never be silently substituted.
    """
    if settings.provider == "deterministic":
        return DeterministicLlmProvider()
    raise LlmConfigurationError(
        f"Unsupported LLM_PROVIDER: {settings.provider!r} "
        "(supported providers: deterministic; a production provider is a deferred decision)"
    )
