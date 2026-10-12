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
    if count <= 0:
        return []
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


def judged_count(verdicts: dict[str, Verdict]) -> int:
    return sum(verdict in LLM_VERDICTS for verdict in verdicts.values())


def _keeps_every_verdict(baseline: dict[str, Verdict], result: VariantResult) -> bool:
    judged_keys = [key for key, verdict in baseline.items() if verdict in LLM_VERDICTS]
    if any(result.verdicts.get(key) not in LLM_VERDICTS for key in judged_keys):
        return False
    return agreement(baseline, result.verdicts) == 1.0


def _has_baseline(results: list[VariantResult]) -> bool:
    return bool(results) and judged_count(results[0].verdicts) > 0


def recommend(results: list[VariantResult]) -> int | None:
    if not _has_baseline(results):
        return None
    baseline = results[0].verdicts
    keeps = [
        result
        for result in results[1:]
        if result.variant.max_pairs_per_call == 1 and _keeps_every_verdict(baseline, result)
    ]
    best = min(keeps, key=lambda result: result.input_tokens, default=None)
    return None if best is None else best.variant.max_edge


def _same_edge_single(results: list[VariantResult], batched: VariantResult):
    return next(
        (
            result
            for result in results
            if result.variant.max_pairs_per_call == 1
            and result.variant.max_edge == batched.variant.max_edge
        ),
        None,
    )


def _batching_line(results: list[VariantResult], batched: VariantResult) -> str:
    label = f"batched ({batched.variant.max_pairs_per_call} per call)"
    single = _same_edge_single(results, batched)
    if single is None:
        return f"{label}: no same-edge single variant to compare"
    return f"{label} vs same-edge single: {agreement(single.verdicts, batched.verdicts):.0%}"


def _batching_lines(results: list[VariantResult]) -> list[str]:
    return [
        _batching_line(results, result)
        for result in results[1:]
        if result.variant.max_pairs_per_call > 1
    ]


def _verdict_line(results: list[VariantResult]) -> str:
    if not results or not results[0].verdicts:
        return "no pairs were routed to the LLM: nothing to calibrate"
    if judged_count(results[0].verdicts) == 0:
        return (
            "the original-size baseline produced no verdicts (errors?): "
            "cannot recommend - check the API errors first"
        )
    best = recommend(results)
    if best is None:
        return "none of the smaller caps kept every verdict: keep original size"
    return f"recommended max_edge: {best}"


def format_calibration(results: list[VariantResult]) -> str:
    total = len(results[0].verdicts) if results else 0
    lines = ["variant                      input tok  output tok  judged  agreement with original"]
    for result in results:
        share = agreement(results[0].verdicts, result.verdicts)
        judged = f"{judged_count(result.verdicts)}/{total}"
        lines.append(
            f"{result.variant.name:<28} {result.input_tokens:>9,} {result.output_tokens:>11,}"
            f"  {judged:>6}  {share:>9.0%}"
        )
    return "\n".join([*lines, *_batching_lines(results), _verdict_line(results)])
