"""What a run would do and cost, worked out without calling the API (--dry-run)."""

from collections import Counter
from dataclasses import dataclass

from llm_compare.analysis.hash_score import score_pair
from llm_compare.analysis.runner import (
    LoadBytes,
    Scorer,
    classify_pairs,
    is_usable_entry,
    prepare_pairs,
)
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.batching import pack
from llm_compare.domain.costing import cost_of
from llm_compare.domain.models import ImagePair, Prices, Verdict
from llm_compare.output.cache import VerdictCache, pair_cache_key


@dataclass(frozen=True)
class RunPlan:
    rows: int
    settled_by_hash: int
    web_only: int
    skipped: int
    to_llm: int
    cached: int
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float | None


def plan_run(
    pairs: list[ImagePair],
    load: LoadBytes,
    config: LlmCompareConfig,
    cache: VerdictCache,
    prompt_version: str,
    prices: Prices | None,
    scorer: Scorer = score_pair,
) -> RunPlan:
    classified = classify_pairs(pairs, load, config.hash_match_percent, scorer)
    prepared = prepare_pairs(classified.to_llm, config.max_edge, config.token_scale)
    misses = [
        pair
        for pair in prepared
        if not is_usable_entry(cache.get(pair_cache_key(pair, prompt_version, config.model)))
    ]
    batches = pack(
        misses, config.max_pairs_per_call, config.max_input_tokens, config.call_overhead_tokens
    )
    input_tokens = sum(p.tokens for p in misses) + config.call_overhead_tokens * len(batches)
    output_tokens = config.output_tokens_per_pair * len(misses)
    counts = Counter(record.verdict for record in classified.settled.values())
    return RunPlan(
        rows=len(pairs),
        settled_by_hash=counts[Verdict.MATCH_PHASH],
        web_only=counts[Verdict.WEB_ONLY],
        skipped=counts[Verdict.SKIPPED],
        to_llm=len(prepared),
        cached=len(prepared) - len(misses),
        calls=len(batches),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost_of(input_tokens, output_tokens, prices),
    )


def format_plan(plan: RunPlan) -> str:
    cost = "cost unavailable" if plan.cost is None else f"${plan.cost:.4f}"
    return "\n".join(
        [
            f"rows: {plan.rows}  (web-only {plan.web_only}, skipped {plan.skipped})",
            f"settled by hash (free): {plan.settled_by_hash}",
            f"for the LLM: {plan.to_llm}  (already cached {plan.cached})",
            f"LLM calls: {plan.calls}",
            f"estimated tokens: {plan.input_tokens:,} in / {plan.output_tokens:,} out",
            f"estimated cost: {cost}",
        ]
    )
