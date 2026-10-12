"""Estimates what a call costs in tokens and packs pairs into as few calls as the budgets
allow. Pure: the estimates are corrected against real usage by --calibrate (token_scale)."""

from collections.abc import Sequence
from math import ceil

from llm_compare.domain.models import PreparedPair

SMALL_EDGE = 384
TOKENS_PER_TILE = 258
MIN_UNIT = 256
MAX_UNIT = 768


def estimate_image_tokens(width: int, height: int, scale: float = 1.0) -> int:
    if max(width, height) <= SMALL_EDGE:
        return ceil(TOKENS_PER_TILE * scale)
    unit = min(MAX_UNIT, max(MIN_UNIT, int(min(width, height) / 1.5)))
    tiles = ceil(width / unit) * ceil(height / unit)
    return ceil(TOKENS_PER_TILE * tiles * scale)


def estimate_call_tokens(batch: Sequence[PreparedPair], overhead: int, output_per_pair: int) -> int:
    return overhead + sum(pair.tokens for pair in batch) + output_per_pair * len(batch)


def pack(
    pairs: Sequence[PreparedPair], max_pairs: int, max_input_tokens: int, overhead: int = 0
) -> list[list[PreparedPair]]:
    batches: list[list[PreparedPair]] = []
    current: list[PreparedPair] = []
    used = overhead
    for pair in pairs:
        full = len(current) >= max_pairs or (current and used + pair.tokens > max_input_tokens)
        if full:
            batches.append(current)
            current, used = [], overhead
        current.append(pair)
        used += pair.tokens
    if current:
        batches.append(current)
    return batches
