import pytest

from llm_compare.analysis.estimate import RunPlan, format_plan, plan_run
from llm_compare.analysis.runner import classify_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.models import ImagePair, Prices
from llm_compare.output.cache import VerdictCache, pair_cache_key
from tests.llm_compare_support import image_pair, png_bytes

FIRST, SECOND = (
    png_bytes(),
    png_bytes(box=(5, 5, 40, 30)),
)  # different bytes -> different cache keys
ENTRY = {
    "verdict": "IDENTICAL",
    "differences": [],
    "input_tokens": 10,
    "output_tokens": 1,
    "cost": None,
}


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
    cache.put(pair_cache_key(lo1, "v1", "m"), ENTRY)
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), cache, "v1", None, scorer)
    assert (plan.cached, plan.calls, plan.to_llm) == (1, 1, 2) and plan.cost is None


def test_a_malformed_cache_entry_is_planned_for_a_call_like_the_real_run_would():
    pairs, load, scorer = _setup()
    cache = VerdictCache()
    lo1 = prepare_pairs(classify_pairs(pairs, load, 90.0, scorer).to_llm[:1], 1024, 1.0)[0]
    cache.put(pair_cache_key(lo1, "v1", "m"), {"verdict": "IDENTICAL"})  # no tokens/cost
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), cache, "v1", None, scorer)
    assert (plan.cached, plan.to_llm) == (0, 2)


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


# ---- rough time -------------------------------------------------------------------------

ROUGH_NOTE = (
    "(calls / workers x ~10 s per call; measured 5-28 s per single-pair call with "
    'reasoning_effort = "" (default thinking); about 4-8 s with the "low" default)'
)


def _plan(calls, workers):
    return RunPlan(
        rows=10,
        settled_by_hash=0,
        web_only=0,
        skipped=0,
        to_llm=calls,
        cached=0,
        calls=calls,
        input_tokens=0,
        output_tokens=0,
        cost=0.0,
        workers=workers,
    )


def test_the_plan_remembers_the_worker_count_the_run_would_use():
    pairs, load, scorer = _setup()
    config = LlmCompareConfig(model="m", workers=3)
    plan = plan_run(pairs, load, config, VerdictCache(), "v1", None, scorer)
    assert plan.workers == 3


@pytest.mark.parametrize(
    ("calls", "workers", "shown"),
    [
        (1, 4, "~10 s"),  # one round of calls
        (3, 2, "~20 s"),  # two rounds
        (24, 4, "~1 min"),  # six rounds: exactly a minute
        (41, 4, "~2 min"),  # eleven rounds: 110 s, rounded up to whole minutes
        (5, 1, "~50 s"),  # under a minute stays in seconds
        (7, 1, "~2 min"),  # 70 s
    ],
)
def test_the_dry_run_gives_a_rough_time_labelled_as_such(calls, workers, shown):
    lines = format_plan(_plan(calls, workers)).splitlines()
    assert lines[-1] == f"rough time: {shown} {ROUGH_NOTE}"


def test_a_plan_with_no_calls_has_no_rough_time():
    text = format_plan(_plan(0, 4))
    assert "rough time" not in text and text.splitlines()[-1].startswith("estimated cost")


def test_a_zero_worker_plan_does_not_divide_by_zero():
    assert "rough time: ~10 s" in format_plan(_plan(1, 0))
