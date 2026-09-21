"""Configurable, provider-agnostic LLM abstraction (Unified Intelligence).

Provider selection is environment-driven (``LLM_PROVIDER`` /
``LLM_MODEL``, documented in ``.env.example``) and fails closed: an
unknown provider or an invalid configuration raises
``LlmConfigurationError`` before any service is built.

The LLM is NOT the authorization system (TRD 10.3, ADR-001): providers
receive only the prompt text assembled by UnifiedIntelligenceService
exclusively from the Approved Context Contract (sanitized content and
citation references). They never receive repository access, vectors, raw
documents, or authorization state.

V2-ADR-006: production routing is Arc -> OmniRoute -> OpenRouter ->
configured model. Provider protocols remain a domain abstraction; the
OpenRouter provider is one concrete implementation.
"""

import json
import os
import random
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

import httpx


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


class LlmRetryableError(LlmError):
    """Raised for transient LLM failures that are safe to retry.

    Subclass of ``LlmError`` so callers that catch ``LlmError`` still
    see transient failures. The retry loop in ``OpenRouterProvider._post``
    catches this specifically to decide whether to retry.
    """


@runtime_checkable
class LlmProvider(Protocol):
    """Provider-agnostic LLM completion interface.

    Implementations receive a single deterministic prompt string and
    return a completion string. The deterministic provider makes the
    reasoning contract testable and CI-safe without any external API,
    key, or network access. The OpenRouter provider is the production
    implementation (V2-ADR-006).

    ``last_usage`` exposes raw provider usage data from the most recent
    request (V2-ADR-006, TRD 13). Production providers capture token
    counts and latency; the deterministic provider returns ``None``.
    Downstream telemetry (Issue #141) consumes this data for persistence,
    cost accounting, and dashboards.
    """

    @property
    def last_usage(self) -> Optional["LlmUsageReport"]:
        """Usage data from the most recent request, or ``None``."""
        ...

    def complete(self, prompt: str) -> str:
        """Return the completion for ``prompt``."""
        ...


@runtime_checkable
class ToolProposingLlm(Protocol):
    """Optional ADR-004 capability: emit ONE raw tool proposal.

    Implementations return untrusted raw output (a mapping that must still
    pass strict ``ToolProposal.parse`` validation in the domain layer) or
    ``None`` when no tool is proposed. Returning a proposal is NOT
    authorization: the application alone resolves, authorizes, validates,
    and executes through ``ToolExecutionService``.
    """

    def propose_tool(
        self, query: str, context_references: Sequence[str]
    ) -> Optional[Mapping[str, Any]]:
        """Return raw untrusted proposal output, or ``None``."""
        ...


@runtime_checkable
class SkillSelectingLlm(Protocol):
    """Optional Agent capability (ADR-006): propose the next bounded step.

    Implementations receive the user's goal and a snapshot of the trusted
    tenant's Skill catalog and return UNTRUSTED raw decision output (a
    mapping that must still pass strict ``AgentDecision.parse`` validation
    in the domain layer) or ``None`` when the Agent should stop. Returning
    a decision is NOT authorization: the application alone validates
    catalog containment, executes exclusively through
    ``SkillExecutionService``, and enforces every tool-layer control.
    """

    def propose_skill(
        self, goal: str, catalog: Sequence[Mapping[str, Any]]
    ) -> Optional[Mapping[str, Any]]:
        """Return raw untrusted decision output for ``goal``, or ``None``."""
        ...


class DeterministicLlmProvider:
    """Local, deterministic LLM provider for development and tests.

    This is NOT a production model. It returns a deterministic summary of
    the approved context items cited in the prompt (``[n] citation:
    <reference>`` lines), which makes the retrieval-to-reasoning contract
    verifiable: the completion always reflects exactly the approved
    context that was supplied, nothing more.

    ADR-004 V1: an OPTIONAL ``tool_proposal_script`` callable may be
    injected (tests/demo wiring only) to make :meth:`propose_tool`
    return a deterministic raw proposal for a given query. When not
    armed — the production default — no proposal is ever emitted.
    The script receives the user query; its output remains UNTRUSTED and
    must pass strict domain validation before anything executes.

    ADR-006 V1: an OPTIONAL ``skill_decision_script`` callable may be
    injected the same way for :meth:`propose_skill`. When not armed —
    the production default — the Agent capability is unavailable and
    every Agent run fails closed without executing any Skill. The script
    receives ``(goal, catalog_snapshot)``; its output remains UNTRUSTED
    and must pass strict domain validation before anything executes.
    """

    def __init__(
        self,
        tool_proposal_script: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
        skill_decision_script: Optional[
            Callable[[str, Sequence[Mapping[str, Any]]], Optional[Mapping[str, Any]]]
        ] = None,
    ):
        self._citation_pattern = re.compile(r"^\[\d+\] citation:\s+(\S+)")
        self._tool_proposal_script = tool_proposal_script
        self._skill_decision_script = skill_decision_script

    @property
    def last_usage(self) -> Optional["LlmUsageReport"]:
        """Always ``None`` — the deterministic provider has no real provider usage."""
        return None

    def propose_tool(
        self, query: str, context_references: Sequence[str] = ()
    ) -> Optional[Mapping[str, Any]]:
        """Return the scripted raw proposal for ``query``, or ``None``."""
        if self._tool_proposal_script is None:
            return None
        return self._tool_proposal_script(query)

    def propose_skill(
        self, goal: str, catalog: Sequence[Mapping[str, Any]] = ()
    ) -> Optional[Mapping[str, Any]]:
        """Return the scripted raw decision for ``goal``, or ``None``."""
        if self._skill_decision_script is None:
            return None
        return self._skill_decision_script(goal, list(catalog))

    @property
    def skill_decision_capable(self) -> bool:
        """Whether an Agent decision capability is actually configured.

        The protocol method always exists on this provider, so callers
        must consult this flag to distinguish an armed decision capability
        from the fail-closed production default (ADR-006).
        """
        return self._skill_decision_script is not None

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
class LlmUsageReport:
    """Raw provider usage data captured from a single LLM request.

    This is the minimum data contract that enables downstream usage
    telemetry (V2-ADR-024, Issue #141). The provider captures and
    exposes this data; persistence and observability are handled by
    the caller.

    ``latency_ms`` measures the wall-clock time of a single HTTP attempt
    (request to response), not the total operation time which may include
    retries and exponential backoff. This matches the per-attempt
    granularity expected by downstream telemetry.
    """

    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


# Per-call usage ContextVar for concurrency-safe usage attribution.
# The OpenRouterProvider is a process-wide singleton shared by concurrent
# requests. _last_usage is mutable instance state that can be overwritten
# by a concurrent request before the original caller reads it. This
# ContextVar stores usage per-async-context, preventing cross-request
# contamination. Production callers (intelligence.py, agent.py) read
# from here. provider.last_usage is kept for backward compatibility.
_current_llm_usage: ContextVar[Optional[LlmUsageReport]] = ContextVar("llm_usage", default=None)


_OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_TIMEOUT = httpx.Timeout(60.0)
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 0.5
_DEFAULT_MAX_DELAY = 4.0


class OpenRouterProvider:
    """Production LLM provider via OpenRouter / OmniRoute (V2-ADR-006).

    Implements all three LLM protocols (``LlmProvider``,
    ``ToolProposingLlm``, ``SkillSelectingLlm``) by calling the
    OpenAI-compatible chat completions endpoint exposed by OpenRouter.

    Routing: Arc -> OmniRoute -> OpenRouter -> configured model.
    The provider never receives repository access, vectors, raw
    documents, or authorization state (TRD 10.3, ADR-001).

    Bounded retry (V2-ADR-006): transient/retry-safe failures (429,
    5xx, timeouts, connection errors) are retried with exponential
    backoff up to ``max_retries`` attempts. Permanent failures (401,
    403, other 4xx) and application errors (no choices) fail
    immediately without retry.

    Structured output validation (V2-ADR-006): ``propose_tool`` and
    ``propose_skill`` perform lightweight structural validation of
    the raw model output before returning it. The domain layer
    (``ToolProposal.parse``, ``AgentDecision.parse``) retains full
    strict validation. Malformed output never reaches tool/skill
    execution as a valid decision.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = _OPENROUTER_DEFAULT_BASE_URL,
        timeout: httpx.Timeout = _OPENROUTER_DEFAULT_TIMEOUT,
        client: Optional[httpx.Client] = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_delay: float = _DEFAULT_BASE_DELAY,
        max_delay: float = _DEFAULT_MAX_DELAY,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LlmConfigurationError("OPENROUTER_API_KEY must not be empty")
        if not model or not model.strip():
            raise LlmConfigurationError("LLM_MODEL must not be empty when using OpenRouter")
        if max_retries < 0:
            raise LlmConfigurationError("max_retries must be non-negative")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._last_usage: Optional[LlmUsageReport] = None

    @property
    def last_usage(self) -> Optional[LlmUsageReport]:
        """Usage data from the most recent request, or ``None``."""
        return self._last_usage

    def _execute_request(self, client: httpx.Client, url: str, body: dict, headers: dict) -> str:
        """Execute a single HTTP request and return assistant content.

        Captures usage data (tokens) and latency from the API response.
        Raises ``LlmConfigurationError`` for permanent auth failures,
        ``LlmRetryableError`` for transient failures (empty choices, rate
        limits, 5xx, timeouts), and ``LlmError`` for other errors. Never
        retries — the caller ``_post`` handles bounded retry.

        Lifecycle: the per-call ContextVar ``_current_llm_usage`` is
        **cleared before** the HTTP call so that stale usage from a
        prior call is never accidentally consumed.  On a successful
        response the ContextVar is set to the new usage report.  If the
        call raises, the ContextVar remains ``None`` — callers observe
        no usage from a failed call.
        """
        _current_llm_usage.set(None)
        started = time.monotonic()
        response = client.post(url, json=body, headers=headers)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _raise_for_status(response)
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise LlmRetryableError(
                f"OpenRouter returned no choices for model {self._model!r}"
            )
        # Capture usage data from the response (V2-ADR-006, TRD 13).
        usage = data.get("usage") or {}
        report = LlmUsageReport(
            provider="openrouter",
            model=self._model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=elapsed_ms,
        )
        self._last_usage = report
        _current_llm_usage.set(report)
        return choices[0]["message"]["content"]

    def _post(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """POST to the chat completions endpoint with bounded retry.

        Transient failures (429, 5xx, timeouts, connection errors, empty
        choices) are retried up to ``max_retries`` times with exponential
        backoff. Permanent failures (401, 403, other 4xx) and application
        errors fail immediately.
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            **kwargs,
        }

        owned_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout)
        last_error: Optional[Exception] = None
        try:
            for attempt in range(1 + self._max_retries):
                try:
                    return self._execute_request(client, url, body, headers)
                except LlmConfigurationError:
                    raise
                except LlmRetryableError as exc:
                    last_error = exc
                    if attempt < self._max_retries:
                        delay = min(
                            self._max_delay,
                            self._base_delay * (2**attempt) + random.uniform(0, self._base_delay),
                        )
                        time.sleep(delay)
                        continue
                except LlmError:
                    raise
                except httpx.TimeoutException as exc:
                    last_error = LlmRetryableError(f"OpenRouter request timed out: {exc}")
                    if attempt < self._max_retries:
                        delay = min(
                            self._max_delay,
                            self._base_delay * (2**attempt) + random.uniform(0, self._base_delay),
                        )
                        time.sleep(delay)
                        continue
                except httpx.HTTPError as exc:
                    last_error = LlmRetryableError(f"OpenRouter HTTP error: {exc}")
                    if attempt < self._max_retries:
                        delay = min(
                            self._max_delay,
                            self._base_delay * (2**attempt) + random.uniform(0, self._base_delay),
                        )
                        time.sleep(delay)
                        continue
            raise last_error  # type: ignore[misc]
        finally:
            if owned_client:
                client.close()

    # -- LlmProvider -------------------------------------------------------

    def complete(self, prompt: str) -> str:
        """Return the completion for ``prompt``."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")
        return self._post([{"role": "user", "content": prompt}])

    # -- ToolProposingLlm ---------------------------------------------------

    def propose_tool(
        self, query: str, context_references: Sequence[str] = ()
    ) -> Optional[Mapping[str, Any]]:
        """Return raw untrusted proposal output, or ``None``.

        Performs structural validation matching ``ToolProposal.parse``: a
        valid tool proposal must be a JSON object with exactly the keys
        ``tool_name`` (non-empty string) and ``arguments`` (mapping).
        Extra or missing keys return ``None``. The domain layer retains
        full strict validation including length limits and value-type
        checks.
        """
        prompt = _build_tool_proposal_prompt(query)
        raw = self._post([{"role": "user", "content": prompt}])
        parsed = _parse_json_response(raw)
        if parsed is not None and not _validate_tool_proposal(parsed):
            return None
        return parsed

    # -- SkillSelectingLlm --------------------------------------------------

    def propose_skill(
        self, goal: str, catalog: Sequence[Mapping[str, Any]] = ()
    ) -> Optional[Mapping[str, Any]]:
        """Return raw untrusted decision output for ``goal``, or ``None``.

        Performs structural validation matching ``AgentDecision.parse``: a
        valid skill decision must be a JSON object with exactly the keys
        ``skill_id`` (non-empty string), ``tool_calls`` (list), and
        ``satisfied_preconditions`` (list). Extra or missing keys return
        ``None``. The domain layer retains full strict validation
        including element-type checks and length limits.
        """
        prompt = _build_skill_proposal_prompt(goal, list(catalog))
        raw = self._post([{"role": "user", "content": prompt}])
        parsed = _parse_json_response(raw)
        if parsed is not None and not _validate_skill_proposal(parsed):
            return None
        return parsed


def _raise_for_status(response: httpx.Response) -> None:
    """Translate HTTP errors into domain exceptions.

    Retryable transient failures (429, 5xx) raise ``LlmRetryableError``.
    Permanent failures (401, 403, other 4xx) raise ``LlmError`` or
    ``LlmConfigurationError`` and must never be retried.
    """
    if response.status_code == 200:
        return
    if response.status_code in (401, 403):
        raise LlmConfigurationError(
            f"OpenRouter authentication failed (HTTP {response.status_code}): "
            "check OPENROUTER_API_KEY"
        )
    if response.status_code == 429:
        raise LlmRetryableError("OpenRouter rate limit exceeded (HTTP 429)")
    if response.status_code >= 500:
        raise LlmRetryableError(f"OpenRouter server error (HTTP {response.status_code})")
    raise LlmError(f"OpenRouter error (HTTP {response.status_code})")


def _parse_json_response(raw: str) -> Optional[Mapping[str, Any]]:
    """Best-effort extraction of a JSON object from LLM output.

    Returns ``None`` when the response is not a valid JSON object, which
    is the correct fail-closed behavior: no proposal is emitted.
    """
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


_TOOL_PROPOSAL_KEYS = frozenset({"tool_name", "arguments"})


def _validate_tool_proposal(raw: Mapping[str, Any]) -> bool:
    """Structural check for a tool proposal matching ``ToolProposal.parse``.

    A valid proposal must have exactly the keys ``tool_name`` (non-empty
    string) and ``arguments`` (mapping). Extra or missing keys are
    rejected. The domain layer (``ToolProposal.parse``) retains full
    strict validation including length limits and value-type checks.
    """
    if set(raw.keys()) != _TOOL_PROPOSAL_KEYS:
        return False
    tool_name = raw.get("tool_name")
    arguments = raw.get("arguments")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return False
    if not isinstance(arguments, dict):
        return False
    return True


_SKILL_PROPOSAL_KEYS = frozenset({"skill_id", "tool_calls", "satisfied_preconditions"})


def _validate_skill_proposal(raw: Mapping[str, Any]) -> bool:
    """Structural check for a skill decision matching ``AgentDecision.parse``.

    A valid decision must have exactly the keys ``skill_id`` (non-empty
    string), ``tool_calls`` (list), and ``satisfied_preconditions`` (list).
    Extra or missing keys are rejected. The domain layer
    (``AgentDecision.parse``) retains full strict validation including
    element-type checks and length limits.
    """
    if set(raw.keys()) != _SKILL_PROPOSAL_KEYS:
        return False
    skill_id = raw.get("skill_id")
    tool_calls = raw.get("tool_calls")
    preconditions = raw.get("satisfied_preconditions")
    if not isinstance(skill_id, str) or not skill_id.strip():
        return False
    if not isinstance(tool_calls, list):
        return False
    if not isinstance(preconditions, list):
        return False
    return True


def _build_tool_proposal_prompt(query: str) -> str:
    """Build a prompt that asks the LLM to propose a tool action."""
    return (
        "You are an AI assistant that proposes tool actions when appropriate.\n"
        "Given the user query below, decide whether a tool action is needed.\n"
        "If yes, return EXACTLY a JSON object with keys 'tool_name' and 'arguments'.\n"
        "If no tool is appropriate, return exactly the string NONE.\n\n"
        "Available tools: check_service_health (checks health of an external service)\n\n"
        f"User query: {query}\n\n"
        "Response (JSON object or NONE):"
    )


def _build_skill_proposal_prompt(goal: str, catalog: list[Mapping[str, Any]]) -> str:
    """Build a prompt that asks the LLM to select a Skill from the catalog.

    The prompt asks for the exact keys expected by ``_validate_skill_proposal``
    and ``AgentDecision.parse``: ``skill_id``, ``tool_calls``, and
    ``satisfied_preconditions``.
    """
    catalog_text = json.dumps(catalog, indent=2) if catalog else "[]"
    return (
        "You are an AI agent that selects the next bounded step (Skill) "
        "to accomplish a goal.\n"
        "Given the goal and the available Skill catalog below, decide "
        "whether a Skill should be executed.\n"
        "If yes, return EXACTLY a JSON object with keys:\n"
        "  - 'skill_id': the Skill's id from the catalog\n"
        "  - 'tool_calls': list of tool call objects the Skill should invoke\n"
        "  - 'satisfied_preconditions': list of precondition strings that are met\n"
        "If no Skill is appropriate, return exactly the string NONE.\n\n"
        f"Goal: {goal}\n\n"
        f"Available Skills:\n{catalog_text}\n\n"
        "Response (JSON object or NONE):"
    )


@dataclass(frozen=True)
class LlmSettings:
    """LLM configuration derived from the environment.

    ``provider`` selects the LLM implementation. Supported values:
    ``deterministic`` (development/tests) and ``openrouter``
    (production, V2-ADR-006). Unknown values fail closed at
    configuration time.
    """

    provider: str = "deterministic"
    model: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = _OPENROUTER_DEFAULT_BASE_URL

    def __post_init__(self) -> None:
        if not self.provider or not self.provider.strip():
            raise LlmConfigurationError("LLM_PROVIDER must not be empty")
        if self.provider == "openrouter":
            if not self.api_key or not self.api_key.strip():
                raise LlmConfigurationError(
                    "OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter"
                )
            if not self.model or not self.model.strip():
                raise LlmConfigurationError("LLM_MODEL is required when LLM_PROVIDER=openrouter")


def get_llm_settings() -> LlmSettings:
    """Build LLM settings from the environment.

    Defaults to the deterministic provider so the application runs
    without configuration while keeping the configuration explicit.
    """
    return LlmSettings(
        provider=os.getenv("LLM_PROVIDER", "deterministic"),
        model=os.getenv("LLM_MODEL") or None,
        api_key=os.getenv("OPENROUTER_API_KEY") or None,
        base_url=os.getenv("OMNIROUTE_BASE_URL") or _OPENROUTER_DEFAULT_BASE_URL,
    )


def build_llm_provider(settings: LlmSettings) -> LlmProvider:
    """Build the configured LLM provider.

    Raises:
        LlmConfigurationError: for unknown providers or missing required
            configuration. Fail closed: a production provider is never
            silently substituted.
    """
    if settings.provider == "deterministic":
        return DeterministicLlmProvider()
    if settings.provider == "openrouter":
        return OpenRouterProvider(
            api_key=settings.api_key,  # type: ignore[arg-type]
            model=settings.model,  # type: ignore[arg-type]
            base_url=settings.base_url,
        )
    raise LlmConfigurationError(
        f"Unsupported LLM_PROVIDER: {settings.provider!r} "
        "(supported providers: deterministic, openrouter)"
    )
