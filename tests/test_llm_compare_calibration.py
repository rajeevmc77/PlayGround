import asyncio

from llm_compare.analysis.calibration import (
    ORIGINAL_EDGE,
    Variant,
    VariantResult,
    agreement,
    default_variants,
    format_calibration,
    recommend,
    run_variants,
    sample_evenly,
)
from llm_compare.analysis.limiter import RateLimiter
from llm_compare.analysis.runner import JudgeDeps, ScoredPair
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import PairVerdict, Usage, Verdict
from llm_compare.output.cache import VerdictCache
from tests.llm_compare_support import image_pair, png_bytes


def test_sampling_is_even_deterministic_and_bounded():
    assert sample_evenly(list(range(10)), 5) == [0, 2, 4, 6, 8]
    assert sample_evenly([1, 2, 3], 10) == [1, 2, 3]
    assert sample_evenly([], 3) == []


def test_agreement_counts_matching_verdicts_among_pairs_both_judged():
    base = {"a": Verdict.IDENTICAL, "b": Verdict.DIFFERENT, "c": Verdict.IDENTICAL}
    other = {
        "a": Verdict.IDENTICAL,
        "b": Verdict.IDENTICAL,
        "d": Verdict.IDENTICAL,
        "c": Verdict.ERROR,
    }
    assert agreement(base, other) == 0.5
    assert agreement(base, {}) == 0.0


def test_default_variants_start_with_the_original_size_baseline():
    variants = default_variants(1024, 6)
    assert [(v.max_edge, v.max_pairs_per_call) for v in variants] == [
        (ORIGINAL_EDGE, 1),
        (768, 1),
        (1024, 1),
        (1024, 6),
    ]


def _result(name, edge, batch, tokens, verdicts):
    return VariantResult(Variant(name, edge, batch), tokens, 0, 0.0, verdicts)


def test_recommend_picks_the_smallest_cap_that_keeps_every_verdict():
    same = {"a": Verdict.IDENTICAL, "b": Verdict.DIFFERENT}
    changed = {"a": Verdict.DIFFERENT, "b": Verdict.DIFFERENT}
    results = [
        _result("orig", ORIGINAL_EDGE, 1, 9000, same),
        _result("768", 768, 1, 3000, changed),
        _result("1024", 1024, 1, 5000, same),
        _result("1024x6", 1024, 6, 4000, same),
    ]
    assert recommend(results) == 1024


def test_recommend_gives_none_when_no_cap_keeps_the_verdicts():
    base = {"a": Verdict.IDENTICAL}
    results = [
        _result("o", ORIGINAL_EDGE, 1, 9, base),
        _result("768", 768, 1, 3, {"a": Verdict.DIFFERENT}),
    ]
    assert recommend(results) is None


def test_the_table_shows_tokens_and_agreement_for_every_variant():
    base = {"a": Verdict.IDENTICAL}
    text = format_calibration(
        [_result("orig", ORIGINAL_EDGE, 1, 9000, base), _result("768", 768, 1, 3000, base)]
    )
    assert "orig" in text and "9,000" in text and "100%" in text
    assert "recommended max_edge: 768" in text


class AllIdentical:
    async def judge(self, pairs):
        verdicts = [PairVerdict(n, Verdict.IDENTICAL, ()) for n in range(1, len(pairs) + 1)]
        return JudgeResult(verdicts, Usage(10 * len(pairs), len(pairs), 0.0))


def test_run_variants_judges_the_same_sample_once_per_variant_with_fresh_caches():
    png = png_bytes()
    scored = [ScoredPair(image_pair("a", pdf="images/a.png"), png, png, 10.0)]
    config = LlmCompareConfig(model="m", retry_base_delay=0.0)

    def make_deps(settings):
        return JudgeDeps(AllIdentical(), RateLimiter(10_000, 10**9), VerdictCache(), settings, "v1")

    results = asyncio.run(run_variants(scored, default_variants(1024, 6), config, make_deps))
    assert [r.variant.max_pairs_per_call for r in results] == [1, 1, 1, 6]
    assert all(r.verdicts == {"pdf:images/a.png": Verdict.IDENTICAL} for r in results)
    assert all(r.input_tokens == 10 for r in results)
