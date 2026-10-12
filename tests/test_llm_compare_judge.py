import asyncio
import base64
from dataclasses import replace

import dspy
import pytest

from llm_compare.analysis.judge import (
    DspyPairJudge,
    PairVerdictModel,
    build_manifest,
    map_litellm_error,
)
from llm_compare.analysis.prompt import INSTRUCTIONS, PROMPT_VERSION
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.errors import Permanent, RateLimited, Transient
from llm_compare.domain.models import Prices, Verdict
from tests.llm_compare_support import prepared_pair


class FakePrediction:
    def __init__(self, verdicts, usage):
        self.verdicts = verdicts
        self._usage = usage

    def get_lm_usage(self):
        return self._usage


class FakePredictor:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def acall(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


PRICES = Prices(1.0, 2.0)


def _judge(outcome, prices=PRICES):
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    predictor = FakePredictor(outcome)
    return DspyPairJudge(config, prices, predictor=predictor, lm=object()), predictor


def _run(judge, count=2):
    pairs = [prepared_pair(f"K{n}", pdf=f"images/{n}.png") for n in range(count)]
    return asyncio.run(judge.judge(pairs))


def test_the_prompt_is_the_agreed_text_and_versioned_by_hash():
    assert "IDENTICAL or DIFFERENT" in INSTRUCTIONS
    assert "Ignore Quality & Formatting Differences" in INSTRUCTIONS
    assert len(PROMPT_VERSION) == 12
    assert PROMPT_VERSION == __import__("hashlib").sha256(INSTRUCTIONS.encode()).hexdigest()[:12]


def test_the_manifest_numbers_each_pair_and_its_two_images():
    manifest = build_manifest(2)
    assert "PAIR 1: image 1 is A (PDF), image 2 is B (web)" in manifest
    assert "PAIR 2: image 3 is A (PDF), image 4 is B (web)" in manifest


def test_a_batch_becomes_one_call_with_images_in_pdf_then_web_order():
    prediction = FakePrediction(
        [
            PairVerdictModel(pair_id=1, verdict="IDENTICAL", differences=[]),
            PairVerdictModel(pair_id=2, verdict="DIFFERENT", differences=["label X missing"]),
        ],
        {"gemini/gemini-x": {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1100}},
    )
    judge, predictor = _judge(prediction)
    result = _run(judge)
    (call,) = predictor.calls
    assert len(call["images"]) == 4 and call["manifest"] == build_manifest(2)
    assert [(v.pair_id, v.verdict, v.differences) for v in result.verdicts] == [
        (1, Verdict.IDENTICAL, ()),
        (2, Verdict.DIFFERENT, ("label X missing",)),
    ]
    # output = max(total - prompt, completion): hidden thinking tokens are billed as output
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 100)
    assert result.usage.cost == pytest.approx((1000 * 1.0 + 100 * 2.0) / 1e6)


def test_verdicts_given_as_plain_dicts_are_accepted():
    prediction = FakePrediction([{"pair_id": 1, "verdict": "IDENTICAL", "differences": []}], {})
    result = _run(_judge(prediction)[0], count=1)
    assert result.verdicts[0].verdict is Verdict.IDENTICAL
    assert result.usage.input_tokens == 0


def test_unknown_price_leaves_cost_unknown():
    prediction = FakePrediction([], {"m": {"prompt_tokens": 5, "total_tokens": 9}})
    result = _run(_judge(prediction, prices=None)[0])
    assert result.usage.cost is None and result.usage.output_tokens == 4


@pytest.mark.parametrize(
    "bad",
    [
        {"pair_id": 1, "verdict": "identical", "differences": []},  # wrong case
        {"pair_id": 1, "verdict": "MAYBE", "differences": []},  # unknown label
        {"pair_id": "one", "verdict": "IDENTICAL", "differences": []},  # non-integer id
    ],
)
def test_a_malformed_verdict_counts_as_no_usable_answer_not_a_crash(bad):
    prediction = FakePrediction([bad], {})
    result = _run(_judge(prediction)[0])
    assert result.verdicts == [] and result.usage.input_tokens == 0


def test_a_parse_failure_inside_the_call_also_returns_no_verdicts():
    judge, _ = _judge(ValueError("could not parse"))
    assert _run(judge).verdicts == []


def _http(name, status=None, headers=None):
    """An exception whose class is called `name`, like litellm's, with optional status/headers."""
    error = type(name, (Exception,), {})(name)
    error.status_code = status
    error.response = type("R", (), {"headers": headers or {}})()
    return error


def test_rate_limits_carry_retry_after_and_server_errors_are_transient():
    limited = map_litellm_error(_http("RateLimitError", None, {"retry-after": "12"}))
    assert isinstance(limited, RateLimited) and limited.retry_after == 12.0
    assert map_litellm_error(_http("Whatever", 429)).retry_after is None
    assert isinstance(map_litellm_error(_http("InternalServerError", 500)), Transient)
    assert isinstance(map_litellm_error(_http("Whatever", 503)), Transient)
    assert isinstance(map_litellm_error(_http("Timeout")), Transient)
    assert isinstance(map_litellm_error(_http("BadRequestError", 400)), Permanent)
    assert isinstance(map_litellm_error(RuntimeError("boom")), Permanent)


def test_errors_from_the_call_are_mapped_to_judge_errors():
    judge, _ = _judge(_http("RateLimitError", 429))
    with pytest.raises(RateLimited):
        _run(judge)


def _tagged_pair(n):
    base = prepared_pair(f"K{n}", pdf=f"images/{n}.png")
    pdf = replace(base.pdf, png=f"pdf{n}".encode())
    web = replace(base.web, png=f"web{n}".encode())
    return replace(base, pdf=pdf, web=web)


def test_the_call_gets_the_injected_lm_and_images_pdf_then_web_per_pair():
    lm = object()
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    predictor = FakePredictor(FakePrediction([], {}))
    judge = DspyPairJudge(config, PRICES, predictor=predictor, lm=lm)
    asyncio.run(judge.judge([_tagged_pair(0), _tagged_pair(1)]))
    (call,) = predictor.calls
    assert call["lm"] is lm
    assert all(isinstance(image, dspy.Image) for image in call["images"])
    prefix = "data:image/png;base64,"
    decoded = []
    for image in call["images"]:
        assert image.url.startswith(prefix)
        decoded.append(base64.b64decode(image.url[len(prefix) :]))
    assert decoded == [b"pdf0", b"web0", b"pdf1", b"web1"]


def test_constructing_a_judge_leaves_the_global_usage_tracking_setting_alone():
    before = dspy.settings.track_usage
    _judge(FakePrediction([], {}))
    assert dspy.settings.track_usage == before


class SettingsProbe(FakePredictor):
    """Records the dspy settings in force while the call runs."""

    async def acall(self, **kwargs):
        self.seen = (dspy.settings.adapter, dspy.settings.track_usage)
        return await super().acall(**kwargs)


def test_the_call_runs_without_the_json_retry_and_with_usage_tracking_scoped_to_it():
    before = dspy.settings.track_usage
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    predictor = SettingsProbe(FakePrediction([], {}))
    judge = DspyPairJudge(config, PRICES, predictor=predictor, lm=object())
    _run(judge)
    adapter, tracking = predictor.seen
    assert isinstance(adapter, dspy.ChatAdapter) and adapter.use_json_adapter_fallback is False
    assert tracking is True
    assert dspy.settings.track_usage == before
