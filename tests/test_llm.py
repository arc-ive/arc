"""Unit tests for the LLM abstraction and providers.

The deterministic provider is the approved development/test implementation
of the configurable, provider-agnostic ``LlmProvider`` interface. The
OpenRouter provider (V2-ADR-006) is the production implementation.
"""

import json

import httpx
import pytest

from arc.services.llm import (
    DeterministicLlmProvider,
    LlmConfigurationError,
    LlmError,
    LlmProvider,
    LlmRetryableError,
    LlmUsageReport,
    OpenRouterProvider,
    SkillSelectingLlm,
    ToolProposingLlm,
    _build_skill_proposal_prompt,
    _parse_json_response,
    _validate_skill_proposal,
    _validate_tool_proposal,
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

    def test_deterministic_provider_last_usage_is_none(self):
        provider = DeterministicLlmProvider()
        assert provider.last_usage is None

    def test_last_usage_accessible_through_protocol(self):
        provider: LlmProvider = DeterministicLlmProvider()
        assert provider.last_usage is None


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


# ---------------------------------------------------------------------------
# OpenRouter provider tests
# ---------------------------------------------------------------------------


def _openrouter_handler(response_body: dict, status: int = 200):
    """Return an httpx.MockTransport handler that returns a chat completion."""

    def handler(request):
        assert "Bearer test-api-key" in request.headers.get("authorization", "")
        return httpx.Response(status, json=response_body)

    return handler


def _make_provider(handler, model: str = "test-model") -> OpenRouterProvider:
    """Build an OpenRouterProvider with a mock HTTP transport."""
    transport = httpx.MockTransport(handler)
    return OpenRouterProvider(
        api_key="test-api-key",
        model=model,
        client=httpx.Client(transport=transport),
    )


def _chat_response(content: str) -> dict:
    """Build a minimal OpenAI-compatible chat completion response."""
    return {"choices": [{"message": {"content": content}}]}


class TestOpenRouterProviderInit:
    def test_missing_api_key_fails_closed(self):
        with pytest.raises(LlmConfigurationError, match="OPENROUTER_API_KEY"):
            OpenRouterProvider(api_key="", model="test-model")

    def test空白_api_key_fails_closed(self):
        with pytest.raises(LlmConfigurationError, match="OPENROUTER_API_KEY"):
            OpenRouterProvider(api_key="   ", model="test-model")

    def test_missing_model_fails_closed(self):
        with pytest.raises(LlmConfigurationError, match="LLM_MODEL"):
            OpenRouterProvider(api_key="key", model="")

    def test空白_model_fails_closed(self):
        with pytest.raises(LlmConfigurationError, match="LLM_MODEL"):
            OpenRouterProvider(api_key="key", model="  ")

    def test_valid_initialization(self):
        provider = OpenRouterProvider(api_key="key", model="m")
        assert provider._api_key == "key"
        assert provider._model == "m"


class TestOpenRouterProviderProtocolCompliance:
    def test_satisfies_llm_provider(self):
        provider = OpenRouterProvider(api_key="k", model="m")
        assert isinstance(provider, LlmProvider)

    def test_satisfies_tool_proposing_llm(self):
        provider = OpenRouterProvider(api_key="k", model="m")
        assert isinstance(provider, ToolProposingLlm)

    def test_satisfies_skill_selecting_llm(self):
        provider = OpenRouterProvider(api_key="k", model="m")
        assert isinstance(provider, SkillSelectingLlm)

    def test_last_usage_accessible_through_llm_provider_protocol(self):
        provider: LlmProvider = OpenRouterProvider(api_key="k", model="m")
        assert provider.last_usage is None


class TestOpenRouterProviderComplete:
    def test_complete_returns_content(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("Hello world")))
        assert provider.complete("test prompt") == "Hello world"

    def test_complete_empty_prompt_rejected(self):
        provider = _make_provider(lambda r: httpx.Response(200, json={}))
        with pytest.raises(ValueError):
            provider.complete("")
        with pytest.raises(ValueError):
            provider.complete("   ")

    def test_complete_no_choices_raises(self):
        provider = _make_provider(lambda r: httpx.Response(200, json={"choices": []}))
        with pytest.raises(LlmError, match="no choices"):
            provider.complete("prompt")

    def test_complete_sends_correct_request(self):
        captured = {}

        def handler(request):
            captured["body"] = request.content
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler)
        provider.complete("test prompt")
        body = json.loads(captured["body"])
        assert body["model"] == "test-model"
        assert body["messages"] == [{"role": "user", "content": "test prompt"}]


class TestOpenRouterProviderErrors:
    def test_401_raises_configuration_error(self):
        provider = _make_provider(lambda r: httpx.Response(401, json={"error": "unauthorized"}))
        with pytest.raises(LlmConfigurationError, match="authentication failed"):
            provider.complete("prompt")

    def test_403_raises_configuration_error(self):
        provider = _make_provider(lambda r: httpx.Response(403, json={"error": "forbidden"}))
        with pytest.raises(LlmConfigurationError, match="authentication failed"):
            provider.complete("prompt")

    def test_429_raises_rate_limit_error(self):
        provider = _make_provider(lambda r: httpx.Response(429, json={"error": "rate limited"}))
        with pytest.raises(LlmError, match="rate limit"):
            provider.complete("prompt")

    def test_500_raises_server_error(self):
        provider = _make_provider(lambda r: httpx.Response(500, json={"error": "internal"}))
        with pytest.raises(LlmError, match="server error"):
            provider.complete("prompt")

    def test_400_raises_generic_error(self):
        provider = _make_provider(lambda r: httpx.Response(400, json={"error": "bad request"}))
        with pytest.raises(LlmError, match="HTTP 400"):
            provider.complete("prompt")

    def test_timeout_raises_error(self):
        def handler(request):
            raise httpx.ReadTimeout("read timed out")

        provider = _make_provider(handler)
        with pytest.raises(LlmError, match="timed out"):
            provider.complete("prompt")

    def test_connect_error_raises_error(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        provider = _make_provider(handler)
        with pytest.raises(LlmError, match="HTTP error"):
            provider.complete("prompt")


class TestOpenRouterProviderProposeTool:
    def test_returns_parsed_json_proposal(self):
        proposal = {
            "tool_name": "check_service_health",
            "arguments": {"url": "https://example.com"},
        }
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps(proposal)))
        )
        result = provider.propose_tool("check example.com health")
        assert result == proposal

    def test_returns_none_for_none_response(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("NONE")))
        assert provider.propose_tool("query") is None

    def test_returns_none_for_malformed_json(self):
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response("not json at all"))
        )
        assert provider.propose_tool("query") is None

    def test_returns_none_for_non_dict_json(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("[1, 2, 3]")))
        assert provider.propose_tool("query") is None

    def test_strips_markdown_code_fences(self):
        proposal = {"tool_name": "check_service_health", "arguments": {}}
        fenced = f"```json\n{json.dumps(proposal)}\n```"
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response(fenced)))
        result = provider.propose_tool("query")
        assert result == proposal


class TestOpenRouterProviderProposeSkill:
    def test_returns_parsed_json_decision(self):
        decision = {
            "skill_id": "summarize-001",
            "tool_calls": [{"tool": "summarize", "args": {"text": "hello"}}],
            "satisfied_preconditions": [],
        }
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps(decision)))
        )
        result = provider.propose_skill("summarize the text", [{"name": "summarize"}])
        assert result == decision

    def test_returns_none_for_none_response(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("NONE")))
        assert provider.propose_skill("goal", []) is None

    def test_returns_none_for_malformed_json(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("random text")))
        assert provider.propose_skill("goal", []) is None

    def test_sends_catalog_in_prompt(self):
        captured = {}

        def handler(request):
            captured["body"] = request.content
            return httpx.Response(200, json=_chat_response("NONE"))

        provider = _make_provider(handler)
        provider.propose_skill("goal", [{"name": "skill_a"}])
        body = json.loads(captured["body"])
        prompt = body["messages"][0]["content"]
        assert "skill_a" in prompt
        assert "goal" in prompt


class TestParseJsonResponse:
    def test_valid_json_object(self):
        assert _parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_json_with_whitespace(self):
        assert _parse_json_response('  {"key": "value"}  ') == {"key": "value"}

    def test_markdown_fenced_json(self):
        assert _parse_json_response('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_markdown_fenced_without_language(self):
        assert _parse_json_response('```\n{"key": "value"}\n```') == {"key": "value"}

    def test_non_dict_returns_none(self):
        assert _parse_json_response("[1, 2, 3]") is None

    def test_invalid_json_returns_none(self):
        assert _parse_json_response("not json") is None

    def test_empty_string_returns_none(self):
        assert _parse_json_response("") is None


class TestLlmSettingsOpenRouter:
    def test_openrouter_requires_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        with pytest.raises(LlmConfigurationError, match="OPENROUTER_API_KEY"):
            get_llm_settings()

    def test_openrouter_requires_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("LLM_MODEL", raising=False)

        with pytest.raises(LlmConfigurationError, match="LLM_MODEL"):
            get_llm_settings()

    def test_openrouter_reads_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OMNIROUTE_BASE_URL", "https://custom.proxy/v1")

        settings = get_llm_settings()

        assert settings.provider == "openrouter"
        assert settings.model == "gpt-4o"
        assert settings.api_key == "sk-test"
        assert settings.base_url == "https://custom.proxy/v1"

    def test_openrouter_base_url_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)

        settings = get_llm_settings()

        assert settings.base_url == "https://openrouter.ai/api/v1"


class TestBuildLlmProviderOpenRouter:
    def test_openrouter_provider_built_from_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        provider = build_llm_provider(get_llm_settings())

        assert isinstance(provider, OpenRouterProvider)

    def test_unknown_provider_fails_closed(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")

        with pytest.raises(LlmConfigurationError, match="Unsupported LLM_PROVIDER"):
            build_llm_provider(get_llm_settings())


# ---------------------------------------------------------------------------
# Bounded retry tests
# ---------------------------------------------------------------------------


class TestOpenRouterBoundedRetry:
    def test_transient_failure_retries_then_succeeds(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        result = provider.complete("prompt")
        assert result == "ok"
        assert call_count == 3

    def test_transient_failure_exhausts_retries(self):
        def handler(request):
            return httpx.Response(503, json={"error": "unavailable"})

        provider = _make_provider(handler, model="m")
        provider._max_retries = 2
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        with pytest.raises(LlmRetryableError, match="server error"):
            provider.complete("prompt")

    def test_permanent_failure_no_retry(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        with pytest.raises(LlmConfigurationError, match="authentication failed"):
            provider.complete("prompt")
        assert call_count == 1

    def test_403_no_retry(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, json={"error": "forbidden"})

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        with pytest.raises(LlmConfigurationError, match="authentication failed"):
            provider.complete("prompt")
        assert call_count == 1

    def test_400_no_retry(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, json={"error": "bad request"})

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        with pytest.raises(LlmError, match="HTTP 400"):
            provider.complete("prompt")
        assert call_count == 1

    def test_timeout_retries(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ReadTimeout("timed out")
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        result = provider.complete("prompt")
        assert result == "ok"
        assert call_count == 2

    def test_connection_error_retries(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        result = provider.complete("prompt")
        assert result == "ok"
        assert call_count == 2

    def test_500_retries(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(500, json={"error": "internal"})
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler, model="m")
        provider._max_retries = 3
        provider._base_delay = 0.0
        provider._max_delay = 0.0
        result = provider.complete("prompt")
        assert result == "ok"
        assert call_count == 2

    def test_zero_retries_configurable(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, json={"error": "rate limited"})

        provider = _make_provider(handler, model="m")
        provider._max_retries = 0
        with pytest.raises(LlmRetryableError):
            provider.complete("prompt")
        assert call_count == 1

    def test_max_retries_negative_fails_closed(self):
        with pytest.raises(LlmConfigurationError, match="max_retries"):
            OpenRouterProvider(api_key="k", model="m", max_retries=-1)


# ---------------------------------------------------------------------------
# Structured output validation tests
# ---------------------------------------------------------------------------


class TestValidateToolProposal:
    def test_valid_proposal(self):
        assert _validate_tool_proposal(
            {"tool_name": "check_health", "arguments": {"url": "https://x.com"}}
        )

    def test_missing_tool_name(self):
        assert not _validate_tool_proposal({"arguments": {}})

    def test_empty_tool_name(self):
        assert not _validate_tool_proposal({"tool_name": "", "arguments": {}})

    def test_whitespace_tool_name(self):
        assert not _validate_tool_proposal({"tool_name": "  ", "arguments": {}})

    def test_tool_name_not_string(self):
        assert not _validate_tool_proposal({"tool_name": 123, "arguments": {}})

    def test_missing_arguments(self):
        assert not _validate_tool_proposal({"tool_name": "x"})

    def test_arguments_not_dict(self):
        assert not _validate_tool_proposal({"tool_name": "x", "arguments": "bad"})

    def test_extra_keys_are_rejected(self):
        assert not _validate_tool_proposal({"tool_name": "x", "arguments": {}, "extra": True})

    def test_extra_keys_with_all_required_rejected(self):
        assert not _validate_tool_proposal(
            {"tool_name": "x", "arguments": {}, "reasoning": "because"}
        )


class TestValidateSkillProposal:
    def test_valid_decision(self):
        assert _validate_skill_proposal(
            {
                "skill_id": "s1",
                "tool_calls": [{"tool": "t"}],
                "satisfied_preconditions": ["p1"],
            }
        )

    def test_missing_skill_id(self):
        assert not _validate_skill_proposal({"tool_calls": [], "satisfied_preconditions": []})

    def test_empty_skill_id(self):
        assert not _validate_skill_proposal(
            {"skill_id": "", "tool_calls": [], "satisfied_preconditions": []}
        )

    def test_skill_id_not_string(self):
        assert not _validate_skill_proposal(
            {"skill_id": 123, "tool_calls": [], "satisfied_preconditions": []}
        )

    def test_missing_tool_calls(self):
        assert not _validate_skill_proposal({"skill_id": "s1", "satisfied_preconditions": []})

    def test_tool_calls_not_list(self):
        assert not _validate_skill_proposal(
            {"skill_id": "s1", "tool_calls": "bad", "satisfied_preconditions": []}
        )

    def test_missing_preconditions(self):
        assert not _validate_skill_proposal({"skill_id": "s1", "tool_calls": []})

    def test_preconditions_not_list(self):
        assert not _validate_skill_proposal(
            {"skill_id": "s1", "tool_calls": [], "satisfied_preconditions": "bad"}
        )

    def test_extra_keys_are_rejected(self):
        assert not _validate_skill_proposal(
            {
                "skill_id": "s1",
                "tool_calls": [],
                "satisfied_preconditions": [],
                "extra": True,
            }
        )

    def test_extra_keys_with_all_required_rejected(self):
        assert not _validate_skill_proposal(
            {
                "skill_id": "s1",
                "tool_calls": [],
                "satisfied_preconditions": [],
                "reasoning": "because",
            }
        )


class TestProposeToolValidation:
    def test_malformed_json_returns_none(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("not json")))
        assert provider.propose_tool("query") is None

    def test_json_without_tool_name_returns_none(self):
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps({"arguments": {}})))
        )
        assert provider.propose_tool("query") is None

    def test_json_without_arguments_returns_none(self):
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps({"tool_name": "x"})))
        )
        assert provider.propose_tool("query") is None

    def test_valid_proposal_passes_through(self):
        proposal = {"tool_name": "check_health", "arguments": {"url": "https://x.com"}}
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps(proposal)))
        )
        assert provider.propose_tool("query") == proposal

    def test_none_response_passes_through(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("NONE")))
        assert provider.propose_tool("query") is None


class TestProposeSkillValidation:
    def test_malformed_json_returns_none(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("random")))
        assert provider.propose_skill("goal", []) is None

    def test_json_without_skill_id_returns_none(self):
        provider = _make_provider(
            lambda r: httpx.Response(
                200,
                json=_chat_response(json.dumps({"tool_calls": [], "satisfied_preconditions": []})),
            )
        )
        assert provider.propose_skill("goal", []) is None

    def test_json_with_non_list_tool_calls_returns_none(self):
        provider = _make_provider(
            lambda r: httpx.Response(
                200,
                json=_chat_response(
                    json.dumps(
                        {"skill_id": "s1", "tool_calls": "bad", "satisfied_preconditions": []}
                    )
                ),
            )
        )
        assert provider.propose_skill("goal", []) is None

    def test_valid_decision_passes_through(self):
        decision = {
            "skill_id": "s1",
            "tool_calls": [{"tool": "t"}],
            "satisfied_preconditions": ["p1"],
        }
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps(decision)))
        )
        assert provider.propose_skill("goal", []) == decision

    def test_none_response_passes_through(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("NONE")))
        assert provider.propose_skill("goal", []) is None


class TestLlmRetryableError:
    def test_is_subclass_of_llm_error(self):
        assert issubclass(LlmRetryableError, LlmError)

    def test_catchable_as_llm_error(self):
        with pytest.raises(LlmError):
            raise LlmRetryableError("test")


# ---------------------------------------------------------------------------
# Skill proposal prompt contract tests
# ---------------------------------------------------------------------------


class TestSkillProposalPromptContract:
    def test_prompt_requests_skill_id_not_skill_name(self):
        """The prompt must ask for 'skill_id' to match AgentDecision.parse."""
        prompt = _build_skill_proposal_prompt("goal", [{"id": "s1", "name": "Skill1"}])
        assert "skill_id" in prompt
        assert "skill_name" not in prompt

    def test_prompt_requests_tool_calls_not_arguments(self):
        """The prompt must ask for 'tool_calls' to match AgentDecision.parse."""
        prompt = _build_skill_proposal_prompt("goal", [])
        assert "tool_calls" in prompt
        assert "'arguments'" not in prompt

    def test_prompt_requests_satisfied_preconditions(self):
        """The prompt must ask for 'satisfied_preconditions' to match AgentDecision.parse."""
        prompt = _build_skill_proposal_prompt("goal", [])
        assert "satisfied_preconditions" in prompt

    def test_prompt_contains_goal_and_catalog(self):
        catalog = [{"id": "s1", "name": "Skill1", "status": "active"}]
        prompt = _build_skill_proposal_prompt("deploy the service", catalog)
        assert "deploy the service" in prompt
        assert "Skill1" in prompt

    def test_prompt_handles_empty_catalog(self):
        prompt = _build_skill_proposal_prompt("goal", [])
        assert "[]" in prompt

    def test_propose_skill_with_correct_contract(self):
        """End-to-end: provider returns valid decision matching AgentDecision contract."""
        decision = {
            "skill_id": "summarize-001",
            "tool_calls": [{"tool": "summarize", "args": {"text": "hello"}}],
            "satisfied_preconditions": [],
        }
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_chat_response(json.dumps(decision)))
        )
        result = provider.propose_skill("summarize the text", [{"id": "summarize-001"}])
        assert result == decision
        assert "skill_id" in result
        assert "tool_calls" in result
        assert "satisfied_preconditions" in result


# ---------------------------------------------------------------------------
# Usage report and latency tests
# ---------------------------------------------------------------------------


class TestLlmUsageReport:
    def test_frozen_dataclass(self):
        report = LlmUsageReport(
            provider="openrouter",
            model="test-model",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            latency_ms=150,
        )
        assert report.provider == "openrouter"
        assert report.input_tokens == 10
        assert report.latency_ms == 150

    def test_optional_fields_default_none(self):
        report = LlmUsageReport(provider="openrouter", model="m")
        assert report.input_tokens is None
        assert report.output_tokens is None
        assert report.total_tokens is None
        assert report.latency_ms is None


class TestOpenRouterProviderUsageCapture:
    def test_complete_captures_usage_from_response(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 25,
                        "total_tokens": 40,
                    },
                },
            )

        provider = _make_provider(handler)
        result = provider.complete("test prompt")
        assert result == "ok"
        usage = provider.last_usage
        assert usage is not None
        assert usage.provider == "openrouter"
        assert usage.model == "test-model"
        assert usage.input_tokens == 15
        assert usage.output_tokens == 25
        assert usage.total_tokens == 40
        assert usage.latency_ms is not None
        assert usage.latency_ms >= 0

    def test_complete_captures_latency(self):
        def handler(request):
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler)
        provider.complete("prompt")
        usage = provider.last_usage
        assert usage is not None
        assert usage.latency_ms is not None
        assert usage.latency_ms >= 0

    def test_last_usage_none_before_first_call(self):
        provider = _make_provider(lambda r: httpx.Response(200, json=_chat_response("ok")))
        assert provider.last_usage is None

    def test_propose_tool_captures_usage(self):
        proposal = {"tool_name": "check_health", "arguments": {"url": "https://x.com"}}

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(proposal)}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                },
            )

        provider = _make_provider(handler)
        result = provider.propose_tool("check health")
        assert result == proposal
        usage = provider.last_usage
        assert usage is not None
        assert usage.input_tokens == 5

    def test_propose_skill_captures_usage(self):
        decision = {
            "skill_id": "s1",
            "tool_calls": [{"tool": "t"}],
            "satisfied_preconditions": [],
        }

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(decision)}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                },
            )

        provider = _make_provider(handler)
        result = provider.propose_skill("goal", [{"id": "s1"}])
        assert result == decision
        usage = provider.last_usage
        assert usage is not None
        assert usage.total_tokens == 20

    def test_usage_captured_when_response_lacks_usage_field(self):
        """API responses without usage field should still work."""

        def handler(request):
            return httpx.Response(200, json=_chat_response("ok"))

        provider = _make_provider(handler)
        result = provider.complete("prompt")
        assert result == "ok"
        usage = provider.last_usage
        assert usage is not None
        assert usage.input_tokens is None
        assert usage.output_tokens is None
        assert usage.total_tokens is None
        assert usage.latency_ms is not None

    def test_usage_updated_on_each_call(self):
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": f"resp-{call_count}"}}],
                    "usage": {"total_tokens": call_count * 10},
                },
            )

        provider = _make_provider(handler)
        provider.complete("first")
        assert provider.last_usage.total_tokens == 10
        provider.complete("second")
        assert provider.last_usage.total_tokens == 20

    def test_last_usage_accessible_through_protocol_after_call(self):
        """Usage data is accessible through LlmProvider protocol, not just concrete type."""

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 42},
                },
            )

        provider: LlmProvider = _make_provider(handler)
        assert provider.last_usage is None
        provider.complete("prompt")
        assert provider.last_usage is not None
        assert provider.last_usage.total_tokens == 42
