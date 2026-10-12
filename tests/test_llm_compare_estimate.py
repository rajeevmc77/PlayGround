from llm_compare.analysis.estimate import format_plan, plan_run
from llm_compare.analysis.runner import classify_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.models import ImagePair, Prices
from llm_compare.output.cache import VerdictCache, pair_cache_key
from tests.llm_compare_support import image_pair, png_bytes

FIRST, SECOND = (
    png_bytes(),
    png_bytes(box=(5, 5, 40, 30)),
)  # different bytes -> different cache keys


def _setup():
    keys = ("hi", "lo1", "lo2")
    pairs = [image_pair(k, pdf=f"images/{k}.png", web=f"web_images/{k}.png") for k in keys]
    pairs.append(ImagePair(row_id="web:w", key="W", pdf_path=None, web_path="web_images/w.png"))
    files = {}
    for key, png in zip(keys, (FIRST, FIRST, SECOND), strict=True):
        files[f"images/{key}.png"] = files[f"web_images/{key}.png"] = png
    scores = {"hi": 95.0, "lo1": 10.0, "lo2": 20.0}
    return pairs, files.get, (lambda pair, _a, _b: scores[pair.key])


def test_the_plan_counts_routes_calls_and_estimates_tokens_and_cost():
    pairs, load, scorer = _setup()
    config = LlmCompareConfig(model="m", max_pairs_per_call=6)
    plan = plan_run(pairs, load, config, VerdictCache(), "v1", Prices(1.0, 2.0), scorer)
    assert (plan.rows, plan.settled_by_hash, plan.web_only, plan.to_llm, plan.cached) == (
        4,
        1,
        1,
        2,
        0,
    )
    assert plan.calls == 1
    assert plan.input_tokens == 2 * 516 + config.call_overhead_tokens
    assert plan.output_tokens == 2 * config.output_tokens_per_pair
    assert plan.cost == (plan.input_tokens * 1.0 + plan.output_tokens * 2.0) / 1_000_000


def test_cached_pairs_are_not_planned_for_a_call():
    pairs, load, scorer = _setup()
    cache = VerdictCache()
    lo1 = prepare_pairs(classify_pairs(pairs, load, 90.0, scorer).to_llm[:1], 1024, 1.0)[0]
    cache.put(pair_cache_key(lo1, "v1", "m"), {"verdict": "IDENTICAL"})
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), cache, "v1", None, scorer)
    assert (plan.cached, plan.calls, plan.to_llm) == (1, 1, 2) and plan.cost is None


def test_zero_pairs_for_the_llm_plans_zero_calls_and_zero_cost():
    pairs, load, _ = _setup()
    plan = plan_run(
        pairs,
        load,
        LlmCompareConfig(model="m"),
        VerdictCache(),
        "v1",
        Prices(1.0, 2.0),
        lambda _p, _a, _b: 100.0,
    )
    assert (plan.to_llm, plan.calls, plan.input_tokens, plan.output_tokens) == (0, 0, 0, 0)
    assert plan.cost == 0.0


def test_format_plan_names_the_cost_or_says_it_is_unavailable():
    pairs, load, scorer = _setup()
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), VerdictCache(), "v1", None, scorer)
    text = format_plan(plan)
    assert "cost unavailable" in text and "LLM calls: 1" in text
    assert "settled by hash (free): 1" in text
