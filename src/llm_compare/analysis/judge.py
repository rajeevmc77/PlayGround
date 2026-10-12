"""The DSPy implementation of PairJudge: one multimodal call judges a numbered batch of
image pairs and returns a structured verdict per pair."""

import base64
from collections.abc import Sequence
from typing import Literal

import dspy
from dspy.utils.exceptions import AdapterParseError, LMRateLimitError, is_retryable_lm_error
from dspy.utils.usage_tracker import track_usage
from pydantic import BaseModel, Field

from llm_compare.analysis.prompt import INSTRUCTIONS
from llm_compare.config import LlmCompareConfig, litellm_model
from llm_compare.domain.costing import cost_of
from llm_compare.domain.errors import JudgeError, Permanent, RateLimited, Transient
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import PairVerdict, PreparedPair, Prices, Usage, Verdict

_PARSE_ERRORS: tuple[type[Exception], ...] = (AdapterParseError, ValueError)

# LiteLLM-shaped errors (by class name), for an engine that does not wrap them.
_TRANSIENT_NAMES = {
    "Timeout",
    "APIConnectionError",
    "InternalServerError",
    "ServiceUnavailableError",
    "BadGatewayError",
}


class PairVerdictModel(BaseModel):
    pair_id: int
    verdict: Literal["IDENTICAL", "DIFFERENT"]
    differences: list[str] = Field(default_factory=list)


def build_signature(instructions: str) -> type[dspy.Signature]:
    class CompareImagePairs(dspy.Signature):
        manifest: str = dspy.InputField(desc="Which image belongs to which numbered pair.")
        images: list[dspy.Image] = dspy.InputField(desc="Images in manifest order.")
        verdicts: list[PairVerdictModel] = dspy.OutputField(desc="One verdict per pair.")

    return CompareImagePairs.with_instructions(instructions)


def build_manifest(count: int) -> str:
    lines = [f"This call holds {count} numbered pair(s). Images are given in the order listed."]
    for number in range(1, count + 1):
        first = 2 * number - 1
        lines.append(f"PAIR {number}: image {first} is A (PDF), image {first + 1} is B (web)")
    return "\n".join(lines)


def _to_image(png: bytes) -> dspy.Image:
    return dspy.Image(url="data:image/png;base64," + base64.b64encode(png).decode())


def _retry_after(error: Exception) -> float | None:
    hint = getattr(error, "retry_after", None)
    if hint is None:
        headers = getattr(getattr(error, "response", None), "headers", None) or {}
        hint = headers.get("retry-after")
    try:
        return float(hint)
    except (TypeError, ValueError):
        return None


def _status(error: Exception) -> int | None:
    """dspy's LM errors carry `.status`; LiteLLM-shaped ones `.status_code`."""
    status = getattr(error, "status", None)
    return status if isinstance(status, int) else getattr(error, "status_code", None)


def _is_rate_limit(error: Exception) -> bool:
    if isinstance(error, LMRateLimitError) or _status(error) == 429:
        return True
    return type(error).__name__ == "RateLimitError"


def _is_transient(error: Exception) -> bool:
    status = _status(error)
    if is_retryable_lm_error(error) or (isinstance(status, int) and status >= 500):
        return True
    return type(error).__name__ in _TRANSIENT_NAMES


def map_litellm_error(error: Exception) -> JudgeError:
    """dspy 3.4 raises its own LM errors (LMRateLimitError, LMServerError, LMTimeoutError,
    LMTransportError, ...); LiteLLM-shaped ones (name/status_code/response.headers) still map."""
    if _is_rate_limit(error):
        return RateLimited(str(error), _retry_after(error))
    if _is_transient(error):
        return Transient(str(error))
    return Permanent(str(error))


def _token_sum(per_model: dict, key: str) -> int:
    return sum(int(model.get(key) or 0) for model in per_model.values())


def _usage_of(per_model: dict, prices: Prices | None) -> Usage:
    prompt = _token_sum(per_model, "prompt_tokens")
    completion = _token_sum(per_model, "completion_tokens")
    total = _token_sum(per_model, "total_tokens")
    output = max(total - prompt, completion)
    return Usage(prompt, output, cost_of(prompt, output, prices))


def _verdicts_of(prediction) -> list[PairVerdict]:
    parsed = [PairVerdictModel.model_validate(item) for item in prediction.verdicts]
    return [
        PairVerdict(item.pair_id, Verdict(item.verdict), tuple(item.differences)) for item in parsed
    ]


def _build_lm(config: LlmCompareConfig) -> dspy.LM:
    # An empty reasoning_effort sends nothing, leaving the model's own default thinking.
    effort = {"reasoning_effort": config.reasoning_effort} if config.reasoning_effort else {}
    return dspy.LM(
        litellm_model(config.model),
        api_key=config.api_key,
        temperature=0.0,
        # Caps output (thinking included): a looping answer is the one that fails to
        # parse and is re-queued, so an uncapped one would be billed again and again.
        max_tokens=config.max_output_tokens,
        num_retries=0,
        cache=False,
        # Without it the native transport waits up to 600 s for a reply (a hung request
        # once stalled a run ~18 min); a timeout is Transient, so the limiter retries it.
        timeout=config.request_timeout_seconds,
        **effort,
    )


class DspyPairJudge:
    def __init__(
        self,
        config: LlmCompareConfig,
        prices: Prices | None,
        *,
        predictor=None,
        lm=None,
        instructions: str = INSTRUCTIONS,
    ):
        self._prices = prices
        self._lm = lm or _build_lm(config)
        self._predictor = predictor or dspy.Predict(build_signature(instructions))
        # No silent second (JSON) attempt: every billed call must go through our limiter.
        self._adapter = dspy.ChatAdapter(use_json_adapter_fallback=False)

    async def judge(self, pairs: Sequence[PreparedPair]) -> JudgeResult:
        images = [_to_image(side.png) for pair in pairs for side in (pair.pdf, pair.web)]
        # Our own tracker: dspy books the LM's usage on it before the adapter parses the
        # answer, so a call whose answer fails to parse still reports what it cost.
        with track_usage() as tracker:
            try:
                with dspy.context(adapter=self._adapter, track_usage=True):
                    prediction = await self._predictor.acall(
                        manifest=build_manifest(len(pairs)), images=images, lm=self._lm
                    )
            except _PARSE_ERRORS:
                prediction = None
            except Exception as error:
                raise map_litellm_error(error) from error
        return self._result(prediction, _usage_of(tracker.get_total_tokens(), self._prices))

    def _result(self, prediction, usage: Usage) -> JudgeResult:
        if prediction is None:
            return JudgeResult([], usage)
        try:
            return JudgeResult(_verdicts_of(prediction), usage)
        except _PARSE_ERRORS:
            return JudgeResult([], usage)
