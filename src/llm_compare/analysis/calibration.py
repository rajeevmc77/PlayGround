"""--calibrate: pick the preprocessing cap and check batching by evidence. A sample of the
pairs bound for the LLM is judged under several settings; the smallest image cap whose
verdicts match the original-size baseline is recommended, and batched verdicts are compared
with one-pair-per-call ones."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from llm_compare.analysis.runner import JudgeDeps, ScoredPair, judge_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.models import LLM_VERDICTS, Verdict

ORIGINAL_EDGE = 10**6


@dataclass(frozen=True)
class Variant:
    name: str
    max_edge: int
    max_pairs_per_call: int


@dataclass(frozen=True)
class VariantResult:
    variant: Variant
    input_tokens: int
    output_tokens: int
    cost: float | None
    verdicts: dict[str, Verdict]


def default_variants(default_edge: int, default_batch: int) -> list[Variant]:
    return [
        Variant("original size, 1 per call", ORIGINAL_EDGE, 1),
        Variant("768px, 1 per call", 768, 1),
        Variant("1024px, 1 per call", 1024, 1),
        Variant(f"{default_edge}px, {default_batch} per call", default_edge, default_batch),
    ]


def sample_evenly(items: Sequence, count: int) -> list:
    if count >= len(items):
        return list(items)
    step = len(items) / count
    return [items[int(index * step)] for index in range(count)]


def agreement(baseline: dict[str, Verdict], other: dict[str, Verdict]) -> float:
    shared = [
        key for key in baseline if baseline[key] in LLM_VERDICTS and other.get(key) in LLM_VERDICTS
    ]
    if not shared:
        return 0.0
    return sum(baseline[key] == other[key] for key in shared) / len(shared)


def _total_cost(records) -> float | None:
    costs = [record.cost for record in records]
    return None if any(cost is None for cost in costs) else sum(costs)


async def _run_one(scored, variant, config, make_deps) -> VariantResult:
    settings = replace(
        config, max_edge=variant.max_edge, max_pairs_per_call=variant.max_pairs_per_call
    )
    deps = make_deps(settings)
    prepared = prepare_pairs(scored, settings.max_edge, settings.token_scale)
    records = list((await judge_pairs(prepared, deps)).values())
    return VariantResult(
        variant,
        sum(record.input_tokens for record in records) + deps.stats.wasted.input_tokens,
        sum(record.output_tokens for record in records) + deps.stats.wasted.output_tokens,
        _total_cost(records),
        {record.row_id: record.verdict for record in records},
    )


async def run_variants(
    scored: list[ScoredPair],
    variants: list[Variant],
    config: LlmCompareConfig,
    make_deps: Callable[[LlmCompareConfig], JudgeDeps],
) -> list[VariantResult]:
    return [await _run_one(scored, variant, config, make_deps) for variant in variants]


def recommend(results: list[VariantResult]) -> int | None:
    baseline = results[0].verdicts
    keeps = [
        result
        for result in results[1:]
        if result.variant.max_pairs_per_call == 1 and agreement(baseline, result.verdicts) == 1.0
    ]
    if not keeps:
        return None
    return min(keeps, key=lambda result: result.input_tokens).variant.max_edge


def format_calibration(results: list[VariantResult]) -> str:
    baseline = results[0].verdicts
    lines = ["variant                      input tok  output tok  agreement with original"]
    for result in results:
        share = agreement(baseline, result.verdicts)
        lines.append(
            f"{result.variant.name:<28} {result.input_tokens:>9,} {result.output_tokens:>11,}"
            f"  {share:>9.0%}"
        )
    best = recommend(results)
    lines.append(
        f"recommended max_edge: {best if best is not None else 'none (keep original size)'}"
    )
    return "\n".join(lines)
