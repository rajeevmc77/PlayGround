import asyncio
import base64
from dataclasses import replace

import dspy
import pytest
from dspy import lm15
from dspy.utils.exceptions import (
    AdapterParseError,
    LMAuthError,
    LMBillingError,
    LMInvalidRequestError,
    LMLockTimeoutError,
    LMProviderError,
    LMRateLimitError,
    LMServerError,
    LMTimeoutError,
    LMTransportError,
    LMUnexpectedError,
)

from llm_compare.analysis.judge import (
    DspyPairJudge,
    PairVerdictModel,
    build_manifest,
    build_signature,
    map_litellm_error,
)
from llm_compare.analysis.prompt import INSTRUCTIONS, PROMPT_VERSION
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.errors import Permanent, RateLimited, Transient
from llm_compare.domain.models import Prices, Verdict
from tests.llm_compare_support import prepared_pair

CALL_USAGE = {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1100}


class FakePrediction:
    def __init__(self, verdicts, usage=None):
        self.verdicts = verdicts
        self.usage = usage  # what the LM call behind this prediction billed


class FakePredictor:
    """Stands in for dspy.Predict. Like dspy's own LM it books the call's usage on the usage
    tracker in force before anything parses the answer, then returns the prediction or raises
    the error (a parse failure after a billed call)."""

    def __init__(self, outcome, usage=None):
        self.outcome = outcome
        self.usage = usage if usage is not None else getattr(outcome, "usage", None)
        self.calls = []

    async def acall(self, **kwargs):
        self.calls.append(kwargs)
        tracker = dspy.settings.usage_tracker
        if self.usage and tracker is not None:
            tracker.add_usage("gemini/gemini-x", dict(self.usage))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


PRICES = Prices(1.0, 2.0)


def _judge(outcome, prices=PRICES, usage=None):
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    predictor = FakePredictor(outcome, usage)
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
        CALL_USAGE,
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
    prediction = FakePrediction([{"pair_id": 1, "verdict": "IDENTICAL", "differences": []}])
    result = _run(_judge(prediction)[0], count=1)
    assert result.verdicts[0].verdict is Verdict.IDENTICAL
    assert result.usage.input_tokens == 0  # nothing was booked


def test_unknown_price_leaves_cost_unknown():
    prediction = FakePrediction([], {"prompt_tokens": 5, "total_tokens": 9})
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
def test_a_malformed_verdict_counts_as_no_usable_answer_but_its_spend_is_kept(bad):
    prediction = FakePrediction([bad], CALL_USAGE)
    result = _run(_judge(prediction)[0])
    assert result.verdicts == []
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 100)


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("could not parse"),
        AdapterParseError("ChatAdapter", build_signature(INSTRUCTIONS), "they look the same"),
    ],
)
def test_a_parse_failure_inside_the_call_returns_no_verdicts_but_the_usage_it_spent(failure):
    judge, _ = _judge(failure, usage=CALL_USAGE)
    result = _run(judge)
    assert result.verdicts == []
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 100)
    assert result.usage.cost == pytest.approx((1000 * 1.0 + 100 * 2.0) / 1e6)


def test_the_real_lm_caps_output_at_max_output_tokens():
    config = LlmCompareConfig(api_key="k", model="gemini-x", max_output_tokens=4096)
    assert DspyPairJudge(config, PRICES)._lm.kwargs["max_tokens"] == 4096


def test_the_real_lm_bounds_a_request_by_request_timeout_seconds():
    """dspy 3.4's native transport waits up to 600 s for a reply unless the LM is given a
    timeout; the configured one must reach lm15's read/write/pool waits."""
    from dspy.clients.engines.lm15_engine import timeouts_for

    config = LlmCompareConfig(api_key="k", model="gemini-x", request_timeout_seconds=45.0)
    judge = DspyPairJudge(config, PRICES)
    timeouts = timeouts_for(judge._lm.kwargs["timeout"])
    assert (timeouts.read, timeouts.write, timeouts.pool) == (45.0, 45.0, 45.0)


def test_the_default_request_timeout_is_120_seconds_for_the_read_wait():
    from dspy.clients.engines.lm15_engine import timeouts_for

    judge = DspyPairJudge(LlmCompareConfig(api_key="k", model="gemini-x"), PRICES)
    assert timeouts_for(judge._lm.kwargs["timeout"]).read == 120.0


def test_the_real_lm_sends_the_default_reasoning_effort_low():
    judge = DspyPairJudge(LlmCompareConfig(api_key="k", model="gemini-x"), PRICES)
    assert judge._lm.kwargs["reasoning_effort"] == "low"


@pytest.mark.parametrize("effort", ["minimal", "medium", "high", "off"])
def test_the_real_lm_sends_the_configured_reasoning_effort(effort):
    config = LlmCompareConfig(api_key="k", model="gemini-x", reasoning_effort=effort)
    assert DspyPairJudge(config, PRICES)._lm.kwargs["reasoning_effort"] == effort


def test_an_empty_reasoning_effort_sends_no_reasoning_effort_at_all():
    config = LlmCompareConfig(api_key="k", model="gemini-x", reasoning_effort="")
    assert "reasoning_effort" not in DspyPairJudge(config, PRICES)._lm.kwargs


def test_the_reasoning_effort_leaves_the_other_request_settings_unchanged():
    lm = DspyPairJudge(LlmCompareConfig(api_key="k", model="gemini-x"), PRICES)._lm
    assert (lm.kwargs["temperature"], lm.kwargs["max_tokens"]) == (0.0, 8192)
    assert (lm.num_retries, lm.cache) == (0, False)


def test_a_request_that_times_out_is_transient_so_the_limiter_retries_it():
    assert isinstance(map_litellm_error(LMTimeoutError("timed out after 120 s")), Transient)


# ---- the real DSPy pipeline, offline ----------------------------------------------------
# dspy.LM accepts a custom engine (complete(Request) -> Response); this one returns a canned
# completion with usage, or raises a dspy.lm15 error, so the real Predict + ChatAdapter +
# usage tracking + error wrapping all run without a network call.


class CannedEngine:
    def __init__(self, text="", error=None):
        self.text, self.error, self.requests = text, error, []

    async def complete(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return lm15.Response(
            id=None,
            model="gemini-x",
            message=lm15.Message.assistant([lm15.TextPart(self.text)]),
            finish_reason="stop",
            usage=lm15.Usage(input_tokens=1000, output_tokens=50, total_tokens=1200),
        )


class NoSyncEngine:
    """dspy.LM wants a sync engine beside the async one; the judge only calls async."""

    def complete(self, request):
        raise NotImplementedError


def _real_pipeline(engine):
    lm = dspy.LM(
        "gemini/gemini-x",
        engine=NoSyncEngine(),
        async_engine=engine,
        temperature=0.0,
        max_tokens=8192,
        num_retries=0,
        cache=False,
    )
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    return DspyPairJudge(config, PRICES, lm=lm)


GOOD_ANSWER = (
    "[[ ## verdicts ## ]]\n"
    '[{"pair_id": 1, "verdict": "IDENTICAL", "differences": []}, '
    '{"pair_id": 2, "verdict": "DIFFERENT", "differences": ["label X missing"]}]\n\n'
    "[[ ## completed ## ]]"
)


def test_the_real_pipeline_parses_a_canonical_answer_and_reports_its_usage():
    engine = CannedEngine(GOOD_ANSWER)
    result = _run(_real_pipeline(engine))
    assert [(v.pair_id, v.verdict, v.differences) for v in result.verdicts] == [
        (1, Verdict.IDENTICAL, ()),
        (2, Verdict.DIFFERENT, ("label X missing",)),
    ]
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    (request,) = engine.requests
    images = [part for message in request.messages for part in message.parts]
    assert sum(type(part).__name__ == "ImagePart" for part in images) == 4
    assert request.config.max_tokens == 8192


def test_the_real_pipeline_keeps_the_usage_of_an_unparsable_answer():
    result = _run(_real_pipeline(CannedEngine("I think they look the same")))
    assert result.verdicts == []
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    assert result.usage.cost == pytest.approx((1000 * 1.0 + 200 * 2.0) / 1e6)


def test_the_real_pipeline_surfaces_a_provider_429_as_rate_limited():
    error = lm15.RateLimitError("slow down", status=429, retry_after=7.0)
    with pytest.raises(RateLimited) as raised:
        _run(_real_pipeline(CannedEngine(error=error)))
    assert raised.value.retry_after == 7.0


def test_the_real_pipeline_surfaces_a_provider_503_as_transient():
    error = lm15.ServerError("unavailable", status=503)
    with pytest.raises(Transient):
        _run(_real_pipeline(CannedEngine(error=error)))


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


def test_dspy_rate_limit_errors_are_rate_limited_with_their_retry_after():
    limited = map_litellm_error(LMRateLimitError("slow down", status=429, retry_after=7.0))
    assert isinstance(limited, RateLimited) and limited.retry_after == 7.0
    unhinted = map_litellm_error(LMRateLimitError("slow down", status=429))
    assert isinstance(unhinted, RateLimited) and unhinted.retry_after is None


def test_a_dspy_error_with_status_429_is_rate_limited_whatever_its_class():
    assert isinstance(map_litellm_error(LMProviderError("quota", status=429)), RateLimited)


@pytest.mark.parametrize(
    "error",
    [
        LMServerError("unavailable", status=503),
        LMServerError("internal"),
        LMTimeoutError("timed out"),
        LMTransportError("connection reset"),
        LMLockTimeoutError("credential lock busy"),
        LMProviderError("bad gateway", status=502),
    ],
)
def test_retryable_dspy_errors_are_transient(error):
    assert type(map_litellm_error(error)) is Transient


@pytest.mark.parametrize(
    "error",
    [
        LMInvalidRequestError("bad image", status=400),
        LMAuthError("bad key", status=401),
        LMBillingError("no credit", status=402),
        LMUnexpectedError("engine bug"),
        LMProviderError("nope", status=404),
    ],
)
def test_other_dspy_errors_are_permanent(error):
    assert type(map_litellm_error(error)) is Permanent


def test_a_real_dspy_rate_limit_from_the_call_is_rate_limited():
    judge, _ = _judge(LMRateLimitError("slow down", status=429, retry_after=3.0))
    with pytest.raises(RateLimited) as raised:
        _run(judge)
    assert raised.value.retry_after == 3.0


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


def test_the_real_signature_takes_manifest_and_images_and_returns_typed_verdicts():
    signature = build_signature(INSTRUCTIONS)
    assert set(signature.input_fields) == {"manifest", "images"}
    assert set(signature.output_fields) == {"verdicts"}
    assert signature.instructions == INSTRUCTIONS.strip()


def test_without_an_injected_predictor_the_judge_builds_the_real_dspy_one():
    config = LlmCompareConfig(api_key="k", model="gemini-x")
    judge = DspyPairJudge(config, PRICES, lm=object())
    assert isinstance(judge._predictor, dspy.Predict)
    assert set(judge._predictor.signature.input_fields) == {"manifest", "images"}
