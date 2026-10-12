"""Splits a call's tokens and cost across its pairs, and prices tokens. Pure."""

from collections.abc import Sequence

from llm_compare.domain.models import Prices, Usage


def add_usage(first: Usage, second: Usage) -> Usage:
    both_known = first.cost is not None and second.cost is not None
    return Usage(
        first.input_tokens + second.input_tokens,
        first.output_tokens + second.output_tokens,
        first.cost + second.cost if both_known else None,
    )


def _apportion(amount: int, weights: Sequence[int]) -> list[int]:
    """Largest-remainder split: integer shares that sum exactly to `amount`."""
    total = sum(weights)
    shares = [amount * weight // total for weight in weights]
    by_fraction = sorted(range(len(weights)), key=lambda i: (-(amount * weights[i] % total), i))
    for index in by_fraction[: amount - sum(shares)]:
        shares[index] += 1
    return shares


def split_usage(usage: Usage, weights: Sequence[int]) -> list[Usage]:
    if not weights:
        return []
    weights = list(weights) if sum(weights) > 0 else [1] * len(weights)
    total = sum(weights)
    inputs = _apportion(usage.input_tokens, weights)
    outputs = _apportion(usage.output_tokens, weights)
    costs = [None if usage.cost is None else usage.cost * w / total for w in weights]
    return [Usage(i, o, c) for i, o, c in zip(inputs, outputs, costs, strict=True)]


def cost_of(input_tokens: int, output_tokens: int, prices: Prices | None) -> float | None:
    if prices is None:
        return None
    return (
        input_tokens * prices.input_per_million + output_tokens * prices.output_per_million
    ) / 1_000_000
