"""Runs the comparison: route each pair by its hash score, prepare the images that need the
LLM, pack them into calls, judge the calls concurrently inside the rate limits, re-queue
unusable answers one pair at a time, and remember every verdict."""

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from llm_compare.analysis.hash_score import score_pair
from llm_compare.analysis.limiter import RateLimiter, call_with_retries
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.batching import estimate_call_tokens, estimate_image_tokens, pack
from llm_compare.domain.costing import add_usage, split_usage
from llm_compare.domain.errors import JudgeError
from llm_compare.domain.judge import PairJudge
from llm_compare.domain.models import (
    ImagePair,
    PairRecord,
    PairVerdict,
    PreparedPair,
    Route,
    Usage,
    Verdict,
)
from llm_compare.domain.selection import route_for
from llm_compare.domain.verdicts import validate_verdicts
from llm_compare.output.cache import VerdictCache, pair_cache_key
from llm_compare.parsing.preprocess import prepare_image

LoadBytes = Callable[[str], bytes | None]
Scorer = Callable[[ImagePair, bytes, bytes], float]

# What an image the scorer cannot read raises: a corrupt file (OSError/ValueError) or one
# Pillow refuses to decode because it is absurdly large (DecompressionBombError is neither).
_UNREADABLE = (OSError, ValueError, Image.DecompressionBombError)


@dataclass(frozen=True)
class ScoredPair:
    pair: ImagePair
    pdf_bytes: bytes
    web_bytes: bytes
    score: float


@dataclass
class Classification:
    settled: dict[str, PairRecord]
    to_llm: list[ScoredPair]


@dataclass
class RunStats:
    calls: int = 0
    wasted: Usage = field(default_factory=Usage)


@dataclass
class JudgeDeps:
    judge: PairJudge
    limiter: RateLimiter
    cache: VerdictCache
    config: LlmCompareConfig
    prompt_version: str
    stats: RunStats = field(default_factory=RunStats)
    sleep: Callable = asyncio.sleep
    jitter: Callable[[], float] = random.random


@dataclass(frozen=True)
class RunOutcome:
    records: list[PairRecord]
    calls: int
    wasted: Usage


def _record(pair: ImagePair, verdict: Verdict, **extra) -> PairRecord:
    return PairRecord(
        row_id=pair.row_id,
        key=pair.key,
        verdict=verdict,
        pdf_path=pair.pdf_path,
        web_path=pair.web_path,
        web_key=pair.web_key,
        **extra,
    )


def _skipped(pair: ImagePair, message: str) -> PairRecord:
    return _record(pair, Verdict.SKIPPED, message=message)


def _classify_one(
    pair: ImagePair, load: LoadBytes, threshold: float, scorer: Scorer
) -> PairRecord | ScoredPair:
    if pair.pdf_path is None:
        return _record(pair, Verdict.WEB_ONLY)
    if pair.skip_reason:
        return _skipped(pair, pair.skip_reason)
    return _score_files(pair, pair.pdf_path, load, threshold, scorer)


def _score_files(
    pair: ImagePair, pdf_path: str, load: LoadBytes, threshold: float, scorer: Scorer
) -> PairRecord | ScoredPair:
    pdf_bytes, web_bytes = load(pdf_path), load(pair.web_path or "")
    if pdf_bytes is None or web_bytes is None:
        return _skipped(pair, "image file missing")
    try:
        score = scorer(pair, pdf_bytes, web_bytes)
    except _UNREADABLE as error:
        return _skipped(pair, f"unreadable image: {error}")
    if route_for(score, threshold) is Route.MATCH_PHASH:
        return _record(pair, Verdict.MATCH_PHASH, score=score)
    return ScoredPair(pair, pdf_bytes, web_bytes, score)


def classify_pairs(
    pairs: list[ImagePair], load: LoadBytes, threshold: float, scorer: Scorer = score_pair
) -> Classification:
    result = Classification(settled={}, to_llm=[])
    for pair in pairs:
        outcome = _classify_one(pair, load, threshold, scorer)
        if isinstance(outcome, ScoredPair):
            result.to_llm.append(outcome)
        else:
            result.settled[pair.row_id] = outcome
    return result


def prepare_pairs(
    scored: list[ScoredPair], max_edge: int, token_scale: float
) -> list[PreparedPair]:
    prepared = []
    for item in scored:
        pdf, web = prepare_image(item.pdf_bytes, max_edge), prepare_image(item.web_bytes, max_edge)
        tokens = estimate_image_tokens(pdf.width, pdf.height, token_scale) + estimate_image_tokens(
            web.width, web.height, token_scale
        )
        prepared.append(PreparedPair(item.pair, item.score, pdf, web, tokens))
    return prepared


def _sizes(pair: PreparedPair) -> dict:
    return {
        "sent_pdf": (pair.pdf.width, pair.pdf.height),
        "sent_web": (pair.web.width, pair.web.height),
    }


def _judged_record(pair: PreparedPair, verdict: PairVerdict, usage: Usage, batch_id: int):
    return _record(
        pair.pair,
        verdict.verdict,
        score=pair.score,
        differences=verdict.differences,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=usage.cost,
        batch_id=batch_id,
        **_sizes(pair),
    )


def _error_record(pair: PreparedPair, batch_id: int, message: str) -> PairRecord:
    return _record(
        pair.pair,
        Verdict.ERROR,
        score=pair.score,
        message=message,
        batch_id=batch_id,
        **_sizes(pair),
    )


def _cached_record(pair: PreparedPair, entry: dict) -> PairRecord:
    return _record(
        pair.pair,
        Verdict(entry["verdict"]),
        score=pair.score,
        differences=tuple(entry["differences"]),
        input_tokens=entry["input_tokens"],
        output_tokens=entry["output_tokens"],
        cost=entry["cost"],
        cached=True,
        **_sizes(pair),
    )


def _entry_for(verdict: PairVerdict, usage: Usage) -> dict:
    return {
        "verdict": verdict.verdict.value,
        "differences": list(verdict.differences),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost": usage.cost,
    }


async def _call_judge(pairs: list[PreparedPair], deps: JudgeDeps):
    config = deps.config
    estimate = estimate_call_tokens(
        pairs, config.call_overhead_tokens, config.output_tokens_per_pair
    )

    async def once():
        reservation = await deps.limiter.acquire(estimate)
        deps.stats.calls += 1
        result = await deps.judge.judge(pairs)
        deps.limiter.release(reservation, result.usage.input_tokens + result.usage.output_tokens)
        return result

    return await call_with_retries(
        once,
        attempts=config.retry_attempts,
        base_delay=config.retry_base_delay,
        max_delay=config.retry_max_delay,
        sleep=deps.sleep,
        jitter=deps.jitter,
    )


def _store(pair, verdict, usage, batch_id, deps, records) -> None:
    records[pair.row_id] = _judged_record(pair, verdict, usage, batch_id)
    key = pair_cache_key(pair, deps.prompt_version, deps.config.model)
    deps.cache.put(key, _entry_for(verdict, usage))


def _store_answers(pairs, result, good, batch_id, deps, records) -> None:
    """Record the verdicts a call gave, splitting its usage across the pairs it answered."""
    answered = sorted(good)
    if not answered:
        deps.stats.wasted = add_usage(deps.stats.wasted, result.usage)
    shares = split_usage(result.usage, [pairs[n - 1].tokens for n in answered])
    for number, share in zip(answered, shares, strict=True):
        _store(pairs[number - 1], good[number], share, batch_id, deps, records)


async def _attempt(pairs, batch_id, deps, records) -> list[PreparedPair]:
    """One call for `pairs`; returns the pairs it gave no usable verdict for."""
    try:
        result = await _call_judge(pairs, deps)
    except JudgeError as error:
        for pair in pairs:
            records[pair.row_id] = _error_record(pair, batch_id, str(error))
        return []
    good, missing = validate_verdicts(len(pairs), result.verdicts)
    _store_answers(pairs, result, good, batch_id, deps, records)
    return [pairs[n - 1] for n in missing]


async def _retry_single(pair, batch_id, deps, records) -> None:
    for _ in range(deps.config.single_retries):
        if not await _attempt([pair], batch_id, deps, records):
            return
    records[pair.row_id] = _error_record(pair, batch_id, "no usable verdict after retries")


async def _process_batch(batch, batch_id, deps) -> dict[str, PairRecord]:
    records: dict[str, PairRecord] = {}
    for pair in await _attempt(batch, batch_id, deps, records):
        await _retry_single(pair, batch_id, deps, records)
    deps.cache.save()
    return records


def _split_cached(prepared, deps) -> tuple[dict[str, PairRecord], list[PreparedPair]]:
    records, misses = {}, []
    for pair in prepared:
        entry = deps.cache.get(pair_cache_key(pair, deps.prompt_version, deps.config.model))
        if entry is None:
            misses.append(pair)
        else:
            records[pair.row_id] = _cached_record(pair, entry)
    return records, misses


async def judge_pairs(prepared: list[PreparedPair], deps: JudgeDeps) -> dict[str, PairRecord]:
    records, misses = _split_cached(prepared, deps)
    config = deps.config
    batches = pack(
        misses, config.max_pairs_per_call, config.max_input_tokens, config.call_overhead_tokens
    )
    gate = asyncio.Semaphore(config.workers)

    async def run(batch_id, batch):
        async with gate:
            return await _process_batch(batch, batch_id, deps)

    parts = await asyncio.gather(*(run(n, b) for n, b in enumerate(batches, start=1)))
    for part in parts:
        records.update(part)
    return records


async def run_comparison(
    pairs: list[ImagePair],
    load: LoadBytes,
    deps: JudgeDeps,
    *,
    limit: int | None = None,
    scorer: Scorer = score_pair,
) -> RunOutcome:
    config = deps.config
    classified = classify_pairs(pairs, load, config.hash_match_percent, scorer)
    cut = len(classified.to_llm) if limit is None else limit
    prepared = prepare_pairs(classified.to_llm[:cut], config.max_edge, config.token_scale)
    records = {**classified.settled, **await judge_pairs(prepared, deps)}
    for item in classified.to_llm[cut:]:
        records[item.pair.row_id] = _skipped(item.pair, "not judged: --limit reached")
    ordered = [records[pair.row_id] for pair in pairs]
    return RunOutcome(ordered, deps.stats.calls, deps.stats.wasted)
