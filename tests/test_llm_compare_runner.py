import asyncio

import pytest
from PIL import Image

from llm_compare.analysis.limiter import RateLimiter
from llm_compare.analysis.runner import (
    JudgeDeps,
    classify_pairs,
    judge_pairs,
    prepare_pairs,
    run_comparison,
)
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.errors import Permanent, Transient
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import ImagePair, PairVerdict, Usage, Verdict
from llm_compare.output.cache import VerdictCache
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
    outcome = asyncio.run(
        run_comparison(pairs, _loader(files), deps, scorer=_scores(hi=99.0, lo1=10.0, lo2=20.0))
    )
    assert [r.key for r in outcome.records] == keys
    assert [r.verdict for r in outcome.records] == [
        Verdict.MATCH_PHASH,
        Verdict.IDENTICAL,
        Verdict.IDENTICAL,
    ]
    assert outcome.calls == 1


def test_when_everything_is_settled_by_the_hash_no_call_is_made():
    files = _files("images/a.png", "web_images/a.png")
    judge = ScriptedJudge()
    outcome = asyncio.run(
        run_comparison([_pair("a")], _loader(files), _deps(judge), scorer=_scores(a=100.0))
    )
    assert judge.batches == [] and outcome.calls == 0
    assert [r.verdict for r in outcome.records] == [Verdict.MATCH_PHASH]


def test_the_limit_judges_the_first_n_and_marks_the_rest_not_judged():
    keys = ["a", "b", "c"]
    files = _files(*[f"{d}/{k}.png" for k in keys for d in ("images", "web_images")])
    outcome = asyncio.run(
        run_comparison(
            [_pair(k) for k in keys],
            _loader(files),
            _deps(ScriptedJudge()),
            limit=1,
            scorer=_scores(a=1.0, b=1.0, c=1.0),
        )
    )
    assert [r.verdict for r in outcome.records] == [
        Verdict.IDENTICAL,
        Verdict.SKIPPED,
        Verdict.SKIPPED,
    ]
    assert "--limit" in outcome.records[1].message


def test_prepare_pairs_estimates_tokens_from_the_prepared_sizes():
    from llm_compare.analysis.runner import ScoredPair

    scored = [ScoredPair(_pair("a"), PNG, PNG, 10.0)]
    (prepared,) = prepare_pairs(scored, max_edge=1024, token_scale=1.0)
    assert prepared.tokens == 516 and (prepared.pdf.width, prepared.pdf.height) == (40, 30)
