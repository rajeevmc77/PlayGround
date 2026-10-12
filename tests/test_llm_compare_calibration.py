import asyncio

from llm_compare.analysis.calibration import (
    ORIGINAL_EDGE,
    Variant,
    VariantResult,
    agreement,
    default_variants,
    format_calibration,
    judged_count,
    recommend,
    run_variants,
    sample_evenly,
)
from llm_compare.analysis.limiter import RateLimiter
from llm_compare.analysis.runner import JudgeDeps, ScoredPair
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.errors import Permanent
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
    # the one pair's own estimate (516 at 40x30 + 40x30) plus one call's overhead
    assert all(r.estimated_input_tokens == 516 + config.call_overhead_tokens for r in results)


def _estimated(name, edge, estimated, actual, verdicts):
    return VariantResult(Variant(name, edge, 1), actual, 0, 0.0, verdicts, estimated)


def test_each_variant_shows_estimated_vs_actual_input_tokens_and_the_implied_scale():
    base = {"a": Verdict.IDENTICAL}
    text = format_calibration(
        [_estimated("orig", ORIGINAL_EDGE, 8000, 9000, base), _estimated("768", 768, 0, 3, base)]
    )
    assert (
        "orig: estimated vs actual input tokens 8,000 vs 9,000 (implied token_scale 1.12)" in text
    )
    assert "768: estimated vs actual input tokens 0 vs 3 (implied token_scale n/a)" in text


def test_a_close_estimate_suggests_no_change_to_token_scale():
    base = {"a": Verdict.IDENTICAL}
    results = [_estimated("orig", ORIGINAL_EDGE, 1000, 1100, base)]
    assert "suggest" not in format_calibration(results)


def test_an_estimate_off_by_more_than_15_percent_suggests_the_token_scale_to_configure():
    base = {"a": Verdict.IDENTICAL}
    results = [
        _estimated("orig", ORIGINAL_EDGE, 1000, 1500, base),
        _estimated("768", 768, 1000, 1500, base),
    ]
    last = format_calibration(results, token_scale=1.2).splitlines()[-1]
    assert last == (
        "actual input tokens were 1.50x the estimate: suggest token_scale = 1.80 "
        "in llm_compare_config.toml"
    )


def test_no_usage_reported_suggests_nothing_and_divides_by_nothing():
    base = {"a": Verdict.ERROR}
    results = [_estimated("orig", ORIGINAL_EDGE, 1000, 0, base)]
    text = format_calibration(results)
    assert "implied token_scale n/a" in text and "suggest" not in text


def _twenty(verdict, judged=20):
    keys = [f"k{n}" for n in range(20)]
    return {k: (verdict if n < judged else Verdict.ERROR) for n, k in enumerate(keys)}


def test_a_candidate_that_errors_on_most_pairs_does_not_win_on_the_one_it_judged():
    results = [
        _result("orig", ORIGINAL_EDGE, 1, 9000, _twenty(Verdict.IDENTICAL)),
        _result("768", 768, 1, 100, _twenty(Verdict.IDENTICAL, judged=1)),
        _result("1024", 1024, 1, 5000, _twenty(Verdict.IDENTICAL)),
    ]
    assert recommend(results) == 1024
    assert "1/20" in format_calibration(results)
    assert "20/20" in format_calibration(results)


def test_a_candidate_must_judge_every_pair_the_baseline_judged():
    results = [
        _result("orig", ORIGINAL_EDGE, 1, 9000, {"a": Verdict.IDENTICAL}),
        _result("768", 768, 1, 100, {"a": Verdict.ERROR}),
    ]
    assert recommend(results) is None


def test_an_all_error_baseline_gives_no_recommendation_and_says_why():
    errors = {"a": Verdict.ERROR, "b": Verdict.ERROR}
    results = [_result("orig", ORIGINAL_EDGE, 1, 9, errors), _result("768", 768, 1, 3, errors)]
    assert recommend(results) is None
    last = format_calibration(results).splitlines()[-1]
    assert "baseline produced no verdicts" in last and "check the API errors first" in last


def test_an_empty_sample_says_nothing_was_routed_to_the_llm():
    assert recommend([]) is None
    results = [_result("orig", ORIGINAL_EDGE, 1, 0, {})]
    assert recommend(results) is None
    for shown in (results, []):
        text = format_calibration(shown)
        assert text.splitlines()[-1] == "no pairs were routed to the LLM: nothing to calibrate"


def test_no_smaller_cap_keeping_the_verdicts_says_to_keep_original_size():
    base = {"a": Verdict.IDENTICAL}
    results = [
        _result("o", ORIGINAL_EDGE, 1, 9, base),
        _result("768", 768, 1, 3, {"a": Verdict.DIFFERENT}),
    ]
    last = format_calibration(results).splitlines()[-1]
    assert last == "none of the smaller caps kept every verdict: keep original size"


def test_ties_on_input_tokens_keep_list_order():
    same = {"a": Verdict.IDENTICAL}
    results = [
        _result("o", ORIGINAL_EDGE, 1, 9, same),
        _result("1024", 1024, 1, 5, same),
        _result("768", 768, 1, 5, same),
    ]
    assert recommend(results) == 1024


def test_judged_count_counts_only_real_verdicts():
    verdicts = {"a": Verdict.IDENTICAL, "b": Verdict.DIFFERENT, "c": Verdict.ERROR}
    assert judged_count(verdicts) == 2
    assert judged_count({}) == 0


def test_batching_is_compared_directly_with_the_same_edge_single_variant():
    single = {"a": Verdict.IDENTICAL, "b": Verdict.DIFFERENT}
    batched = {"a": Verdict.IDENTICAL, "b": Verdict.IDENTICAL}
    results = [
        _result("o", ORIGINAL_EDGE, 1, 9, single),
        _result("1024", 1024, 1, 5, single),
        _result("1024x6", 1024, 6, 4, batched),
    ]
    assert "batched (6 per call) vs same-edge single: 50%" in format_calibration(results)


def test_a_batched_variant_without_a_same_edge_single_says_so():
    same = {"a": Verdict.IDENTICAL}
    results = [_result("o", ORIGINAL_EDGE, 1, 9, same), _result("512x4", 512, 4, 4, same)]
    assert "batched (4 per call): no same-edge single variant to compare" in format_calibration(
        results
    )


def test_sampling_zero_or_fewer_gives_nothing():
    assert sample_evenly([1, 2, 3], 0) == []
    assert sample_evenly([1, 2, 3], -2) == []


def _errored(name, edge, verdicts, first_error):
    return VariantResult(Variant(name, edge, 1), 0, 0, 0.0, verdicts, first_error=first_error)


def test_a_variant_that_judged_fewer_pairs_than_the_sample_shows_its_first_error():
    base = {"a": Verdict.IDENTICAL, "b": Verdict.IDENTICAL}
    broken = {"a": Verdict.ERROR, "b": Verdict.IDENTICAL}
    results = [
        _result("orig", ORIGINAL_EDGE, 1, 9, base),
        _errored("768px, 1 per call", 768, broken, "CERTIFICATE_VERIFY_FAILED: self-signed"),
    ]
    lines = format_calibration(results).splitlines()
    assert "768px, 1 per call: first error: CERTIFICATE_VERIFY_FAILED: self-signed" in lines


def test_a_fully_judged_variant_shows_no_error_line():
    base = {"a": Verdict.IDENTICAL}
    results = [_errored("orig", ORIGINAL_EDGE, base, "stale message")]
    assert "first error" not in format_calibration(results)


def test_a_variant_without_an_error_message_shows_no_error_line():
    results = [_result("orig", ORIGINAL_EDGE, 1, 9, {"a": Verdict.ERROR})]
    assert "first error" not in format_calibration(results)


def test_the_first_error_is_one_line_cut_to_about_200_characters():
    broken = {"a": Verdict.ERROR}
    message = "boom\n" + "x" * 500
    text = format_calibration([_errored("orig", ORIGINAL_EDGE, broken, message)])
    line = next(row for row in text.splitlines() if "first error" in row)
    assert line.startswith("orig: first error: boom xxx") and line.endswith("...")
    assert len(line) < len("orig: first error: ") + 210


def test_error_lines_come_before_the_closing_verdict_line():
    broken = {"a": Verdict.ERROR}
    text = format_calibration([_errored("orig", ORIGINAL_EDGE, broken, "bad key")])
    lines = text.splitlines()
    assert lines[-1].startswith("the original-size baseline produced no verdicts")
    assert lines[-2] == "orig: first error: bad key"


class AlwaysFails:
    def __init__(self, error):
        self.error = error

    async def judge(self, pairs):
        raise self.error


def test_run_variants_keeps_the_first_error_and_scrubs_the_api_key_from_it():
    secret = "AIzaFAKEKEY123"
    png = png_bytes()
    scored = [ScoredPair(image_pair("a", pdf="images/a.png"), png, png, 10.0)]
    config = LlmCompareConfig(api_key=secret, model="m", retry_base_delay=0.0)
    failing = AlwaysFails(Permanent(f"400 for https://x/v1?key={secret} bad request"))

    def make_deps(settings):
        return JudgeDeps(failing, RateLimiter(10_000, 10**9), VerdictCache(), settings, "v1")

    results = asyncio.run(run_variants(scored, default_variants(1024, 6)[:1], config, make_deps))
    assert results[0].first_error == "400 for https://x/v1?key=[redacted] bad request"
    assert secret not in format_calibration(results)


def test_a_fully_judged_run_records_no_first_error():
    png = png_bytes()
    scored = [ScoredPair(image_pair("a", pdf="images/a.png"), png, png, 10.0)]
    config = LlmCompareConfig(model="m", retry_base_delay=0.0)

    def make_deps(settings):
        return JudgeDeps(AllIdentical(), RateLimiter(10_000, 10**9), VerdictCache(), settings, "v1")

    results = asyncio.run(run_variants(scored, default_variants(1024, 6)[:1], config, make_deps))
    assert results[0].first_error == ""
