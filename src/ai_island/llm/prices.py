"""Money maths (Contract C4): what a call cost, and the most it could cost."""

from __future__ import annotations

import json
from decimal import Decimal

from ai_island.config import PricesConfig, RoleConfig
from ai_island.llm.schema_transform import INSTRUCTION_HEAD, provider_schema
from ai_island.llm.types import LLMRequest, Usage

_MILLION = Decimal(1_000_000)


def _d(value: float) -> Decimal:
    return Decimal(repr(float(value)))


def cost_usd(usage: Usage, prices: PricesConfig) -> float:
    """(input*I + cache_write*CW + cache_read*CR + output*O) / 1e6, Decimal inside."""
    total = (
        Decimal(usage.input_tokens) * _d(prices.input)
        + Decimal(usage.cache_write_tokens) * _d(prices.cache_write)
        + Decimal(usage.cache_read_tokens) * _d(prices.cache_read)
        + Decimal(usage.output_tokens) * _d(prices.output)
    )
    return float(total / _MILLION)


def upper_bound_usd(request: LLMRequest, role: RoleConfig, framing_tokens: int = 256) -> float:
    """The most the call can cost: every prompt token at the dearer input rate, full output.

    A token is never shorter than one byte, so the prompt is at most its UTF-8 byte length plus
    the byte length of the provider schema plus ``framing_tokens`` for the wrapper text.
    """
    layers = request.layers
    prompt_bytes = sum(len(t.encode("utf-8")) for t in (layers.fixed, layers.slow, layers.current))
    schema = provider_schema(request.schema, role.provider)
    schema_bytes = len(json.dumps(schema).encode("utf-8"))
    instruction_bytes = 0
    if role.output_mode == "prompt":  # the instruction block is the schema JSON plus its head line
        instruction_bytes = len((INSTRUCTION_HEAD + "\n").encode("utf-8"))
    tokens = prompt_bytes + schema_bytes + instruction_bytes + framing_tokens
    p = role.prices
    rate_in = max(_d(p.input), _d(p.cache_write))
    total = Decimal(tokens) * rate_in + Decimal(request.max_output_tokens) * _d(p.output)
    return float(total / _MILLION)
