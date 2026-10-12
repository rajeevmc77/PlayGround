import asyncio
import json
import signal
import time
from dataclasses import replace

import pytest
from PIL import Image

from llm_compare.analysis.limiter import RateLimiter
from llm_compare.analysis.runner import (
    INTERRUPTED,
    JudgeDeps,
    classify_pairs,
    judge_pairs,
    prepare_pairs,
    run_comparison,
)
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.errors import Permanent, Transient
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import (
    ImagePair,
    PairVerdict,
    PdfLocation,
    Usage,
    Verdict,
    WebLocation,
)
from llm_compare.output.cache import VerdictCache, pair_cache_key
from tests.llm_compare_support import image_pair, png_bytes, prepared_pair

PNG = png_bytes()


def _files(*paths):
    return {path: PNG for path in paths}


def _loader(files):
    return lambda path: files.get(path)


def _pair(key, n=None):
    n = n or key
    return image_pair(key, pdf=f"images/{n}.png", web=f"web_images/{n}.png")


def _scores(**by_key):
    return lambda pair, pdf, web: by_key[pair.key]


class ScriptedJudge:
    def __init__(self, drop_in_batches=(), drop_always=(), error=None, fail_times=0):
        self.batches, self.drop_in_batches, self.drop_always = (
            [],
            set(drop_in_batches),
            set(drop_always),
        )
        self.error, self.fail_times = error, fail_times
        self.active = self.max_active = 0

    async def judge(self, pairs):
        self.batches.append([p.key for p in pairs])
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if self.fail_times:
            self.fail_times -= 1
            raise Transient("503")
        if self.error:
            raise self.error
        verdicts = [
            PairVerdict(n, Verdict.IDENTICAL, ())
            for n, p in enumerate(pairs, start=1)
            if p.key not in self.drop_always
            and not (len(pairs) > 1 and p.key in self.drop_in_batches)
        ]
        count = len(pairs)
        return JudgeResult(verdicts, Usage(100 * count, 10 * count, 0.01 * count))


def _deps(judge, cache=None, **overrides):
    settings = {
        "max_pairs_per_call": 3,
        "workers": 2,
        "rpm": 10_000,
        "tpm": 10**9,
        "retry_base_delay": 0.0,
        **overrides,
    }
    config = LlmCompareConfig(**settings)

    async def no_sleep(_):
        return None

    return JudgeDeps(
        judge=judge,
        limiter=RateLimiter(config.rpm, config.tpm),
        cache=cache or VerdictCache(),
        config=config,
        prompt_version="v1",
        sleep=no_sleep,
        jitter=lambda: 0.0,
    )


def _prepared(*keys):
    return [prepared_pair(k, tokens=100, pdf=f"images/{k}.png") for k in keys]


# ---- classify ---------------------------------------------------------------------------


def test_every_row_kind_is_settled_or_scored():
    web_only = ImagePair(
        row_id="web:w", key="W", pdf_path=None, web_path="web_images/w.png", web_key="W"
    )
    skipped = ImagePair(
        row_id="pdf:s",
        key="S",
        pdf_path="images/s.png",
        web_path=None,
        skip_reason="no web counterpart",
    )
    pairs = [_pair("hi"), _pair("lo"), web_only, skipped, _pair("gone")]
    files = _files("images/hi.png", "web_images/hi.png", "images/lo.png", "web_images/lo.png")
    result = classify_pairs(pairs, _loader(files), 90.0, _scores(hi=95.0, lo=40.0))
    assert result.settled["pdf:images/hi.png"].verdict is Verdict.MATCH_PHASH
    assert result.settled["pdf:images/hi.png"].score == 95.0
    assert result.settled["web:w"].verdict is Verdict.WEB_ONLY
    assert (result.settled["pdf:s"].verdict, result.settled["pdf:s"].message) == (
        Verdict.SKIPPED,
        "no web counterpart",
    )
    assert result.settled["pdf:images/gone.png"].message == "image file missing"
    assert [item.pair.key for item in result.to_llm] == ["lo"] and result.to_llm[0].score == 40.0


@pytest.mark.parametrize(("score", "verdict"), [(90.0, Verdict.MATCH_PHASH), (89.9, None)])
def test_the_90_percent_boundary_is_inclusive(score, verdict):
    files = _files("images/a.png", "web_images/a.png")
    result = classify_pairs([_pair("a")], _loader(files), 90.0, _scores(a=score))
    assert (verdict is None) == bool(result.to_llm)
    if verdict:
        assert result.settled["pdf:images/a.png"].verdict is verdict


def test_an_unreadable_image_is_skipped_with_the_reason():
    def scorer(pair, pdf, web):
        raise OSError("cannot identify image file")

    files = _files("images/a.png", "web_images/a.png")
    result = classify_pairs([_pair("a")], _loader(files), 90.0, scorer)
    record = result.settled["pdf:images/a.png"]
    assert record.verdict is Verdict.SKIPPED and "unreadable image" in record.message


def test_a_decompression_bomb_is_skipped_like_an_unreadable_image():
    def scorer(pair, pdf, web):
        raise Image.DecompressionBombError("too big")

    files = _files("images/a.png", "web_images/a.png")
    result = classify_pairs([_pair("a")], _loader(files), 90.0, scorer)
    record = result.settled["pdf:images/a.png"]
    assert record.verdict is Verdict.SKIPPED and "unreadable image" in record.message


# ---- judge_pairs ------------------------------------------------------------------------


def test_pairs_are_packed_into_calls_and_usage_is_split_across_them():
    judge = ScriptedJudge()
    deps = _deps(judge)
    records = asyncio.run(judge_pairs(_prepared(*"ABCDEFG"), deps))
    assert sorted(len(b) for b in judge.batches) == [1, 3, 3]
    assert deps.stats.calls == 3
    assert all(r.verdict is Verdict.IDENTICAL for r in records.values())
    assert sum(r.input_tokens for r in records.values()) == 700
    assert sum(r.output_tokens for r in records.values()) == 70
    assert sum(r.cost for r in records.values()) == pytest.approx(0.07)
    assert all(r.batch_id is not None and not r.cached for r in records.values())


def test_each_answered_call_adds_its_estimated_input_tokens_to_the_stats():
    judge = ScriptedJudge(drop_in_batches={"B"})
    deps = _deps(judge, call_overhead_tokens=50)
    asyncio.run(judge_pairs(_prepared("A", "B", "C"), deps))
    # [A, B, C] then B alone: every pair's estimated tokens plus each call's overhead
    assert deps.stats.estimated_input_tokens == (300 + 50) + (100 + 50)


def test_a_failed_call_adds_no_estimate():
    deps = _deps(ScriptedJudge(error=Permanent("x")))
    asyncio.run(judge_pairs(_prepared("A"), deps))
    assert deps.stats.estimated_input_tokens == 0


def test_nothing_to_judge_makes_no_call():
    judge = ScriptedJudge()
    assert asyncio.run(judge_pairs([], _deps(judge))) == {}
    assert judge.batches == []


def test_a_missing_id_is_retried_alone_and_usage_still_adds_up():
    judge = ScriptedJudge(drop_in_batches={"B"})
    records = asyncio.run(judge_pairs(_prepared("A", "B", "C"), _deps(judge)))
    assert judge.batches == [["A", "B", "C"], ["B"]]
    assert records["pdf:images/B.png"].verdict is Verdict.IDENTICAL
    assert sum(r.input_tokens for r in records.values()) == 300 + 100


def test_a_pair_that_never_gets_a_verdict_becomes_an_error_and_its_calls_count_as_waste():
    judge = ScriptedJudge(drop_always={"B"})
    deps = _deps(judge)
    records = asyncio.run(judge_pairs(_prepared("A", "B", "C"), deps))
    assert judge.batches == [["A", "B", "C"], ["B"], ["B"]]
    bad = records["pdf:images/B.png"]
    assert bad.verdict is Verdict.ERROR and "no usable verdict" in bad.message
    assert records["pdf:images/A.png"].verdict is Verdict.IDENTICAL
    assert deps.stats.wasted.input_tokens == 200


def test_a_permanent_error_fails_the_whole_batch_without_retrying():
    judge = ScriptedJudge(error=Permanent("bad request"))
    records = asyncio.run(judge_pairs(_prepared("A", "B"), _deps(judge)))
    assert len(judge.batches) == 1
    assert {r.verdict for r in records.values()} == {Verdict.ERROR}
    assert all(r.message == "bad request" for r in records.values())


def test_the_api_key_is_scrubbed_from_error_text_stored_in_rows():
    judge = ScriptedJudge(error=Permanent("401 for https://x/?key=s3cr3t-key (s3cr3t-key)"))
    records = asyncio.run(judge_pairs(_prepared("A"), _deps(judge, api_key="s3cr3t-key")))
    message = records["pdf:images/A.png"].message
    assert "s3cr3t-key" not in message
    assert message == "401 for https://x/?key=[redacted] ([redacted])"


def test_a_transient_error_is_retried_then_succeeds():
    judge = ScriptedJudge(fail_times=1)
    deps = _deps(judge)
    records = asyncio.run(judge_pairs(_prepared("A"), deps))
    assert deps.stats.calls == 2 and records["pdf:images/A.png"].verdict is Verdict.IDENTICAL


def test_a_second_run_is_served_from_the_cache_at_no_cost():
    cache = VerdictCache()
    first = ScriptedJudge()
    asyncio.run(judge_pairs(_prepared("A", "B"), _deps(first, cache)))
    second = ScriptedJudge()
    records = asyncio.run(judge_pairs(_prepared("A", "B"), _deps(second, cache)))
    assert second.batches == []
    assert all(r.cached and r.batch_id is None for r in records.values())
    assert sum(r.cost for r in records.values()) == pytest.approx(0.02)


GOOD_ENTRY = {
    "verdict": "IDENTICAL",
    "differences": [],
    "input_tokens": 10,
    "output_tokens": 1,
    "cost": 0.5,
}


@pytest.mark.parametrize(
    "entry",
    [
        {key: value for key, value in GOOD_ENTRY.items() if key != "verdict"},
        {key: value for key, value in GOOD_ENTRY.items() if key != "input_tokens"},
        {**GOOD_ENTRY, "verdict": "MAYBE"},
        {**GOOD_ENTRY, "verdict": "ERROR"},
        {**GOOD_ENTRY, "differences": "not a list"},
        {**GOOD_ENTRY, "differences": [1]},
        {**GOOD_ENTRY, "output_tokens": "1"},
        {**GOOD_ENTRY, "cost": "free"},
        "IDENTICAL",
    ],
)
def test_a_malformed_cache_entry_is_a_miss_and_the_pair_is_judged_again(entry):
    pair = _prepared("A")[0]
    cache = VerdictCache()
    cache.put(pair_cache_key(pair, "v1", ""), entry)
    judge = ScriptedJudge()
    records = asyncio.run(judge_pairs([pair], _deps(judge, cache)))
    assert judge.batches == [["A"]]
    assert records[pair.row_id].verdict is Verdict.IDENTICAL and not records[pair.row_id].cached


def test_a_well_formed_cache_entry_is_a_hit():
    pair = _prepared("A")[0]
    cache = VerdictCache()
    cache.put(pair_cache_key(pair, "v1", ""), {**GOOD_ENTRY, "cost": None})
    judge = ScriptedJudge()
    records = asyncio.run(judge_pairs([pair], _deps(judge, cache)))
    assert judge.batches == [] and records[pair.row_id].cached
    assert records[pair.row_id].cost is None


def test_errors_are_not_cached():
    cache = VerdictCache()
    asyncio.run(judge_pairs(_prepared("A"), _deps(ScriptedJudge(error=Permanent("x")), cache)))
    again = ScriptedJudge()
    asyncio.run(judge_pairs(_prepared("A"), _deps(again, cache)))
    assert again.batches == [["A"]]


def test_calls_never_exceed_the_worker_cap():
    judge = ScriptedJudge()
    asyncio.run(judge_pairs(_prepared(*"ABCDEF"), _deps(judge, max_pairs_per_call=1, workers=2)))
    assert judge.max_active == 2


# ---- run_comparison ---------------------------------------------------------------------


def test_a_whole_run_keeps_input_order_and_labels_every_row():
    keys = ["hi", "lo1", "lo2"]
    pairs = [_pair(k) for k in keys]
    files = _files(*[f"{d}/{k}.png" for k in keys for d in ("images", "web_images")])
    deps = _deps(ScriptedJudge())
    outcome = run_comparison(
        pairs, _loader(files), deps, scorer=_scores(hi=99.0, lo1=10.0, lo2=20.0)
    )
    assert [r.key for r in outcome.records] == keys
    assert [r.verdict for r in outcome.records] == [
        Verdict.MATCH_PHASH,
        Verdict.IDENTICAL,
        Verdict.IDENTICAL,
    ]
    assert outcome.calls == 1 and not outcome.interrupted


def test_when_everything_is_settled_by_the_hash_no_call_is_made():
    files = _files("images/a.png", "web_images/a.png")
    judge = ScriptedJudge()
    outcome = run_comparison([_pair("a")], _loader(files), _deps(judge), scorer=_scores(a=100.0))
    assert judge.batches == [] and outcome.calls == 0
    assert [r.verdict for r in outcome.records] == [Verdict.MATCH_PHASH]


def test_the_limit_judges_the_first_n_and_marks_the_rest_not_judged():
    keys = ["a", "b", "c"]
    files = _files(*[f"{d}/{k}.png" for k in keys for d in ("images", "web_images")])
    outcome = run_comparison(
        [_pair(k) for k in keys],
        _loader(files),
        _deps(ScriptedJudge()),
        limit=1,
        scorer=_scores(a=1.0, b=1.0, c=1.0),
    )
    assert [r.verdict for r in outcome.records] == [
        Verdict.IDENTICAL,
        Verdict.SKIPPED,
        Verdict.SKIPPED,
    ]
    assert "--limit" in outcome.records[1].message


class InterruptAfterFirst(ScriptedJudge):
    """Answers the first call, then the user presses Ctrl-C (a real SIGINT) during the second."""

    async def judge(self, pairs):
        if self.batches:
            self.batches.append([p.key for p in pairs])
            signal.raise_signal(signal.SIGINT)
            await asyncio.sleep(2)  # cancelled by the interrupt, never returns
        return await super().judge(pairs)


def test_an_interrupted_run_keeps_what_finished_and_saves_the_cache(tmp_path):
    keys = ["a", "b", "c"]
    files = {
        f"{d}/{k}.png": png_bytes(box=(5 + n, 5, 40, 30))
        for n, k in enumerate(keys)
        for d in ("images", "web_images")
    }
    cache = VerdictCache(tmp_path / "cache.json")
    deps = _deps(InterruptAfterFirst(), cache, max_pairs_per_call=1, workers=1)
    outcome = run_comparison(
        [_pair(k) for k in keys], _loader(files), deps, scorer=_scores(a=1.0, b=1.0, c=1.0)
    )
    assert outcome.interrupted and outcome.calls == 2
    first, *rest = outcome.records
    assert first.verdict is Verdict.IDENTICAL and not first.cached and first.input_tokens == 100
    assert [(r.verdict, r.message) for r in rest] == [(Verdict.ERROR, INTERRUPTED)] * 2
    assert len(json.loads((tmp_path / "cache.json").read_text())) == 1


def test_judge_pairs_writes_each_record_into_the_callers_dict():
    records: dict = {}
    returned = asyncio.run(judge_pairs(_prepared("A", "B"), _deps(ScriptedJudge()), records))
    assert returned is records and set(records) == {"pdf:images/A.png", "pdf:images/B.png"}


def test_prepare_pairs_estimates_tokens_from_the_prepared_sizes():
    from llm_compare.analysis.runner import ScoredPair

    scored = [ScoredPair(_pair("a"), PNG, PNG, 10.0)]
    (prepared,) = prepare_pairs(scored, max_edge=1024, token_scale=1.0)
    assert prepared.tokens == 516 and (prepared.pdf.width, prepared.pdf.height) == (40, 30)


# ---- timing -----------------------------------------------------------------------------


class FakeClock:
    """A clock that only moves when a test advances it (the judge, a scorer, a fake sleep)."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TickingClock:
    """Moves one second every time it is read, so a phase that reads it twice lasts 1 s."""

    def __init__(self):
        self.now = -1.0

    def __call__(self):
        self.now += 1.0
        return self.now


class TimedJudge(ScriptedJudge):
    """Each call takes the next figure of `seconds` on the fake clock (the last one repeats);
    a call that then fails still used its time."""

    def __init__(self, clock, seconds=(5.0,), **kwargs):
        super().__init__(**kwargs)
        self.clock, self.seconds = clock, list(seconds)

    async def judge(self, pairs):
        self.clock.advance(self.seconds[min(len(self.batches), len(self.seconds) - 1)])
        return await super().judge(pairs)


def _timed(judge, clock, limiter=None, cache=None, **overrides):
    deps = _deps(judge, cache, **overrides)
    return replace(deps, clock=clock, limiter=limiter or deps.limiter)


def test_each_completed_call_records_its_duration():
    clock = FakeClock()
    # one worker: calls running side by side would all see each other's fake-clock time
    deps = _timed(TimedJudge(clock, seconds=(2.0, 4.0, 6.0)), clock, workers=1)
    asyncio.run(judge_pairs(_prepared(*"ABCDEFG"), deps))
    assert deps.stats.calls == 3 and sorted(deps.stats.call_seconds) == [2.0, 4.0, 6.0]


def test_the_default_clock_is_the_monotonic_clock():
    assert _deps(ScriptedJudge()).clock is time.monotonic


def test_a_calls_duration_excludes_the_time_spent_waiting_for_the_rate_limiter():
    clock = FakeClock()

    async def waiting(seconds):
        clock.advance(seconds)

    limiter = RateLimiter(1, 10**9, clock=clock, sleep=waiting)
    deps = _timed(TimedJudge(clock), clock, limiter, max_pairs_per_call=1, workers=1)
    asyncio.run(judge_pairs(_prepared("A", "B"), deps))
    assert deps.stats.call_seconds == [5.0, 5.0]
    assert clock.now == 5.0 + 55.0 + 5.0  # the 55 s wait is on the clock but not in a call


def test_a_failed_attempt_is_not_timed_but_the_retry_that_succeeds_is():
    clock = FakeClock()
    deps = _timed(TimedJudge(clock, fail_times=1), clock)
    asyncio.run(judge_pairs(_prepared("A"), deps))
    assert deps.stats.calls == 2 and deps.stats.call_seconds == [5.0]


def test_a_call_that_fails_for_good_records_no_duration_and_its_rows_none():
    clock = FakeClock()
    deps = _timed(TimedJudge(clock, error=Permanent("bad")), clock)
    records = asyncio.run(judge_pairs(_prepared("A"), deps))
    assert deps.stats.call_seconds == []
    assert records["pdf:images/A.png"].call_seconds is None


def test_pairs_answered_by_one_call_share_its_duration_and_a_single_retry_has_its_own():
    clock = FakeClock()
    deps = _timed(TimedJudge(clock, seconds=(4.0, 9.0), drop_in_batches={"B"}), clock)
    records = asyncio.run(judge_pairs(_prepared("A", "B", "C"), deps))
    seconds = {r.key: r.call_seconds for r in records.values()}
    assert seconds == {"A": 4.0, "B": 9.0, "C": 4.0}
    assert deps.stats.call_seconds == [4.0, 9.0]


def test_calls_that_answered_nothing_usable_are_timed_but_their_error_rows_are_not():
    clock = FakeClock()
    deps = _timed(TimedJudge(clock, seconds=(4.0, 1.0), drop_always={"B"}), clock)
    records = asyncio.run(judge_pairs(_prepared("A", "B"), deps))
    assert deps.stats.call_seconds == [4.0, 1.0, 1.0]
    assert records["pdf:images/B.png"].verdict is Verdict.ERROR
    assert records["pdf:images/B.png"].call_seconds is None


def test_cached_rows_carry_no_duration_and_a_cached_run_times_no_calls():
    cache, clock = VerdictCache(), FakeClock()
    asyncio.run(judge_pairs(_prepared("A"), _timed(TimedJudge(clock), clock, cache=cache)))
    again = _timed(TimedJudge(clock), clock, cache=cache)
    records = asyncio.run(judge_pairs(_prepared("A"), again))
    assert records["pdf:images/A.png"].cached and records["pdf:images/A.png"].call_seconds is None
    assert again.stats.call_seconds == []


def _scored_files(keys):
    return _files(*[f"{d}/{k}.png" for k in keys for d in ("images", "web_images")])


class SlowScorer:
    """Scores every pair 10 (so the LLM judges it) and takes 3 s of the fake clock to do so."""

    def __init__(self, clock):
        self.clock = clock

    def __call__(self, pair, pdf, web):
        self.clock.advance(3.0)
        return 10.0


def test_a_run_times_scoring_and_judging_apart():
    clock = FakeClock()
    keys = ["a", "b"]
    outcome = run_comparison(
        [_pair(k) for k in keys],
        _loader(_scored_files(keys)),
        _timed(TimedJudge(clock, seconds=(5.0,)), clock),
        scorer=SlowScorer(clock),
    )
    assert outcome.scoring_seconds == 6.0 and outcome.judging_seconds == 5.0
    assert outcome.call_seconds == (5.0,) and outcome.calls == 1
    assert [r.call_seconds for r in outcome.records] == [5.0, 5.0]


def test_a_run_settled_by_the_hash_has_scoring_time_but_no_judging_or_calls():
    clock = FakeClock()

    def scorer(pair, pdf, web):
        clock.advance(2.0)
        return 100.0

    outcome = run_comparison(
        [_pair("a")], _loader(_scored_files(["a"])), _timed(ScriptedJudge(), clock), scorer=scorer
    )
    assert (outcome.scoring_seconds, outcome.judging_seconds) == (2.0, 0.0)
    assert outcome.call_seconds == ()


def test_a_run_answered_entirely_from_the_cache_still_measures_its_judging_phase():
    cache, clock = VerdictCache(), FakeClock()
    args = ([_pair("a")], _loader(_scored_files(["a"])))
    run_comparison(*args, _timed(TimedJudge(clock), clock, cache=cache), scorer=_scores(a=10.0))
    outcome = run_comparison(
        *args, _timed(ScriptedJudge(), TickingClock(), cache=cache), scorer=_scores(a=10.0)
    )
    assert outcome.calls == 0 and outcome.call_seconds == ()
    assert (outcome.scoring_seconds, outcome.judging_seconds) == (1.0, 1.0)
    assert outcome.records[0].cached


class TimedInterrupt(InterruptAfterFirst):
    """The first call takes 5 s and is answered; the second runs 7 s, then Ctrl-C."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    async def judge(self, pairs):
        self.clock.advance(7.0 if self.batches else 5.0)
        return await super().judge(pairs)


def test_an_interrupted_run_still_reports_its_timing_up_to_the_interrupt():
    clock, keys = FakeClock(), ["a", "b", "c"]
    files = {
        f"{d}/{k}.png": png_bytes(box=(5 + n, 5, 40, 30))
        for n, k in enumerate(keys)
        for d in ("images", "web_images")
    }
    deps = _timed(TimedInterrupt(clock), clock, max_pairs_per_call=1, workers=1)
    outcome = run_comparison(
        [_pair(k) for k in keys], _loader(files), deps, scorer=_scores(a=1.0, b=1.0, c=1.0)
    )
    assert outcome.interrupted and outcome.judging_seconds == 12.0
    assert outcome.call_seconds == (5.0,) and outcome.records[0].call_seconds == 5.0


# ---- locations --------------------------------------------------------------------------

PDF_AT = PdfLocation(3, 10.0, 20.0, 110.0, 70.0)
WEB_AT = WebLocation("web_pages/p.html", "/html/body/main/img[1]", 1, 2, 3, 4, "nbc.a.fig1")


def _located(key, **extra):
    return replace(_pair(key), pdf_location=PDF_AT, web_location=WEB_AT, **extra)


def _both_locations(record):
    return (record.pdf_location, record.web_location) == (PDF_AT, WEB_AT)


def test_every_kind_of_record_a_run_produces_carries_both_locations():
    keys = ["hi", "lo", "extra", "gone"]
    web_only = replace(_located("w"), row_id="web:w", pdf_path=None)
    skipped = _located("s", skip_reason="no web counterpart")
    pairs = [_located(k) for k in keys] + [web_only, skipped]
    outcome = run_comparison(
        pairs,
        _loader(_scored_files(["hi", "lo", "extra"])),
        _timed(ScriptedJudge(), FakeClock()),
        limit=1,
        scorer=_scores(hi=99.0, lo=10.0, extra=10.0),
    )
    verdicts = {r.key: r.verdict for r in outcome.records}
    assert verdicts == {
        "hi": Verdict.MATCH_PHASH,
        "lo": Verdict.IDENTICAL,
        "extra": Verdict.SKIPPED,  # past --limit
        "gone": Verdict.SKIPPED,  # image file missing
        "w": Verdict.WEB_ONLY,
        "s": Verdict.SKIPPED,
    }
    assert all(_both_locations(r) for r in outcome.records)


def _prepared_located(key):
    prepared = prepared_pair(key, tokens=100, pdf=f"images/{key}.png")
    return replace(prepared, pair=replace(prepared.pair, pdf_location=PDF_AT, web_location=WEB_AT))


def test_cached_error_and_interrupted_records_carry_both_locations():
    cache = VerdictCache()
    asyncio.run(judge_pairs([_prepared_located("A")], _deps(ScriptedJudge(), cache)))
    cached = asyncio.run(judge_pairs([_prepared_located("A")], _deps(ScriptedJudge(), cache)))
    failed = asyncio.run(
        judge_pairs([_prepared_located("B")], _deps(ScriptedJudge(error=Permanent("x"))))
    )
    assert cached["pdf:images/A.png"].cached and _both_locations(cached["pdf:images/A.png"])
    assert failed["pdf:images/B.png"].verdict is Verdict.ERROR
    assert _both_locations(failed["pdf:images/B.png"])


def test_a_pair_never_answered_keeps_its_locations_on_its_error_row():
    judge = ScriptedJudge(drop_always={"B"})
    records = asyncio.run(judge_pairs([_prepared_located("B")], _deps(judge)))
    assert "no usable verdict" in records["pdf:images/B.png"].message
    assert _both_locations(records["pdf:images/B.png"])


def test_an_interrupted_pair_keeps_its_locations_on_its_error_row():
    clock, keys = FakeClock(), ["a", "b"]
    files = {
        f"{d}/{k}.png": png_bytes(box=(5 + n, 5, 40, 30))
        for n, k in enumerate(keys)
        for d in ("images", "web_images")
    }
    deps = _timed(TimedInterrupt(clock), clock, max_pairs_per_call=1, workers=1)
    outcome = run_comparison(
        [_located(k) for k in keys], _loader(files), deps, scorer=_scores(a=1.0, b=1.0)
    )
    assert outcome.records[1].message == INTERRUPTED and _both_locations(outcome.records[1])
