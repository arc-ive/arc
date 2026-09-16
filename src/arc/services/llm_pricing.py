"""LLM pricing configuration and cost calculation (V2-ADR-024).

Pricing is static configuration, not hardcoded in domain logic. Cost is
calculated only when BOTH input and output token counts are available AND
a pricing entry exists for the (provider, model) pair. Otherwise cost
is None — never a partial calculation.

Configuration is loaded from the ``LLM_PRICING_JSON`` environment
variable. The expected format is a JSON object mapping
``"provider/model"`` keys to objects with ``input_cost_per_1k_tokens``
and ``output_cost_per_1k_tokens`` string values (preserving precision).

Example::

    {
        "openrouter/anthropic/claude-3-haiku": {
            "input_cost_per_1k_tokens": "0.000250",
            "output_cost_per_1k_tokens": "0.001250"
        }
    }
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from arc.domain.models import LlmUsageRecord

logger = logging.getLogger("arc.llm_pricing")

_COST_QUANTIZATION = Decimal("0.000001")


@dataclass(frozen=True)
class ModelPricing:
    """Per-model token pricing in USD per 1k tokens."""

    input_cost_per_1k_tokens: Decimal
    output_cost_per_1k_tokens: Decimal


def _load_pricing_from_env() -> dict[tuple[str, str], ModelPricing]:
    """Load pricing configuration from LLM_PRICING_JSON env var."""
    raw = os.getenv("LLM_PRICING_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("LLM_PRICING_JSON is not valid JSON; pricing disabled")
        return {}
    result: dict[tuple[str, str], ModelPricing] = {}
    for key, value in data.items():
        parts = key.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            logger.warning("Invalid pricing key format: %r (expected 'provider/model')", key)
            continue
        provider, model = parts
        try:
            result[(provider, model)] = ModelPricing(
                input_cost_per_1k_tokens=Decimal(str(value["input_cost_per_1k_tokens"])),
                output_cost_per_1k_tokens=Decimal(str(value["output_cost_per_1k_tokens"])),
            )
        except (KeyError, Decimal.InvalidOperation) as exc:
            logger.warning("Invalid pricing entry for %r: %s", key, exc)
    return result


_PRICING_CACHE: Optional[dict[tuple[str, str], ModelPricing]] = None


def get_pricing_config() -> dict[tuple[str, str], ModelPricing]:
    """Return the loaded pricing configuration (cached)."""
    global _PRICING_CACHE
    if _PRICING_CACHE is None:
        _PRICING_CACHE = _load_pricing_from_env()
    return _PRICING_CACHE


def reset_pricing_cache() -> None:
    """Reset the cached pricing configuration (for testing)."""
    global _PRICING_CACHE
    _PRICING_CACHE = None


def lookup_pricing(provider: str, model: str) -> Optional[ModelPricing]:
    """Look up pricing for a provider/model pair."""
    return get_pricing_config().get((provider, model))


def calculate_cost(
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    pricing: ModelPricing,
) -> Decimal:
    """Calculate exact cost using Decimal arithmetic.

    Returns the cost rounded to 6 decimal places. Caller must ensure
    token counts are not None before calling — this function does NOT
    guard against None (the caller decides the None-policy).
    """
    input_cost = Decimal(input_tokens) / Decimal(1000) * pricing.input_cost_per_1k_tokens
    output_cost = Decimal(output_tokens) / Decimal(1000) * pricing.output_cost_per_1k_tokens
    return (input_cost + output_cost).quantize(_COST_QUANTIZATION, rounding=ROUND_HALF_UP)


def build_llm_usage_record(
    usage,
    call_type: str,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    agent_run_id: Optional[str] = None,
    principal_id: Optional[str] = None,
) -> LlmUsageRecord:
    """Build an LlmUsageRecord with cost calculated from pricing config.

    If pricing is available for the (provider, model) pair AND both
    input_tokens and output_tokens are present, cost_usd is set using
    exact Decimal arithmetic.  Otherwise cost_usd remains None — never
    a partial calculation.
    """
    cost_usd: Optional[Decimal] = None
    pricing = lookup_pricing(usage.provider, usage.model)
    if pricing is not None and usage.input_tokens is not None and usage.output_tokens is not None:
        cost_usd = calculate_cost(usage.input_tokens, usage.output_tokens, pricing)
    return LlmUsageRecord(
        id=str(uuid.uuid4()),
        provider=usage.provider,
        model=usage.model,
        call_type=call_type,
        tenant_id=tenant_id,
        request_id=request_id,
        agent_run_id=agent_run_id,
        principal_id=principal_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        latency_ms=usage.latency_ms,
        cost_usd=cost_usd,
    )
