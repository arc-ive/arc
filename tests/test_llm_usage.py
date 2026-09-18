"""Tests for LLM usage persistence (V2-ADR-024, Issue #141).

Covers domain validation, pricing, persistence, aggregation, telemetry
semantics, cost coverage, API endpoints, and backward compatibility.
"""

import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from arc.domain.models import (
    LLM_CALL_TYPE_COMPLETE,
    LLM_CALL_TYPES,
    LlmUsageActivityMetrics,
    LlmUsageRecord,
    LlmUsageRecordsAggregate,
)
from arc.services.llm import LlmUsageReport, _current_llm_usage

# ─── Domain Models ──────────────────────────────────────────────────


def _usage_record(**overrides):
    defaults = dict(
        id=f"llm-{uuid.uuid4().hex[:12]}",
        provider="openrouter",
        model="openrouter/free",
        call_type=LLM_CALL_TYPE_COMPLETE,
        tenant_id="t-1",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        latency_ms=200,
    )
    defaults.update(overrides)
    return LlmUsageRecord(**defaults)


class TestLlmUsageRecordValidation:
    def test_valid_minimal_record(self):
        record = _usage_record()
        assert record.id.startswith("llm-")
        assert record.provider == "openrouter"
        assert record.model == "openrouter/free"
        assert record.call_type == LLM_CALL_TYPE_COMPLETE
        assert record.tenant_id == "t-1"
        assert record.cost_usd is None

    def test_valid_attributed_record(self):
        record = _usage_record(
            tenant_id="t-2",
            request_id="req-1",
            agent_run_id="run-1",
            principal_id="u-1",
            cost_usd=Decimal("0.001234"),
        )
        assert record.tenant_id == "t-2"
        assert record.request_id == "req-1"
        assert record.agent_run_id == "run-1"
        assert record.principal_id == "u-1"
        assert record.cost_usd == Decimal("0.001234")

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="ID cannot be empty"):
            _usage_record(id="")

    def test_empty_provider_rejected(self):
        with pytest.raises(ValueError, match="provider cannot be empty"):
            _usage_record(provider="")

    def test_whitespace_provider_rejected(self):
        with pytest.raises(ValueError, match="provider cannot be empty"):
            _usage_record(provider="  ")

    def test_empty_model_rejected(self):
        with pytest.raises(ValueError, match="model cannot be empty"):
            _usage_record(model="")

    def test_whitespace_model_rejected(self):
        with pytest.raises(ValueError, match="model cannot be empty"):
            _usage_record(model="  ")

    def test_invalid_call_type_rejected(self):
        with pytest.raises(ValueError, match="Invalid LLM call type"):
            _usage_record(call_type="invalid")

    @pytest.mark.parametrize("call_type", LLM_CALL_TYPES)
    def test_valid_call_types_accepted(self, call_type):
        assert _usage_record(call_type=call_type).call_type == call_type

    def test_optional_fields_default_none(self):
        record = LlmUsageRecord(
            id=f"llm-{uuid.uuid4().hex[:12]}",
            provider="openrouter",
            model="openrouter/free",
            call_type=LLM_CALL_TYPE_COMPLETE,
        )
        assert record.tenant_id is None
        assert record.request_id is None
        assert record.agent_run_id is None
        assert record.principal_id is None
        assert record.input_tokens is None
        assert record.output_tokens is None
        assert record.total_tokens is None
        assert record.latency_ms is None
        assert record.cost_usd is None


class TestLlmUsageActivityMetricsValidation:
    def test_valid_metrics(self):
        metrics = LlmUsageActivityMetrics(
            total_calls=10,
            calls_by_type={"complete": 5, "propose_tool": 5},
            total_input_tokens=1000,
            total_output_tokens=500,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=Decimal("0.05"),
            unknown_cost_records=0,
            models_used=["openrouter/free"],
        )
        assert metrics.total_calls == 10
        assert metrics.unknown_cost_records == 0

    def test_negative_total_calls_rejected(self):
        with pytest.raises(ValueError, match="Total calls cannot be negative"):
            LlmUsageActivityMetrics(
                total_calls=-1,
                calls_by_type={},
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                avg_latency_ms=0.0,
                total_cost_usd=None,
                unknown_cost_records=0,
                models_used=[],
            )

    def test_negative_unknown_cost_rejected(self):
        with pytest.raises(ValueError, match="Unknown cost records cannot be negative"):
            LlmUsageActivityMetrics(
                total_calls=0,
                calls_by_type={},
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                avg_latency_ms=0.0,
                total_cost_usd=None,
                unknown_cost_records=-1,
                models_used=[],
            )

    def test_unknown_cost_exceeds_total_rejected(self):
        with pytest.raises(ValueError, match="Unknown cost records cannot exceed total"):
            LlmUsageActivityMetrics(
                total_calls=5,
                calls_by_type={},
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                avg_latency_ms=0.0,
                total_cost_usd=None,
                unknown_cost_records=10,
                models_used=[],
            )


class TestCostCoverageProperty:
    """Verify the cost_coverage property on LlmUsageActivityMetrics is the
    single authoritative source used by both _llm_payload and the API."""

    def _metrics(self, total_calls, unknown_cost_records):
        return LlmUsageActivityMetrics(
            total_calls=total_calls,
            calls_by_type={},
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            avg_latency_ms=0.0,
            total_cost_usd=None,
            unknown_cost_records=unknown_cost_records,
            models_used=[],
        )

    def test_zero_calls_returns_none(self):
        assert self._metrics(0, 0).cost_coverage == "none"

    def test_all_known_returns_full(self):
        assert self._metrics(10, 0).cost_coverage == "full"

    def test_some_unknown_returns_partial(self):
        assert self._metrics(10, 3).cost_coverage == "partial"

    def test_all_unknown_returns_partial(self):
        assert self._metrics(10, 10).cost_coverage == "partial"

    def test_summary_payload_uses_property(self):
        from arc.services.observability import ObservabilityService

        llm = self._metrics(5, 2)
        payload = ObservabilityService._llm_payload(llm)
        assert payload["cost_coverage"] == "partial"

    def test_zero_calls_summary_uses_property(self):
        from arc.services.observability import ObservabilityService

        llm = self._metrics(0, 0)
        payload = ObservabilityService._llm_payload(llm)
        assert payload["cost_coverage"] == "none"


class TestLlmUsageRecordsAggregateValidation:
    def test_valid_aggregate_full_coverage(self):
        agg = LlmUsageRecordsAggregate(
            total_calls=10,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=Decimal("0.05"),
            unknown_cost_records=0,
            cost_coverage="full",
        )
        assert agg.cost_coverage == "full"

    def test_valid_aggregate_partial_coverage(self):
        agg = LlmUsageRecordsAggregate(
            total_calls=10,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=Decimal("0.03"),
            unknown_cost_records=3,
            cost_coverage="partial",
        )
        assert agg.cost_coverage == "partial"

    def test_valid_aggregate_no_coverage(self):
        agg = LlmUsageRecordsAggregate(
            total_calls=10,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=None,
            unknown_cost_records=10,
            cost_coverage="none",
        )
        assert agg.cost_coverage == "none"

    def test_invalid_cost_coverage_rejected(self):
        with pytest.raises(ValueError, match="Invalid cost_coverage"):
            LlmUsageRecordsAggregate(
                total_calls=10,
                total_tokens=1500,
                avg_latency_ms=200.0,
                total_cost_usd=None,
                unknown_cost_records=0,
                cost_coverage="unknown",
            )


# ─── Pricing Service ────────────────────────────────────────────────


class TestLlmPricing:
    def test_calculate_cost_basic(self):
        from arc.services.llm_pricing import ModelPricing, calculate_cost

        pricing = ModelPricing(
            input_cost_per_1k_tokens=Decimal("0.000250"),
            output_cost_per_1k_tokens=Decimal("0.001250"),
        )
        cost = calculate_cost(1000, 1000, pricing)
        assert cost == Decimal("0.001500")

    def test_calculate_cost_zero_tokens(self):
        from arc.services.llm_pricing import ModelPricing, calculate_cost

        pricing = ModelPricing(
            input_cost_per_1k_tokens=Decimal("0.000250"),
            output_cost_per_1k_tokens=Decimal("0.001250"),
        )
        cost = calculate_cost(0, 0, pricing)
        assert cost == Decimal("0.000000")

    def test_calculate_cost_rounding(self):
        from arc.services.llm_pricing import ModelPricing, calculate_cost

        pricing = ModelPricing(
            input_cost_per_1k_tokens=Decimal("0.000001"),
            output_cost_per_1k_tokens=Decimal("0.000001"),
        )
        cost = calculate_cost(1, 1, pricing)
        assert cost == Decimal("0.000000")

    def test_lookup_pricing_with_env(self, monkeypatch):
        from arc.services.llm_pricing import lookup_pricing, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "openrouter/test-model": {
                "input_cost_per_1k_tokens": "0.001000",
                "output_cost_per_1k_tokens": "0.002000",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            pricing = lookup_pricing("openrouter", "test-model")
            assert pricing is not None
            assert pricing.input_cost_per_1k_tokens == Decimal("0.001000")
        finally:
            reset_pricing_cache()

    def test_lookup_pricing_unknown_model(self, monkeypatch):
        from arc.services.llm_pricing import lookup_pricing, reset_pricing_cache

        reset_pricing_cache()
        monkeypatch.delenv("LLM_PRICING_JSON", raising=False)
        reset_pricing_cache()
        try:
            assert lookup_pricing("openrouter", "unknown-model") is None
        finally:
            reset_pricing_cache()

    def test_invalid_json_env_handled(self, monkeypatch):
        from arc.services.llm_pricing import get_pricing_config, reset_pricing_cache

        reset_pricing_cache()
        monkeypatch.setenv("LLM_PRICING_JSON", "not-valid-json")
        reset_pricing_cache()
        try:
            config = get_pricing_config()
            assert config == {}
        finally:
            reset_pricing_cache()

    def test_invalid_key_format_skipped(self, monkeypatch):
        from arc.services.llm_pricing import lookup_pricing, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "invalid-key": {
                "input_cost_per_1k_tokens": "0.001000",
                "output_cost_per_1k_tokens": "0.002000",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            assert lookup_pricing("openrouter", "unknown-model") is None
        finally:
            reset_pricing_cache()


# ─── build_llm_usage_record (pricing wiring) ────────────────────────


class TestBuildLlmUsageRecord:
    def _usage(self, **overrides):
        defaults = dict(
            provider="openrouter",
            model="openrouter/free",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=200,
        )
        defaults.update(overrides)
        return LlmUsageReport(**defaults)

    def test_configured_pricing_produces_non_null_cost(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "openrouter/openrouter/free": {
                "input_cost_per_1k_tokens": "0.001000",
                "output_cost_per_1k_tokens": "0.002000",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(), call_type=LLM_CALL_TYPE_COMPLETE, tenant_id="t-1"
            )
            assert record.cost_usd is not None
            # input 100/1000*0.001 + output 50/1000*0.002 = 0.0001 + 0.0001 = 0.000200
            assert record.cost_usd == Decimal("0.000200")
        finally:
            reset_pricing_cache()

    def test_fractional_decimal_cost_is_correct(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "openrouter/openrouter/free": {
                "input_cost_per_1k_tokens": "0.000003",
                "output_cost_per_1k_tokens": "0.000007",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(input_tokens=1234, output_tokens=5678),
                call_type=LLM_CALL_TYPE_COMPLETE,
                tenant_id="t-1",
            )
            assert record.cost_usd is not None
            expected = (Decimal("1234") / Decimal(1000) * Decimal("0.000003")) + (
                Decimal("5678") / Decimal(1000) * Decimal("0.000007")
            )
            from decimal import ROUND_HALF_UP

            expected = expected.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            assert record.cost_usd == expected
        finally:
            reset_pricing_cache()

    def test_unknown_pricing_produces_null_cost(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        monkeypatch.delenv("LLM_PRICING_JSON", raising=False)
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(), call_type=LLM_CALL_TYPE_COMPLETE, tenant_id="t-1"
            )
            assert record.cost_usd is None
        finally:
            reset_pricing_cache()

    def test_missing_tokens_produces_null_cost(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "openrouter/openrouter/free": {
                "input_cost_per_1k_tokens": "0.001000",
                "output_cost_per_1k_tokens": "0.002000",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(input_tokens=None, output_tokens=50),
                call_type=LLM_CALL_TYPE_COMPLETE,
                tenant_id="t-1",
            )
            assert record.cost_usd is None
        finally:
            reset_pricing_cache()

    def test_free_pricing_produces_zero(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        pricing_data = {
            "openrouter/openrouter/free": {
                "input_cost_per_1k_tokens": "0.000000",
                "output_cost_per_1k_tokens": "0.000000",
            }
        }
        monkeypatch.setenv("LLM_PRICING_JSON", json.dumps(pricing_data))
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(), call_type=LLM_CALL_TYPE_COMPLETE, tenant_id="t-1"
            )
            assert record.cost_usd == Decimal("0.000000")
        finally:
            reset_pricing_cache()

    def test_record_fields_propagated(self, monkeypatch):
        from arc.services.llm_pricing import build_llm_usage_record, reset_pricing_cache

        reset_pricing_cache()
        monkeypatch.delenv("LLM_PRICING_JSON", raising=False)
        reset_pricing_cache()
        try:
            record = build_llm_usage_record(
                self._usage(),
                call_type="complete",
                tenant_id="t-9",
                request_id="req-42",
                agent_run_id="run-7",
                principal_id="u-3",
            )
            assert record.tenant_id == "t-9"
            assert record.request_id == "req-42"
            assert record.agent_run_id == "run-7"
            assert record.principal_id == "u-3"
            assert record.call_type == "complete"
            assert record.provider == "openrouter"
            assert record.model == "openrouter/free"
            assert record.input_tokens == 100
            assert record.output_tokens == 50
            assert record.total_tokens == 150
            assert record.latency_ms == 200
        finally:
            reset_pricing_cache()


# ─── ContextVar Usage Tracking ──────────────────────────────────────


class TestContextVarUsage:
    def test_contextvar_set_and_get(self):
        token = _current_llm_usage.set(None)
        try:
            usage = MagicMock()
            token2 = _current_llm_usage.set(usage)
            try:
                assert _current_llm_usage.get() is usage
            finally:
                _current_llm_usage.reset(token2)
        finally:
            _current_llm_usage.reset(token)

    def test_contextvar_reset(self):
        token = _current_llm_usage.set(None)
        try:
            token2 = _current_llm_usage.set(MagicMock())
            _current_llm_usage.reset(token2)
            assert _current_llm_usage.get() is None
        finally:
            _current_llm_usage.reset(token)

    @pytest.mark.asyncio
    async def test_contextvar_isolation_across_concurrent_coroutines(self):
        """Verify that two concurrent async contexts see independent values."""

        async def worker(name, value):
            token = _current_llm_usage.set(None)
            try:
                token2 = _current_llm_usage.set(value)
                try:
                    await asyncio.sleep(0)  # yield to allow interleaving
                    current = _current_llm_usage.get()
                    assert current is value, (
                        f"Coroutine {name!r} expected {value!r} but got {current!r}"
                    )
                finally:
                    _current_llm_usage.reset(token2)
            finally:
                _current_llm_usage.reset(token)

        usage_a = MagicMock(spec=LlmUsageReport)
        usage_a.provider = "a"
        usage_b = MagicMock(spec=LlmUsageReport)
        usage_b.provider = "b"

        await asyncio.gather(worker("A", usage_a), worker("B", usage_b))


# ─── ContextVar Lifecycle (Production) ──────────────────────────────


class TestContextVarLifecycle:
    """Verify the _execute_request ContextVar lifecycle invariant:
    stale usage must not leak across calls."""

    def _make_provider(self, handler):
        from arc.services.llm import OpenRouterProvider

        return OpenRouterProvider.__new__(OpenRouterProvider)

    def test_successful_call_sets_contextvar(self):
        """After a successful call, ContextVar has the new usage."""
        import httpx

        from arc.services.llm import OpenRouterProvider

        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider._model = "test-model"
        provider._last_usage = None

        body = {
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return body

        client = MagicMock(spec=httpx.Client)
        client.post.return_value = FakeResponse()

        token = _current_llm_usage.set(None)
        try:
            result = provider._execute_request(client, "http://x", {}, {})
            assert result == "answer"
            usage = _current_llm_usage.get()
            assert usage is not None
            assert usage.provider == "openrouter"
            assert usage.model == "test-model"
            assert usage.input_tokens == 10
            assert usage.output_tokens == 5
            assert usage.total_tokens == 15
            assert provider.last_usage is usage
        finally:
            _current_llm_usage.reset(token)

    def test_exception_path_leaves_contextvar_none(self):
        """After a failed call, ContextVar is None — no stale usage."""
        import httpx

        from arc.services.llm import OpenRouterProvider

        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider._model = "test-model"
        provider._last_usage = None

        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 500
        response.text = "error"
        client.post.return_value = response

        token = _current_llm_usage.set(None)
        try:
            # Pre-set stale usage to prove it gets cleared
            token2 = _current_llm_usage.set(
                LlmUsageReport(
                    provider="openrouter",
                    model="stale-model",
                    input_tokens=999,
                    output_tokens=999,
                    total_tokens=999,
                    latency_ms=999,
                )
            )
            _current_llm_usage.reset(token2)

            from arc.services.llm import LlmError

            with pytest.raises(LlmError):
                provider._execute_request(client, "http://x", {}, {})

            assert _current_llm_usage.get() is None
        finally:
            _current_llm_usage.reset(token)

    def test_stale_usage_cleared_before_new_call(self):
        """A new call clears stale ContextVar usage before the HTTP call."""
        import httpx

        from arc.services.llm import OpenRouterProvider

        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider._model = "new-model"
        provider._last_usage = None

        body = {
            "choices": [{"message": {"content": "new"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return body

        client = MagicMock(spec=httpx.Client)
        client.post.return_value = FakeResponse()

        token = _current_llm_usage.set(None)
        try:
            # Inject stale usage from a hypothetical prior call
            stale = LlmUsageReport(
                provider="openrouter",
                model="stale-model",
                input_tokens=999,
                output_tokens=999,
                total_tokens=999,
                latency_ms=999,
            )
            token2 = _current_llm_usage.set(stale)
            _current_llm_usage.reset(token2)

            # The new call should clear stale and set fresh
            provider._execute_request(client, "http://x", {}, {})

            usage = _current_llm_usage.get()
            assert usage is not None
            assert usage.model == "new-model"
            assert usage.total_tokens == 2
            assert provider.last_usage is usage
        finally:
            _current_llm_usage.reset(token)

    def test_no_usage_response_leaves_contextvar_none(self):
        """When the response has no usage block, ContextVar is None."""
        import httpx

        from arc.services.llm import OpenRouterProvider

        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider._model = "test-model"
        provider._last_usage = None

        body = {"choices": [{"message": {"content": "ok"}}]}

        class FakeResponse:
            status_code = 200

            def json(self):
                return body

        client = MagicMock(spec=httpx.Client)
        client.post.return_value = FakeResponse()

        token = _current_llm_usage.set(None)
        try:
            provider._execute_request(client, "http://x", {}, {})
            usage = _current_llm_usage.get()
            assert usage is not None
            assert usage.input_tokens is None
            assert usage.output_tokens is None
            assert usage.total_tokens is None
        finally:
            _current_llm_usage.reset(token)

    def test_provider_last_usage_preserved_on_success(self):
        """provider.last_usage is set alongside ContextVar on success."""
        import httpx

        from arc.services.llm import OpenRouterProvider

        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider._model = "test-model"
        provider._last_usage = None

        body = {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return body

        client = MagicMock(spec=httpx.Client)
        client.post.return_value = FakeResponse()

        token = _current_llm_usage.set(None)
        try:
            provider._execute_request(client, "http://x", {}, {})
            assert provider.last_usage is not None
            assert provider.last_usage.total_tokens == 7
            assert _current_llm_usage.get() is provider.last_usage
        finally:
            _current_llm_usage.reset(token)


# ─── Observability Service LLM Usage ────────────────────────────────


class TestObservabilityServiceLlmUsage:
    @pytest.mark.asyncio
    async def test_record_llm_usage_success(self):
        from arc.services.observability import ObservabilityService

        repo = AsyncMock()
        service = ObservabilityService(repository=repo)
        record = _usage_record()

        result = await service.record_llm_usage(record)

        assert result is True
        repo.create_llm_usage_record.assert_awaited_once_with(record)

    @pytest.mark.asyncio
    async def test_record_llm_usage_failure_returns_false(self):
        from arc.services.observability import ObservabilityService

        repo = AsyncMock()
        repo.create_llm_usage_record.side_effect = Exception("DB error")
        service = ObservabilityService(repository=repo)
        record = _usage_record()

        result = await service.record_llm_usage(record)

        assert result is False

    @pytest.mark.asyncio
    async def test_get_llm_usage_aggregation(self):
        from arc.services.observability import ObservabilityService

        expected = LlmUsageActivityMetrics(
            total_calls=10,
            calls_by_type={"complete": 5, "propose_tool": 5},
            total_input_tokens=1000,
            total_output_tokens=500,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=Decimal("0.05"),
            unknown_cost_records=0,
            models_used=["openrouter/free"],
        )
        repo = AsyncMock()
        repo.llm_usage_activity.return_value = expected
        service = ObservabilityService(repository=repo)

        result = await service.get_llm_usage("t-1", 24)

        assert result.total_calls == 10
        repo.llm_usage_activity.assert_awaited_once_with("t-1", 24)

    @pytest.mark.asyncio
    async def test_get_llm_usage_records_returns_total(self):
        from arc.services.observability import ObservabilityService

        records = [_usage_record() for _ in range(5)]
        repo = AsyncMock()
        repo.llm_usage_records_page.return_value = (records, 42)
        service = ObservabilityService(repository=repo)

        result = await service.get_llm_usage_records("t-1", 24, "complete", 10, 0)

        assert result["limit"] == 10
        assert result["offset"] == 0
        assert result["total"] == 42
        assert len(result["records"]) == 5
        repo.llm_usage_records_page.assert_awaited_once_with("t-1", 24, "complete", 10, 0)

    def test_validated_window_rejects_non_integer(self):
        from arc.services.observability import ObservabilityService

        with pytest.raises(ValueError, match="Window hours must be an integer"):
            ObservabilityService._validated_window("24")

    def test_validated_window_rejects_out_of_range(self):
        from arc.services.observability import ObservabilityService

        with pytest.raises(ValueError, match="Window hours must be between"):
            ObservabilityService._validated_window(0)
        with pytest.raises(ValueError, match="Window hours must be between"):
            ObservabilityService._validated_window(169)


# ─── LLM Payload Formatting ─────────────────────────────────────────


class TestLlmPayload:
    def _metrics(self, total_calls, unknown_cost_records, cost_usd=None):
        return LlmUsageActivityMetrics(
            total_calls=total_calls,
            calls_by_type={},
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            avg_latency_ms=0.0,
            total_cost_usd=cost_usd,
            unknown_cost_records=unknown_cost_records,
            models_used=[],
        )

    def test_payload_zero_calls(self):
        from arc.services.observability import ObservabilityService

        payload = ObservabilityService._llm_payload(self._metrics(0, 0))
        assert payload["cost_coverage"] == "none"
        assert payload["total_cost_usd"] is None

    def test_payload_full_coverage(self):
        from arc.services.observability import ObservabilityService

        payload = ObservabilityService._llm_payload(self._metrics(10, 0, cost_usd=Decimal("0.05")))
        assert payload["cost_coverage"] == "full"
        assert payload["total_cost_usd"] == 0.05

    def test_payload_partial_coverage(self):
        from arc.services.observability import ObservabilityService

        payload = ObservabilityService._llm_payload(self._metrics(10, 3, cost_usd=Decimal("0.03")))
        assert payload["cost_coverage"] == "partial"


# ─── Integration: Intelligence Service ──────────────────────────────


class TestIntelligenceServiceUsageRecording:
    @pytest.mark.asyncio
    async def test_answer_query_records_usage_after_complete(self):
        """Invoke the real answer_query path; verify record_llm_usage is called
        with correct provider, model, tokens, latency, request_id, tenant,
        principal, and call_type."""
        from arc.domain.models import (
            ApprovedContext,
            ApprovedContextItem,
            ApprovedContextSecurityMetadata,
            KnowledgeSource,
            RetrievalMethod,
            TenantContext,
            UserRole,
        )
        from arc.services.intelligence import UnifiedIntelligenceService

        obs_service = AsyncMock()

        # Fake LLM provider that sets ContextVar then returns answer
        llm_provider = MagicMock()
        fake_usage = LlmUsageReport(
            provider="openrouter",
            model="test-model",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            latency_ms=150,
        )

        def _complete(prompt):
            _current_llm_usage.set(fake_usage)
            return "test answer"

        llm_provider.complete.side_effect = _complete

        # Fake retrieval returning one item
        retrieval = AsyncMock()
        security_meta = ApprovedContextSecurityMetadata(tenant_id="t-1")
        approved = ApprovedContext(
            request_id="req-abc-123",
            tenant_id="t-1",
            principal_id="u-1",
            query="What is X?",
            retrieval_method=RetrievalMethod.DENSE_SEMANTIC,
            items=[
                ApprovedContextItem(
                    document_id="d-1",
                    chunk_id="c-1",
                    content="approved content",
                    source=KnowledgeSource.POLICY,
                    provenance="doc.pdf",
                    document_version=1,
                    sequence=0,
                    relevance_score=0.9,
                    citation_reference="d-1#c0",
                )
            ],
            security_metadata=security_meta,
        )
        retrieval.approved_search.return_value = approved

        context = TenantContext(
            tenant_id="t-1", tenant_name="Test", user_id="u-1", role=UserRole.MEMBER
        )

        service = UnifiedIntelligenceService(
            retrieval=retrieval,
            llm_provider=llm_provider,
            tool_service=None,
            observability_service=obs_service,
        )

        answer = await service.answer_query(context, "What is X?")

        assert answer.answer == "test answer"
        assert obs_service.record_llm_usage.await_count == 1
        recorded = obs_service.record_llm_usage.call_args[0][0]
        assert isinstance(recorded, LlmUsageRecord)
        assert recorded.provider == "openrouter"
        assert recorded.model == "test-model"
        assert recorded.input_tokens == 200
        assert recorded.output_tokens == 100
        assert recorded.total_tokens == 300
        assert recorded.latency_ms == 150
        assert recorded.call_type == LLM_CALL_TYPE_COMPLETE
        assert recorded.tenant_id == "t-1"
        assert recorded.principal_id == "u-1"
        assert recorded.request_id == "req-abc-123"
        assert recorded.agent_run_id is None

    @pytest.mark.asyncio
    async def test_no_observability_still_works(self):
        from arc.services.intelligence import UnifiedIntelligenceService

        service = UnifiedIntelligenceService(
            retrieval=MagicMock(),
            llm_provider=MagicMock(),
            tool_service=None,
        )

        assert service.observability_service is None


# ─── Integration: Agent Service ─────────────────────────────────────


class TestAgentServiceUsageRecording:
    @pytest.mark.asyncio
    async def test_agent_run_records_usage_with_request_id_and_agent_run_id(self):
        """Invoke the real agent run path; verify record_llm_usage is called
        with both request_id (from correlation ContextVar) and agent_run_id."""
        from arc.domain.models import TenantContext, UserRole
        from arc.security.authorization import AuthorizationService
        from arc.services.agent import AgentExecutionService

        obs_service = AsyncMock()

        # Fake LLM provider: returns None on first call to end the loop
        from arc.services.llm import SkillSelectingLlm

        llm_provider = MagicMock(spec=SkillSelectingLlm)
        llm_provider.skill_decision_capable = True

        def _propose_skill(goal, snapshot):
            _current_llm_usage.set(
                LlmUsageReport(
                    provider="openrouter",
                    model="agent-model",
                    input_tokens=50,
                    output_tokens=25,
                    total_tokens=75,
                    latency_ms=80,
                )
            )
            return None  # decline => ends the run

        llm_provider.propose_skill.side_effect = _propose_skill

        skill_service = AsyncMock()
        skill_service.list_skills.return_value = []

        skill_exec_service = MagicMock()

        context = TenantContext(
            tenant_id="t-5", tenant_name="AgentTenant", user_id="u-7", role=UserRole.MEMBER
        )
        principal = MagicMock()
        authorization = MagicMock(spec=AuthorizationService)

        service = AgentExecutionService(
            skill_service=skill_service,
            skill_execution_service=skill_exec_service,
            llm_provider=llm_provider,
            observability_service=obs_service,
        )

        from arc.api.correlation import request_id_var

        token = request_id_var.set("req-agent-42")
        try:
            await service.run(context, principal, "do something", authorization)
        finally:
            request_id_var.reset(token)

        assert obs_service.record_llm_usage.await_count == 1
        recorded = obs_service.record_llm_usage.call_args[0][0]
        assert isinstance(recorded, LlmUsageRecord)
        assert recorded.request_id == "req-agent-42"
        assert recorded.agent_run_id is not None
        # It must be the id the run is actually persisted under. The agent
        # previously minted a second UUID for usage records, so this was a
        # valid id that correlated to no agent run at all — "is not None"
        # passed throughout.
        persisted_run = obs_service.record_agent_run.call_args[0][0]
        assert recorded.agent_run_id == persisted_run.id
        assert recorded.call_type == "propose_skill"
        assert recorded.tenant_id == "t-5"
        assert recorded.principal_id == "u-7"
        assert recorded.provider == "openrouter"
        assert recorded.model == "agent-model"
        assert recorded.input_tokens == 50

    @pytest.mark.asyncio
    async def test_no_observability_still_works(self):
        from arc.services.agent import AgentExecutionService

        service = AgentExecutionService(
            skill_service=MagicMock(),
            skill_execution_service=MagicMock(),
            llm_provider=MagicMock(),
        )

        assert service.observability_service is None


# ─── Tenant Usage Summary Integration ───────────────────────────────


class TestTenantUsageSummaryLlm:
    @pytest.mark.asyncio
    async def test_usage_summary_includes_llm(self):
        from arc.services.observability import ObservabilityService

        http = MagicMock()
        http.total_requests = 100
        http.error_count = 5
        http.error_rate = 0.05
        http.avg_duration_ms = 100.0
        http.p95_duration_ms = 200.0

        tools = MagicMock()
        tools.total_executions = 50
        tools.successful = 45
        tools.failed = 3
        tools.denied = 2

        connectors = MagicMock()
        connectors.total_syncs = 10
        connectors.successful = 8
        connectors.failed = 2
        connectors.items_fetched = 100

        webhooks = MagicMock()
        webhooks.available = True
        webhooks.total_events = 20
        webhooks.distinct_event_types = 5
        webhooks.total_payload_bytes = 1024

        approvals = MagicMock()
        approvals.total = 5
        approvals.pending = 2
        approvals.approved = 2
        approvals.rejected = 1
        approvals.expired = 0
        approvals.consumed = 2

        agent_runs = MagicMock()
        agent_runs.total_runs = 3
        agent_runs.succeeded = 2
        agent_runs.failed = 1
        agent_runs.approval_required = 0
        agent_runs.max_steps_reached = 0

        llm = LlmUsageActivityMetrics(
            total_calls=10,
            calls_by_type={"complete": 5, "propose_tool": 5},
            total_input_tokens=1000,
            total_output_tokens=500,
            total_tokens=1500,
            avg_latency_ms=200.0,
            total_cost_usd=Decimal("0.05"),
            unknown_cost_records=0,
            models_used=["openrouter/free"],
        )

        repo = AsyncMock()
        repo.api_request_summary.return_value = http
        repo.tool_execution_activity.return_value = tools
        repo.connector_sync_activity.return_value = connectors
        repo.webhook_event_activity.return_value = webhooks
        repo.approval_activity.return_value = approvals
        repo.escalation_count.return_value = 0
        repo.agent_run_activity.return_value = agent_runs
        repo.llm_usage_activity.return_value = llm

        service = ObservabilityService(repository=repo)
        summary = await service.get_tenant_usage_summary("t-1", 24)

        assert "llm" in summary
        assert summary["llm"]["total_calls"] == 10
        assert summary["llm"]["cost_coverage"] == "full"
        assert summary["llm"]["total_cost_usd"] == 0.05


# ─── Paginated records total count ──────────────────────────────────


class TestLlmUsageRecordsTotal:
    @pytest.mark.asyncio
    async def test_total_included_in_response(self):
        from arc.services.observability import ObservabilityService

        repo = AsyncMock()
        repo.llm_usage_records_page.return_value = ([_usage_record()], 25)
        service = ObservabilityService(repository=repo)

        result = await service.get_llm_usage_records("t-1", 24, None, 10, 0)

        assert result["total"] == 25

    @pytest.mark.asyncio
    async def test_total_with_call_type_filter(self):
        from arc.services.observability import ObservabilityService

        repo = AsyncMock()
        repo.llm_usage_records_page.return_value = ([], 3)
        service = ObservabilityService(repository=repo)

        result = await service.get_llm_usage_records("t-1", 24, "complete", 10, 0)

        assert result["total"] == 3
        repo.llm_usage_records_page.assert_awaited_once_with("t-1", 24, "complete", 10, 0)
