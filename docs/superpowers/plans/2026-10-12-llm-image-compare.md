# LLM visual image comparison (DSPy) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Judge, with a multimodal LLM through DSPy, the PDF/web image pairs the perceptual hash scores below 90%, and publish a report showing every image, its verdict, tokens and cost.

**Architecture:** A new `src/llm_compare/` package (domain / parsing / analysis / output, like `jira_backlog`) driven by `src/build_llm_comparison.py`. Pure steps (pair building, routing, preprocessing, batching, cost splitting) sit apart from I/O; the LLM is reached only through the `PairJudge` protocol, whose one real implementation is `DspyPairJudge`. A sliding-window limiter, retry/backoff and a content-hash cache wrap the async batch runner.

**Tech Stack:** Python 3.14, `dspy` (LiteLLM underneath, Gemini model from `.env`), Pillow, `asyncio`, pytest (async tests via `asyncio.run`, no new test plugin), stdlib `tomllib`.

**Spec:** `docs/superpowers/specs/2026-10-12-llm-image-compare-design.md`

## Global Constraints

- Routing: `score >= 90.0` -> `MATCH_PHASH` (inclusive); `score < 90.0` -> LLM; applies to equations too. The old 80%/70% thresholds and OCR/ink-correlation rescues are not used here.
- The tree's ✓/✗ and `output/comparison.json` are never modified; results go to `output/llm_image_compare.json`, `output/llm_image_report.html`, `output/llm_compare/`.
- Preprocessing order: flatten alpha onto white -> `autocrop_to_content` -> fit in a `max_edge` box, **scale down only** (Lanczos) -> lossless PNG. Colour is kept.
- Prompt text is the user's Gemini prompt verbatim plus one batch paragraph; temperature 0; `prompt_version` is a hash of that text and is part of the cache key.
- Verdict labels: `MATCH_PHASH`, `IDENTICAL`, `DIFFERENT`, `SKIPPED`, `WEB_ONLY`, `ERROR`.
- 429/5xx retry with exponential backoff + jitter honouring `Retry-After`; other 4xx do not retry. Missing/duplicate/malformed verdict ids are re-queued as single-pair calls, at most `single_retries` (2) times, then `ERROR`.
- Per-pair token shares sum exactly to the call's tokens; per-pair cost shares sum to the call's cost to float precision.
- `GEMINI_API_KEY` / `GEMINI_MODEL` come from the environment or `.env`; the key is never logged, written to output, or accepted from the TOML file.
- Repo rules (`CLAUDE.md`): TDD, functions <= 20 executable lines, cyclomatic complexity <= 6, nesting <= 2, guard clauses; Definition of done = `ruff check --fix . && ruff format .`, `radon cc -s -n B .`, `vulture .`, `pytest --cov=.`.
- Tests import from `src` via `tests/conftest.py`; async code is tested with `asyncio.run(...)`; no network in unit tests.
- All work stays on branch `worktree-llm-image-compare` (this worktree) and ends in a PR to `main`.

## Review Focus

1. Palette (`P`), greyscale (`L`), 1-bit and transparent images must preprocess without error and keep their content (Task 3).
2. Zero pairs routed to the LLM (everything >= 90%): no calls, valid report, valid dry-run (Tasks 10, 12).
3. Keys/messages containing `&`, `<`, quotes or parentheses (`B.A-9.8.8.6.(1).Fig4`) must render escaped and searchable (Task 11).
4. A model verdict with an unknown label, wrong case, or non-integer `pair_id` counts as malformed output -> single-pair retry, never a crash (Task 9).
5. Missing API key or model: exit non-zero with a clear message before any network call, dry-run still works without a key (Task 12).

---

## File Structure

```
requirements.txt                      modify: + dspy
.gitignore                            modify: + .env, llm_compare_config.toml
llm_compare_config.example.toml       create
src/llm_compare/__init__.py           create (+ domain/ parsing/ analysis/ output/ __init__.py)
src/llm_compare/config.py             settings + .env parsing + litellm model id
src/llm_compare/domain/models.py      Verdict, Route, ImagePair, PreparedImage, PreparedPair, Usage, Prices, PairVerdict, PairRecord
src/llm_compare/domain/errors.py      JudgeError, RateLimited, Transient, Permanent
src/llm_compare/domain/selection.py   route_for
src/llm_compare/domain/verdicts.py    validate_verdicts
src/llm_compare/domain/judge.py       JudgeResult, PairJudge protocol
src/llm_compare/domain/batching.py    estimate_image_tokens, estimate_call_tokens, pack
src/llm_compare/domain/costing.py     add_usage, split_usage, cost_of
src/llm_compare/parsing/preprocess.py prepare_image
src/llm_compare/parsing/pair_source.py build_pairs
src/llm_compare/analysis/hash_score.py   score_pair
src/llm_compare/analysis/pricing.py   resolve_prices
src/llm_compare/analysis/limiter.py   RateLimiter, call_with_retries
src/llm_compare/analysis/prompt.py    INSTRUCTIONS, PROMPT_VERSION
src/llm_compare/analysis/judge.py     DspyPairJudge, build_manifest, map_litellm_error
src/llm_compare/analysis/runner.py    classify_pairs, prepare_pairs, judge_pairs, run_comparison
src/llm_compare/analysis/estimate.py  plan_run, format_plan
src/llm_compare/analysis/calibration.py  variants, agreement, recommend
src/llm_compare/output/cache.py       VerdictCache, cache_key, pair_cache_key
src/llm_compare/output/report.py      summarise, build_report, render_html, write_report
src/build_llm_comparison.py           CLI
tests/llm_compare_support.py          shared test builders
tests/test_llm_compare_*.py           one file per module group
CLAUDE.md, Readme.md                  modify (Task 14)
```

---

### Task 1: Scaffold, dependency and configuration

**Files:**
- Modify: `requirements.txt`, `.gitignore`
- Create: `llm_compare_config.example.toml`, `src/llm_compare/__init__.py`, `src/llm_compare/{domain,parsing,analysis,output}/__init__.py`, `src/llm_compare/config.py`
- Test: `tests/test_llm_compare_config.py`

**Interfaces:**
- Produces: `ConfigError(ValueError)`; `LlmCompareConfig` (frozen dataclass, fields below); `parse_dotenv(text: str) -> dict[str, str]`; `load_config(toml_text: str, env: Mapping[str, str], dotenv: Mapping[str, str] | None = None) -> LlmCompareConfig`; `litellm_model(model: str) -> str`.

`LlmCompareConfig` fields and defaults: `api_key=""`, `model=""`, `hash_match_percent=90.0`, `max_edge=1024`, `max_pairs_per_call=6`, `max_input_tokens=60_000`, `call_overhead_tokens=700`, `output_tokens_per_pair=150`, `token_scale=1.0`, `rpm=30`, `tpm=250_000`, `workers=4`, `single_retries=2`, `retry_attempts=5`, `retry_base_delay=1.0`, `retry_max_delay=60.0`, `input_price_per_million=None`, `output_price_per_million=None`.

- [ ] **Step 1: Write the failing test** — `tests/test_llm_compare_config.py`

```python
import pytest

from llm_compare.config import ConfigError, litellm_model, load_config, parse_dotenv


def test_defaults_apply_when_nothing_is_configured():
    config = load_config("", {})
    assert config.hash_match_percent == 90.0
    assert config.max_edge == 1024
    assert config.api_key == ""
    assert config.input_price_per_million is None


def test_toml_values_override_defaults():
    config = load_config("rpm = 12\nhash_match_percent = 85\n", {})
    assert (config.rpm, config.hash_match_percent) == (12, 85.0)


def test_environment_beats_dotenv_beats_toml_for_the_model():
    toml = 'model = "from-toml"\n'
    assert load_config(toml, {"GEMINI_MODEL": "env"}, {"GEMINI_MODEL": "dot"}).model == "env"
    assert load_config(toml, {}, {"GEMINI_MODEL": "dot"}).model == "dot"
    assert load_config(toml, {}, {}).model == "from-toml"


def test_api_key_comes_from_environment_or_dotenv_only():
    assert load_config("", {}, {"GEMINI_API_KEY": "k"}).api_key == "k"
    assert load_config("", {"GEMINI_API_KEY": "e"}, {"GEMINI_API_KEY": "k"}).api_key == "e"
    with pytest.raises(ConfigError, match="api_key"):
        load_config('api_key = "secret"', {})


@pytest.mark.parametrize(
    "text",
    [
        "rpm = 0",
        "hash_match_percent = 0",
        "hash_match_percent = 101",
        "max_pairs_per_call = 0",
        "tpm = -5",
        "single_retries = -1",
        "input_price_per_million = -1",
        "token_scale = 0",
    ],
)
def test_out_of_range_values_are_rejected(text):
    with pytest.raises(ConfigError):
        load_config(text, {})


@pytest.mark.parametrize("text", ["nonsense = 1", 'rpm = "ten"', "rpm = true", "= broken"])
def test_unknown_keys_wrong_types_and_bad_toml_are_rejected(text):
    with pytest.raises(ConfigError):
        load_config(text, {})


def test_prices_are_optional_and_accept_integers():
    config = load_config("input_price_per_million = 1\noutput_price_per_million = 2.5", {})
    assert (config.input_price_per_million, config.output_price_per_million) == (1.0, 2.5)


def test_parse_dotenv_reads_plain_quoted_and_exported_lines():
    text = "# comment\n\nGEMINI_API_KEY=\"abc\"\nexport X=1\nBAD LINE\nQ='v'\nEMPTY=\n"
    assert parse_dotenv(text) == {"GEMINI_API_KEY": "abc", "X": "1", "Q": "v", "EMPTY": ""}


def test_litellm_model_adds_the_gemini_prefix_once():
    assert litellm_model("gemini-3.8-flash") == "gemini/gemini-3.8-flash"
    assert litellm_model("gemini/gemini-3.8-flash") == "gemini/gemini-3.8-flash"
    assert litellm_model("") == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_config.py -q`
Expected: FAIL / collection error `ModuleNotFoundError: No module named 'llm_compare'`

- [ ] **Step 3: Scaffold and implement**

Append `dspy>=3.1.0` to `requirements.txt`. Append to `.gitignore`:

```
.env
llm_compare_config.toml
```

Create empty `src/llm_compare/__init__.py` and the four subpackage `__init__.py` files. Create `llm_compare_config.example.toml`:

```toml
# Copy to llm_compare_config.toml (git-ignored) to override defaults. The API key and model
# come from GEMINI_API_KEY / GEMINI_MODEL in the environment or .env, never from this file.
hash_match_percent = 90      # a phash score at or above this is a match and is not sent to the LLM
max_edge = 1024              # longest side, px, images are scaled down to (set from --calibrate)
max_pairs_per_call = 6       # image pairs per LLM call
max_input_tokens = 60000     # input budget per call
rpm = 30                     # provider requests per minute
tpm = 250000                 # provider tokens per minute
workers = 4                  # concurrent calls
# input_price_per_million = 0.0   # USD per 1M tokens; only needed when LiteLLM has no price
# output_price_per_million = 0.0
```

Create `src/llm_compare/config.py`:

```python
"""Settings for the LLM image comparison, read from llm_compare_config.toml text plus
GEMINI_API_KEY / GEMINI_MODEL (environment first, then .env, then the file for the model)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields


class ConfigError(ValueError):
    """The settings are unusable; the message says which one and why."""


@dataclass(frozen=True)
class LlmCompareConfig:
    api_key: str = ""
    model: str = ""
    hash_match_percent: float = 90.0
    max_edge: int = 1024
    max_pairs_per_call: int = 6
    max_input_tokens: int = 60_000
    call_overhead_tokens: int = 700
    output_tokens_per_pair: int = 150
    token_scale: float = 1.0
    rpm: int = 30
    tpm: int = 250_000
    workers: int = 4
    single_retries: int = 2
    retry_attempts: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None


_INT_KEYS = (
    "max_edge",
    "max_pairs_per_call",
    "max_input_tokens",
    "call_overhead_tokens",
    "output_tokens_per_pair",
    "rpm",
    "tpm",
    "workers",
    "single_retries",
    "retry_attempts",
)
_FLOAT_KEYS = (
    "hash_match_percent",
    "token_scale",
    "retry_base_delay",
    "retry_max_delay",
    "input_price_per_million",
    "output_price_per_million",
)
_FILE_KEYS = {f.name for f in fields(LlmCompareConfig)} - {"api_key"}


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        values[name.strip()] = raw.strip().strip("\"'")
    return values


def litellm_model(model: str) -> str:
    return model if not model or "/" in model else f"gemini/{model}"


def _coerce(name: str, value):
    if name in _INT_KEYS and (isinstance(value, bool) or not isinstance(value, int)):
        raise ConfigError(f"{name} must be a whole number")
    if name in _FLOAT_KEYS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{name} must be a number")
        return float(value)
    if name == "model" and not isinstance(value, str):
        raise ConfigError("model must be text")
    return value


def _read_values(toml_text: str) -> dict:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"llm_compare_config.toml is not valid TOML: {error}") from error
    unknown = sorted(set(data) - _FILE_KEYS)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(unknown)}")
    return {name: _coerce(name, value) for name, value in data.items()}


def _check_ints(config: LlmCompareConfig) -> None:
    for name in _INT_KEYS:
        minimum = 0 if name == "single_retries" else 1
        if getattr(config, name) < minimum:
            raise ConfigError(f"{name} must be at least {minimum}")


def _check_floats(config: LlmCompareConfig) -> None:
    if not 0 < config.hash_match_percent <= 100:
        raise ConfigError("hash_match_percent must be above 0 and at most 100")
    if config.token_scale <= 0:
        raise ConfigError("token_scale must be above 0")
    for name in _FLOAT_KEYS:
        value = getattr(config, name)
        if value is not None and value < 0:
            raise ConfigError(f"{name} must not be negative")


def load_config(
    toml_text: str, env: Mapping[str, str], dotenv: Mapping[str, str] | None = None
) -> LlmCompareConfig:
    dotenv = dotenv or {}
    values = _read_values(toml_text)
    file_model = values.pop("model", "")
    model = env.get("GEMINI_MODEL") or dotenv.get("GEMINI_MODEL") or file_model
    api_key = env.get("GEMINI_API_KEY") or dotenv.get("GEMINI_API_KEY") or ""
    config = LlmCompareConfig(api_key=api_key, model=model, **values)
    _check_ints(config)
    _check_floats(config)
    return config
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_config.py -q`
Expected: PASS (all)

- [ ] **Step 5: Install the dependency and commit**

```bash
pip install "dspy>=3.1.0"
git add requirements.txt .gitignore llm_compare_config.example.toml src/llm_compare tests/test_llm_compare_config.py
git commit -m "feat(llm-compare): scaffold package, dspy dependency and settings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Domain models, routing, verdict validation, errors, test support

**Files:**
- Create: `src/llm_compare/domain/models.py`, `errors.py`, `selection.py`, `verdicts.py`, `judge.py`, `tests/llm_compare_support.py`
- Test: `tests/test_llm_compare_domain.py`

**Interfaces:**
- Produces (`models.py`): `Verdict`, `Route` (StrEnums), `LLM_VERDICTS`, `ImagePair(row_id, key, pdf_path, web_path, web_key=None, skip_reason="")`, `PreparedImage(png, width, height, source_width, source_height)`, `PreparedPair(pair, score, pdf, web, tokens)` with `.row_id`/`.key`, `Usage(input_tokens=0, output_tokens=0, cost=0.0)`, `Prices(input_per_million, output_per_million)`, `PairVerdict(pair_id, verdict, differences)`, `PairRecord(...)` (fields below).
- Produces: `route_for(score: float, threshold: float) -> Route`; `validate_verdicts(expected_count: int, verdicts: Sequence[PairVerdict]) -> tuple[dict[int, PairVerdict], list[int]]`; `JudgeError`, `RateLimited(message, retry_after=None)`, `Transient`, `Permanent`; `JudgeResult(verdicts, usage)`; `PairJudge` protocol with `async judge(pairs: Sequence[PreparedPair]) -> JudgeResult`.
- Test support: `png_bytes(size=(60, 50), box=(10, 10, 49, 39)) -> bytes` (40x30 of black content), `prepared_image(width=40, height=30)`, `prepared_pair(key="A.Fig1", tokens=100, score=50.0)`, `image_pair(key="A.Fig1", pdf="images/a.png", web="web_images/a.png", **extra)`.

`PairRecord` fields: `row_id, key, verdict, pdf_path, web_path, web_key=None, score=None, differences=(), message="", input_tokens=0, output_tokens=0, cost=None, batch_id=None, cached=False, sent_pdf=None, sent_web=None`.

- [ ] **Step 1: Write the failing test** — `tests/test_llm_compare_domain.py`

```python
import pytest

from llm_compare.domain.errors import JudgeError, Permanent, RateLimited, Transient
from llm_compare.domain.models import PairVerdict, Route, Verdict
from llm_compare.domain.selection import route_for
from llm_compare.domain.verdicts import validate_verdicts
from tests.llm_compare_support import image_pair, prepared_pair


@pytest.mark.parametrize(
    ("score", "expected"),
    [(89.9, Route.TO_LLM), (90.0, Route.MATCH_PHASH), (100.0, Route.MATCH_PHASH), (0.0, Route.TO_LLM)],
)
def test_route_for_is_inclusive_at_the_threshold(score, expected):
    assert route_for(score, 90.0) is expected


def test_route_for_uses_the_given_threshold():
    assert route_for(85.0, 80.0) is Route.MATCH_PHASH


def _verdict(number, verdict=Verdict.IDENTICAL):
    return PairVerdict(number, verdict, ())


def test_every_expected_id_answered_once_is_good():
    good, missing = validate_verdicts(2, [_verdict(2), _verdict(1)])
    assert sorted(good) == [1, 2] and missing == []


def test_a_missing_id_is_reported():
    good, missing = validate_verdicts(3, [_verdict(1), _verdict(3)])
    assert sorted(good) == [1, 3] and missing == [2]


def test_a_duplicated_id_is_treated_as_missing():
    good, missing = validate_verdicts(2, [_verdict(1), _verdict(1, Verdict.DIFFERENT), _verdict(2)])
    assert sorted(good) == [2] and missing == [1]


def test_ids_outside_the_batch_are_ignored():
    good, missing = validate_verdicts(2, [_verdict(0), _verdict(1), _verdict(9)])
    assert sorted(good) == [1] and missing == [2]


def test_no_verdicts_means_everything_is_missing():
    assert validate_verdicts(2, []) == ({}, [1, 2])
    assert validate_verdicts(0, []) == ({}, [])


def test_judge_errors_share_a_base_and_rate_limits_carry_retry_after():
    assert issubclass(RateLimited, JudgeError)
    assert issubclass(Transient, JudgeError) and issubclass(Permanent, JudgeError)
    assert RateLimited("slow down", retry_after=7.0).retry_after == 7.0
    assert RateLimited("slow down").retry_after is None


def test_support_builders_make_consistent_objects():
    pair = prepared_pair("B.Eq1", tokens=250)
    assert (pair.key, pair.row_id, pair.tokens) == ("B.Eq1", "pdf:images/a.png", 250)
    assert image_pair("X").web_path == "web_images/a.png"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_domain.py -q`
Expected: FAIL `ModuleNotFoundError: llm_compare.domain.models`

- [ ] **Step 3: Implement**

`src/llm_compare/domain/models.py`:

```python
"""Plain data the LLM image comparison passes between its steps."""

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    MATCH_PHASH = "MATCH_PHASH"
    IDENTICAL = "IDENTICAL"
    DIFFERENT = "DIFFERENT"
    SKIPPED = "SKIPPED"
    WEB_ONLY = "WEB_ONLY"
    ERROR = "ERROR"


class Route(StrEnum):
    MATCH_PHASH = "MATCH_PHASH"
    TO_LLM = "TO_LLM"


LLM_VERDICTS = (Verdict.IDENTICAL, Verdict.DIFFERENT)


@dataclass(frozen=True)
class ImagePair:
    """One report row's inputs. `pdf_path`/`web_path` are relative to the source directory;
    a missing side is None. `skip_reason` is set when the row cannot be compared."""

    row_id: str
    key: str
    pdf_path: str | None
    web_path: str | None
    web_key: str | None = None
    skip_reason: str = ""


@dataclass(frozen=True)
class PreparedImage:
    png: bytes
    width: int
    height: int
    source_width: int
    source_height: int


@dataclass(frozen=True)
class PreparedPair:
    pair: ImagePair
    score: float
    pdf: PreparedImage
    web: PreparedImage
    tokens: int

    @property
    def row_id(self) -> str:
        return self.pair.row_id

    @property
    def key(self) -> str:
        return self.pair.key


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = 0.0


@dataclass(frozen=True)
class Prices:
    input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class PairVerdict:
    pair_id: int
    verdict: Verdict
    differences: tuple[str, ...] = ()


@dataclass(frozen=True)
class PairRecord:
    row_id: str
    key: str
    verdict: Verdict
    pdf_path: str | None
    web_path: str | None
    web_key: str | None = None
    score: float | None = None
    differences: tuple[str, ...] = ()
    message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    batch_id: int | None = None
    cached: bool = False
    sent_pdf: tuple[int, int] | None = None
    sent_web: tuple[int, int] | None = None
```

`src/llm_compare/domain/errors.py`:

```python
"""Failures a PairJudge reports, split by whether retrying can help."""


class JudgeError(Exception):
    """Base of every judge failure."""


class RateLimited(JudgeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class Transient(JudgeError):
    """A 5xx, timeout or dropped connection: worth retrying."""


class Permanent(JudgeError):
    """A rejected request (bad input, bad key): retrying cannot help."""
```

`src/llm_compare/domain/selection.py`:

```python
"""Which route a scored pair takes."""

from llm_compare.domain.models import Route


def route_for(score: float, threshold: float) -> Route:
    return Route.MATCH_PHASH if score >= threshold else Route.TO_LLM
```

`src/llm_compare/domain/verdicts.py`:

```python
"""Checks that a batch response answers each numbered pair exactly once."""

from collections import Counter
from collections.abc import Sequence

from llm_compare.domain.models import PairVerdict


def validate_verdicts(
    expected_count: int, verdicts: Sequence[PairVerdict]
) -> tuple[dict[int, PairVerdict], list[int]]:
    """(usable verdicts by 1-based pair id, ids with no usable verdict). A duplicated id is
    ambiguous and so counts as missing; ids outside 1..expected_count are ignored."""
    counts = Counter(verdict.pair_id for verdict in verdicts)
    good = {
        verdict.pair_id: verdict
        for verdict in verdicts
        if 1 <= verdict.pair_id <= expected_count and counts[verdict.pair_id] == 1
    }
    missing = [number for number in range(1, expected_count + 1) if number not in good]
    return good, missing
```

`src/llm_compare/domain/judge.py`:

```python
"""The one role the runner needs from an LLM: judge a batch of prepared pairs."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from llm_compare.domain.models import PairVerdict, PreparedPair, Usage


@dataclass(frozen=True)
class JudgeResult:
    verdicts: list[PairVerdict]
    usage: Usage = field(default_factory=Usage)


class PairJudge(Protocol):
    async def judge(self, pairs: Sequence[PreparedPair]) -> JudgeResult: ...
```

`tests/llm_compare_support.py`:

```python
"""Builders shared by the llm_compare tests."""

import io

from PIL import Image, ImageDraw

from llm_compare.domain.models import ImagePair, PreparedImage, PreparedPair


def png_bytes(size=(60, 50), box=(10, 10, 49, 39)) -> bytes:
    """White canvas with a black rectangle (PIL boxes are inclusive: 40x30 of content) that has
    a margin to trim and content to keep."""
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle(box, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def prepared_image(width=40, height=30) -> PreparedImage:
    return PreparedImage(png_bytes(), width, height, 60, 50)


def image_pair(key="A.Fig1", pdf="images/a.png", web="web_images/a.png", **extra) -> ImagePair:
    return ImagePair(row_id=f"pdf:{pdf}", key=key, pdf_path=pdf, web_path=web, web_key=key, **extra)


def prepared_pair(key="A.Fig1", tokens=100, score=50.0, pdf="images/a.png") -> PreparedPair:
    pair = image_pair(key, pdf=pdf)
    return PreparedPair(pair, score, prepared_image(), prepared_image(), tokens)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_domain.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/domain tests/llm_compare_support.py tests/test_llm_compare_domain.py
git commit -m "feat(llm-compare): domain models, routing at 90%, verdict validation" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Image preprocessing

**Files:**
- Create: `src/llm_compare/parsing/preprocess.py`
- Test: `tests/test_llm_compare_preprocess.py`

**Interfaces:**
- Consumes: `image_compare.parsing.autocrop.autocrop_to_content(bytes) -> bytes` (PNG); `PreparedImage`.
- Produces: `prepare_image(data: bytes, max_edge: int) -> PreparedImage` — raises `OSError` (PIL `UnidentifiedImageError`) for non-image bytes.

- [ ] **Step 1: Write the failing test**

```python
import io

import pytest
from PIL import Image, ImageDraw

from llm_compare.parsing.preprocess import prepare_image
from tests.llm_compare_support import png_bytes


def _decode(prepared):
    return Image.open(io.BytesIO(prepared.png))


def test_blank_margins_are_trimmed_and_source_size_is_recorded():
    prepared = prepare_image(png_bytes(), max_edge=1024)
    assert (prepared.width, prepared.height) == (40, 30)
    assert (prepared.source_width, prepared.source_height) == (60, 50)


def test_a_large_image_is_scaled_down_keeping_its_aspect_ratio():
    big = Image.new("RGB", (2000, 1000), "white")
    ImageDraw.Draw(big).rectangle((100, 100, 1899, 899), fill="black")
    buffer = io.BytesIO()
    big.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (1024, 455)
    assert _decode(prepared).size == (1024, 455)


def test_a_small_image_is_never_enlarged():
    prepared = prepare_image(png_bytes(), max_edge=4096)
    assert (prepared.width, prepared.height) == (40, 30)


def test_a_very_thin_image_keeps_at_least_one_pixel():
    thin = Image.new("RGB", (3000, 4), "black")
    buffer = io.BytesIO()
    thin.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=300)
    assert prepared.width == 300 and prepared.height >= 1


def test_transparency_is_flattened_onto_white_before_trimming():
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).rectangle((30, 30, 69, 69), fill=(0, 0, 0, 255))
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (40, 40)


@pytest.mark.parametrize("mode", ["P", "L", "1", "RGBA"])
def test_palette_greyscale_bilevel_and_alpha_modes_do_not_crash(mode):
    image = Image.new("RGB", (80, 60), "white")
    ImageDraw.Draw(image).rectangle((20, 10, 60, 50), fill="black")
    buffer = io.BytesIO()
    image.convert(mode).save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert 0 < prepared.width <= 80 and 0 < prepared.height <= 60


def test_a_uniform_image_is_kept_whole():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(buffer, format="PNG")
    prepared = prepare_image(buffer.getvalue(), max_edge=1024)
    assert (prepared.width, prepared.height) == (30, 20)


def test_the_output_is_deterministic():
    assert prepare_image(png_bytes(), 512).png == prepare_image(png_bytes(), 512).png


def test_bytes_that_are_not_an_image_raise_oserror():
    with pytest.raises(OSError):
        prepare_image(b"not an image", max_edge=1024)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_preprocess.py -q`
Expected: FAIL `ModuleNotFoundError: llm_compare.parsing.preprocess`

- [ ] **Step 3: Implement** — `src/llm_compare/parsing/preprocess.py`

```python
"""Makes one image cheap to send without hiding any of its content: transparency flattened
onto white, blank margins trimmed, scaled down (never up) to fit max_edge, lossless PNG.
Gemini bills image tokens by pixel dimensions, not file bytes, so lossy encoding would add
risk and save nothing."""

import io

from PIL import Image

from image_compare.parsing.autocrop import autocrop_to_content
from llm_compare.domain.models import PreparedImage


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _flatten_to_png(image: Image.Image) -> bytes:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    canvas.alpha_composite(rgba)
    return _encode(canvas.convert("RGB"))


def _fit_within(image: Image.Image, max_edge: int) -> Image.Image:
    longest = max(image.size)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def prepare_image(data: bytes, max_edge: int) -> PreparedImage:
    source = Image.open(io.BytesIO(data))
    source_width, source_height = source.size
    trimmed = Image.open(io.BytesIO(autocrop_to_content(_flatten_to_png(source))))
    fitted = _fit_within(trimmed, max_edge)
    return PreparedImage(
        png=_encode(fitted),
        width=fitted.width,
        height=fitted.height,
        source_width=source_width,
        source_height=source_height,
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_preprocess.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/parsing/preprocess.py tests/test_llm_compare_preprocess.py
git commit -m "feat(llm-compare): normalise images before sending (flatten, trim, scale down)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Pair source (every PDF image and web-only image becomes a row)

**Files:**
- Create: `src/llm_compare/parsing/pair_source.py`
- Test: `tests/test_llm_compare_pair_source.py`

**Interfaces:**
- Consumes: `bcbc_pdf.json` `images[]` entries (`image_path`, `unified_number` optional), `bcbc_web.json` `images[]` entries (`id`, `local_path`, `unified_number` optional), `comparison.json` `counterparts` (`{pdf_key: web_key | None}`).
- Produces: `build_pairs(pdf_images: list[dict], web_images: list[dict], counterparts: dict[str, str | None]) -> list[ImagePair]`. One pair per PDF image (row id `pdf:<image_path>`), then one per web image no PDF image pairs with (row id `web:<local_path or id>`, `pdf_path=None`).

- [ ] **Step 1: Write the failing test**

```python
from llm_compare.parsing.pair_source import build_pairs


def _pdf(number, path):
    image = {"image_path": path}
    if number:
        image["unified_number"] = number
    return image


def _web(number, path, image_id=None):
    return {"unified_number": number, "local_path": path, "id": image_id or number}


def test_a_same_numbered_pair_is_comparable():
    (pair,) = build_pairs([_pdf("A.Fig1", "images/1.png")], [_web("A.Fig1", "web_images/1.jpg")], {})
    assert (pair.key, pair.pdf_path, pair.web_path, pair.web_key) == (
        "A.Fig1",
        "images/1.png",
        "web_images/1.jpg",
        "A.Fig1",
    )
    assert pair.skip_reason == "" and pair.row_id == "pdf:images/1.png"


def test_a_counterpart_overrides_the_same_number():
    pdf = [_pdf("A.Fig1", "images/1.png")]
    web = [_web("A.Fig1", "web_images/a.jpg"), _web("A.Eq2", "web_images/b.jpg")]
    pairs = build_pairs(pdf, web, {"A.Fig1": "A.Eq2"})
    assert pairs[0].web_key == "A.Eq2" and pairs[0].web_path == "web_images/b.jpg"
    assert [p.key for p in pairs] == ["A.Fig1", "A.Fig1"]  # the unused A.Fig1 web image is web-only
    assert pairs[1].pdf_path is None and pairs[1].web_path == "web_images/a.jpg"


def test_a_null_counterpart_or_missing_web_image_is_skipped():
    pdf = [_pdf("A.Fig1", "images/1.png"), _pdf("A.Fig2", "images/2.png")]
    pairs = build_pairs(pdf, [], {"A.Fig1": None})
    assert [p.skip_reason for p in pairs] == ["no web counterpart", "no web counterpart"]
    assert all(p.web_path is None for p in pairs)


def test_a_pdf_image_without_a_number_is_skipped_and_keyed_by_its_path():
    (pair,) = build_pairs([_pdf(None, "images/9.png")], [], {})
    assert pair.key == "images/9.png" and pair.skip_reason == "no unified number"


def test_a_web_image_without_a_local_file_is_skipped():
    web = [{"unified_number": "A.Fig1", "id": "x", "local_path": ""}]
    (pair,) = build_pairs([_pdf("A.Fig1", "images/1.png")], web, {})
    assert pair.skip_reason == "web image has no local file" and pair.web_path is None


def test_web_images_no_pdf_image_pairs_with_become_web_only_rows():
    web = [_web("A.Fig1", "web_images/1.jpg"), _web("Z.Fig9", "web_images/z.jpg")]
    pairs = build_pairs([_pdf("A.Fig1", "images/1.png")], web, {})
    assert len(pairs) == 2
    only = pairs[1]
    assert (only.key, only.pdf_path, only.web_path) == ("Z.Fig9", None, "web_images/z.jpg")
    assert only.row_id == "web:web_images/z.jpg"


def test_a_web_image_without_a_number_is_keyed_by_its_id():
    web = [{"id": "nbc.x.figure1", "local_path": "web_images/x.jpg"}]
    (pair,) = build_pairs([], web, {})
    assert pair.key == "nbc.x.figure1"


def test_two_pdf_images_can_share_one_web_image_and_it_is_not_web_only():
    pdf = [_pdf("A.Fig1", "images/1.png"), _pdf("A.Fig2", "images/2.png")]
    web = [_web("A.Eq1", "web_images/e.jpg")]
    pairs = build_pairs(pdf, web, {"A.Fig1": "A.Eq1", "A.Fig2": "A.Eq1"})
    assert len(pairs) == 2 and all(p.web_key == "A.Eq1" for p in pairs)


def test_row_ids_are_unique_even_when_keys_repeat():
    pdf = [_pdf("A.Fig1", "images/1.png")]
    web = [_web("A.Fig1", "web_images/1.jpg", "w1"), _web("Q.Fig1", "web_images/q.jpg")]
    ids = [p.row_id for p in build_pairs(pdf, web, {"A.Fig1": None})]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_pair_source.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `src/llm_compare/parsing/pair_source.py`

```python
"""Turns the PDF and web image indexes plus comparison.json's `counterparts` into one
ImagePair per report row: every PDF image, then every web image no PDF image pairs with."""

from llm_compare.domain.models import ImagePair


def _web_key(image: dict) -> str:
    return image.get("unified_number") or image["id"]


def _skipped(row_id: str, key: str, path: str, reason: str) -> ImagePair:
    return ImagePair(row_id=row_id, key=key, pdf_path=path, web_path=None, skip_reason=reason)


def _pdf_pair(image: dict, web_by_key: dict, counterparts: dict, used: set[str]) -> ImagePair:
    path = image["image_path"]
    row_id = f"pdf:{path}"
    number = image.get("unified_number")
    if not number:
        return _skipped(row_id, path, path, "no unified number")
    web_key = counterparts[number] if number in counterparts else number
    web = web_by_key.get(web_key) if web_key else None
    if web is None:
        return _skipped(row_id, number, path, "no web counterpart")
    used.add(web_key)
    web_path = web.get("local_path") or None
    reason = "" if web_path else "web image has no local file"
    return ImagePair(
        row_id=row_id,
        key=number,
        pdf_path=path,
        web_path=web_path,
        web_key=web_key,
        skip_reason=reason,
    )


def _web_only_pair(image: dict) -> ImagePair:
    web_path = image.get("local_path") or None
    return ImagePair(
        row_id=f"web:{web_path or image['id']}",
        key=_web_key(image),
        pdf_path=None,
        web_path=web_path,
        web_key=_web_key(image),
    )


def build_pairs(
    pdf_images: list[dict], web_images: list[dict], counterparts: dict[str, str | None]
) -> list[ImagePair]:
    web_by_key = {_web_key(image): image for image in web_images}
    used: set[str] = set()
    pairs = [_pdf_pair(image, web_by_key, counterparts, used) for image in pdf_images]
    pairs += [_web_only_pair(image) for image in web_images if _web_key(image) not in used]
    return pairs
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_pair_source.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/parsing/pair_source.py tests/test_llm_compare_pair_source.py
git commit -m "feat(llm-compare): build a report row for every PDF and web-only image" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Token estimates and batch packing

**Files:**
- Create: `src/llm_compare/domain/batching.py`
- Test: `tests/test_llm_compare_batching.py`

**Interfaces:**
- Consumes: `PreparedPair.tokens`.
- Produces: `estimate_image_tokens(width: int, height: int, scale: float = 1.0) -> int` (Gemini tiling rule: both sides <= 384 -> 258; else crop unit `clamp(floor(min(w,h)/1.5), 256, 768)`, tiles `ceil(w/unit)*ceil(h/unit)`, 258 per tile; result `ceil(tokens*scale)`); `estimate_call_tokens(batch: Sequence[PreparedPair], overhead: int, output_per_pair: int) -> int`; `pack(pairs: Sequence[PreparedPair], max_pairs: int, max_input_tokens: int, overhead: int = 0) -> list[list[PreparedPair]]`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from llm_compare.domain.batching import estimate_call_tokens, estimate_image_tokens, pack
from tests.llm_compare_support import prepared_pair


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(300, 200, 258), (384, 384, 258), (1000, 1000, 1032), (1024, 300, 2064), (385, 10, 516)],
)
def test_image_tokens_follow_the_gemini_tiling_rule(width, height, expected):
    assert estimate_image_tokens(width, height) == expected


def test_the_calibration_scale_adjusts_the_estimate():
    assert estimate_image_tokens(1000, 1000, scale=0.5) == 516
    assert estimate_image_tokens(300, 200, scale=1.5) == 387


def _pairs(count, tokens=1000):
    return [prepared_pair(f"K{n}", tokens=tokens) for n in range(count)]


def test_pack_respects_the_pair_limit_and_keeps_order():
    batches = pack(_pairs(7), max_pairs=3, max_input_tokens=10**9)
    assert [[p.key for p in b] for b in batches] == [["K0", "K1", "K2"], ["K3", "K4", "K5"], ["K6"]]


def test_pack_respects_the_token_budget_including_overhead():
    batches = pack(_pairs(5), max_pairs=10, max_input_tokens=2500, overhead=600)
    assert [len(b) for b in batches] == [1, 1, 1, 1, 1]
    batches = pack(_pairs(5), max_pairs=10, max_input_tokens=3000, overhead=600)
    assert [len(b) for b in batches] == [2, 2, 1]


def test_one_oversize_pair_still_gets_its_own_call():
    batches = pack([prepared_pair("big", tokens=10**6), *_pairs(2)], 5, max_input_tokens=5000)
    assert [[p.key for p in b] for b in batches] == [["big"], ["K0", "K1"]]


def test_no_pairs_means_no_batches():
    assert pack([], max_pairs=3, max_input_tokens=1000) == []


def test_call_estimate_adds_overhead_and_output_allowance():
    batch = _pairs(3, tokens=1000)
    assert estimate_call_tokens(batch, overhead=700, output_per_pair=150) == 3000 + 700 + 450
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_batching.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `src/llm_compare/domain/batching.py`

```python
"""Estimates what a call costs in tokens and packs pairs into as few calls as the budgets
allow. Pure: the estimates are corrected against real usage by --calibrate (token_scale)."""

from collections.abc import Sequence
from math import ceil

from llm_compare.domain.models import PreparedPair

SMALL_EDGE = 384
TOKENS_PER_TILE = 258
MIN_UNIT = 256
MAX_UNIT = 768


def estimate_image_tokens(width: int, height: int, scale: float = 1.0) -> int:
    if max(width, height) <= SMALL_EDGE:
        return ceil(TOKENS_PER_TILE * scale)
    unit = min(MAX_UNIT, max(MIN_UNIT, int(min(width, height) / 1.5)))
    tiles = ceil(width / unit) * ceil(height / unit)
    return ceil(TOKENS_PER_TILE * tiles * scale)


def estimate_call_tokens(
    batch: Sequence[PreparedPair], overhead: int, output_per_pair: int
) -> int:
    return overhead + sum(pair.tokens for pair in batch) + output_per_pair * len(batch)


def pack(
    pairs: Sequence[PreparedPair], max_pairs: int, max_input_tokens: int, overhead: int = 0
) -> list[list[PreparedPair]]:
    batches: list[list[PreparedPair]] = []
    current: list[PreparedPair] = []
    used = overhead
    for pair in pairs:
        full = len(current) >= max_pairs or (current and used + pair.tokens > max_input_tokens)
        if full:
            batches.append(current)
            current, used = [], overhead
        current.append(pair)
        used += pair.tokens
    if current:
        batches.append(current)
    return batches
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_batching.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/domain/batching.py tests/test_llm_compare_batching.py
git commit -m "feat(llm-compare): estimate call tokens and pack pairs into batches" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Cost splitting and prices

**Files:**
- Create: `src/llm_compare/domain/costing.py`, `src/llm_compare/analysis/pricing.py`
- Test: `tests/test_llm_compare_costing.py`

**Interfaces:**
- Consumes: `Usage`, `Prices`, `LlmCompareConfig`, `litellm_model`.
- Produces: `add_usage(a: Usage, b: Usage) -> Usage` (cost None if either is None); `split_usage(usage: Usage, weights: Sequence[int]) -> list[Usage]` (integer tokens by largest remainder so they sum exactly; cost proportional; zero total weight -> equal split; empty weights -> `[]`); `cost_of(input_tokens: int, output_tokens: int, prices: Prices | None) -> float | None`; `resolve_prices(config: LlmCompareConfig, lookup: Mapping | None = None) -> Prices | None` (config prices if both set, else LiteLLM's `model_cost` table via `lookup` or `litellm.model_cost`, else None).

- [ ] **Step 1: Write the failing test**

```python
import sys

import pytest

from llm_compare.analysis.pricing import resolve_prices
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.costing import add_usage, cost_of, split_usage
from llm_compare.domain.models import Prices, Usage


def test_tokens_split_exactly_and_cost_proportionally():
    shares = split_usage(Usage(1000, 100, 0.10), [1, 1, 2])
    assert [s.input_tokens for s in shares] == [250, 250, 500]
    assert sum(s.input_tokens for s in shares) == 1000
    assert sum(s.output_tokens for s in shares) == 100
    assert sum(s.cost for s in shares) == pytest.approx(0.10)


def test_remainders_go_to_the_largest_fractions_and_still_sum_exactly():
    shares = split_usage(Usage(10, 7, 0.0), [1, 1, 1])
    assert sum(s.input_tokens for s in shares) == 10
    assert sorted(s.input_tokens for s in shares) == [3, 3, 4]
    assert sum(s.output_tokens for s in shares) == 7


def test_zero_weights_split_equally_and_empty_weights_give_nothing():
    assert [s.input_tokens for s in split_usage(Usage(9, 0, 0.9), [0, 0, 0])] == [3, 3, 3]
    assert split_usage(Usage(9, 0, 0.9), []) == []


def test_a_single_pair_takes_the_whole_call():
    assert split_usage(Usage(123, 45, 0.5), [999]) == [Usage(123, 45, 0.5)]


def test_unknown_cost_stays_unknown():
    assert [s.cost for s in split_usage(Usage(10, 10, None), [1, 1])] == [None, None]


def test_add_usage_sums_tokens_and_cost():
    assert add_usage(Usage(1, 2, 0.5), Usage(3, 4, 0.25)) == Usage(4, 6, 0.75)
    assert add_usage(Usage(1, 2, None), Usage(3, 4, 0.25)).cost is None


def test_cost_of_uses_per_million_prices():
    assert cost_of(1_000_000, 500_000, Prices(0.30, 2.50)) == pytest.approx(0.30 + 1.25)
    assert cost_of(10, 10, None) is None


def test_config_prices_win_and_both_must_be_set():
    both = LlmCompareConfig(model="m", input_price_per_million=1.0, output_price_per_million=2.0)
    assert resolve_prices(both, lookup={}) == Prices(1.0, 2.0)
    one = LlmCompareConfig(model="m", input_price_per_million=1.0)
    assert resolve_prices(one, lookup={}) is None


def test_litellm_prices_are_used_when_the_config_has_none():
    table = {"gemini/m": {"input_cost_per_token": 3e-7, "output_cost_per_token": 2.5e-6}}
    prices = resolve_prices(LlmCompareConfig(model="m"), lookup=table)
    assert prices.input_per_million == pytest.approx(0.3)
    assert prices.output_per_million == pytest.approx(2.5)


def test_the_unprefixed_model_name_is_also_tried_and_missing_entries_give_none():
    table = {"m": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}}
    assert resolve_prices(LlmCompareConfig(model="m"), lookup=table) is not None
    assert resolve_prices(LlmCompareConfig(model="other"), lookup=table) is None
    partial = {"gemini/m": {"input_cost_per_token": 1e-6}}
    assert resolve_prices(LlmCompareConfig(model="m"), lookup=partial) is None


def test_without_litellm_installed_the_cost_is_simply_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)  # makes `import litellm` raise ImportError
    assert resolve_prices(LlmCompareConfig(model="m")) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_costing.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/llm_compare/domain/costing.py`:

```python
"""Splits a call's tokens and cost across its pairs, and prices tokens. Pure."""

from collections.abc import Sequence

from llm_compare.domain.models import Prices, Usage


def add_usage(first: Usage, second: Usage) -> Usage:
    both_known = first.cost is not None and second.cost is not None
    return Usage(
        first.input_tokens + second.input_tokens,
        first.output_tokens + second.output_tokens,
        first.cost + second.cost if both_known else None,
    )


def _apportion(amount: int, weights: Sequence[int]) -> list[int]:
    """Largest-remainder split: integer shares that sum exactly to `amount`."""
    total = sum(weights)
    shares = [amount * weight // total for weight in weights]
    by_fraction = sorted(range(len(weights)), key=lambda i: (-(amount * weights[i] % total), i))
    for index in by_fraction[: amount - sum(shares)]:
        shares[index] += 1
    return shares


def split_usage(usage: Usage, weights: Sequence[int]) -> list[Usage]:
    if not weights:
        return []
    weights = list(weights) if sum(weights) > 0 else [1] * len(weights)
    total = sum(weights)
    inputs = _apportion(usage.input_tokens, weights)
    outputs = _apportion(usage.output_tokens, weights)
    costs = [None if usage.cost is None else usage.cost * w / total for w in weights]
    return [Usage(i, o, c) for i, o, c in zip(inputs, outputs, costs, strict=True)]


def cost_of(input_tokens: int, output_tokens: int, prices: Prices | None) -> float | None:
    if prices is None:
        return None
    return (
        input_tokens * prices.input_per_million + output_tokens * prices.output_per_million
    ) / 1_000_000
```

`src/llm_compare/analysis/pricing.py`:

```python
"""Per-million-token prices: the config's when both are set, else LiteLLM's table."""

from collections.abc import Mapping

from llm_compare.config import LlmCompareConfig, litellm_model
from llm_compare.domain.models import Prices


def _litellm_table() -> Mapping:
    try:
        import litellm
    except ImportError:
        return {}
    return litellm.model_cost


def _from_table(model: str, table: Mapping) -> Prices | None:
    entry = table.get(model) or table.get(model.split("/", 1)[-1])
    if not entry:
        return None
    per_input, per_output = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
    if per_input is None or per_output is None:
        return None
    return Prices(per_input * 1_000_000, per_output * 1_000_000)


def resolve_prices(config: LlmCompareConfig, lookup: Mapping | None = None) -> Prices | None:
    if config.input_price_per_million is not None and config.output_price_per_million is not None:
        return Prices(config.input_price_per_million, config.output_price_per_million)
    table = lookup if lookup is not None else _litellm_table()
    return _from_table(litellm_model(config.model), table)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_costing.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/domain/costing.py src/llm_compare/analysis/pricing.py tests/test_llm_compare_costing.py
git commit -m "feat(llm-compare): split call usage across pairs and resolve prices" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Rate limiter and retry with backoff

**Files:**
- Create: `src/llm_compare/analysis/limiter.py`
- Test: `tests/test_llm_compare_limiter.py`

**Interfaces:**
- Consumes: `RateLimited`, `Transient` from `domain.errors`.
- Produces: `RateLimiter(rpm: int, tpm: int, clock=time.monotonic, sleep=asyncio.sleep, window: float = 60.0)` with `async acquire(tokens: int) -> list` (a reservation) and `release(reservation, actual_tokens: int) -> None`; `async call_with_retries(call, *, attempts: int, base_delay: float, max_delay: float, sleep=asyncio.sleep, jitter=random.random)` — `call` is a zero-argument async callable; retries `RateLimited`/`Transient`, lets every other exception (including `Permanent`) through at once.

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from llm_compare.analysis.limiter import RateLimiter, call_with_retries
from llm_compare.domain.errors import Permanent, RateLimited, Transient


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(fake, rpm=100, tpm=10_000):
    return RateLimiter(rpm, tpm, clock=fake.clock, sleep=fake.sleep)


def test_requests_over_the_per_minute_budget_wait_for_the_window():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=2)

    async def go():
        for _ in range(3):
            await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_tokens_over_the_per_minute_budget_wait_too():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        await limiter.acquire(60)
        await limiter.acquire(60)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_the_window_slides_so_only_the_remaining_time_is_waited():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=2)

    async def go():
        await limiter.acquire(1)
        fake.now = 30.0
        await limiter.acquire(1)
        await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [30.0]


def test_one_call_bigger_than_the_whole_token_budget_does_not_deadlock():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        await limiter.acquire(500)
        await limiter.acquire(1)

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def test_releasing_with_actual_usage_frees_unused_budget():
    fake = FakeTime()
    limiter = _limiter(fake, tpm=100)

    async def go():
        reservation = await limiter.acquire(90)
        limiter.release(reservation, 10)
        await limiter.acquire(80)

    asyncio.run(go())
    assert fake.sleeps == []


def test_concurrent_acquirers_share_the_budget():
    fake = FakeTime()
    limiter = _limiter(fake, rpm=1)

    async def go():
        await asyncio.gather(limiter.acquire(1), limiter.acquire(1))

    asyncio.run(go())
    assert fake.sleeps == [60.0]


def _flaky(errors, result="ok"):
    pending = list(errors)

    async def call():
        if pending:
            raise pending.pop(0)
        return result

    return call


def _retry(call, fake=None, attempts=5, jitter=lambda: 1.0):
    fake = fake or FakeTime()
    outcome = asyncio.run(
        call_with_retries(call, attempts=attempts, base_delay=1.0, max_delay=3.0, sleep=fake.sleep, jitter=jitter)
    )
    return outcome, fake


def test_transient_errors_back_off_exponentially_up_to_the_cap():
    outcome, fake = _retry(_flaky([Transient("503")] * 3))
    assert outcome == "ok" and fake.sleeps == [1.0, 2.0, 3.0]


def test_jitter_scales_the_delay_between_half_and_full():
    _, fake = _retry(_flaky([Transient("503")]), jitter=lambda: 0.0)
    assert fake.sleeps == [0.5]


def test_retry_after_is_honoured_over_the_backoff():
    _, fake = _retry(_flaky([RateLimited("429", retry_after=7.0)]))
    assert fake.sleeps == [7.0]


def test_permanent_errors_are_not_retried():
    fake = FakeTime()
    with pytest.raises(Permanent):
        _retry(_flaky([Permanent("400")]), fake)
    assert fake.sleeps == []


def test_the_last_error_surfaces_when_attempts_run_out():
    fake = FakeTime()
    with pytest.raises(Transient):
        _retry(_flaky([Transient("503")] * 5), fake, attempts=3)
    assert len(fake.sleeps) == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_limiter.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `src/llm_compare/analysis/limiter.py`

```python
"""Keeps async calls inside the provider's requests- and tokens-per-minute limits, and
retries the failures that retrying can cure."""

import asyncio
import random
import time
from collections import deque

from llm_compare.domain.errors import RateLimited, Transient


class RateLimiter:
    """Sliding-window limiter. `acquire` reserves an estimate and waits if either budget
    would be exceeded; `release` corrects the reservation with the real usage. One request
    larger than the whole token budget is let through when nothing else is in the window."""

    def __init__(self, rpm, tpm, clock=time.monotonic, sleep=asyncio.sleep, window=60.0):
        self._rpm, self._tpm, self._window = rpm, tpm, window
        self._clock, self._sleep = clock, sleep
        self._entries: deque[list] = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self._entries and now - self._entries[0][0] >= self._window:
            self._entries.popleft()

    def _wait_needed(self, now: float, tokens: int) -> float:
        if not self._entries:
            return 0.0
        over_requests = len(self._entries) >= self._rpm
        over_tokens = sum(entry[1] for entry in self._entries) + tokens > self._tpm
        if not (over_requests or over_tokens):
            return 0.0
        return self._entries[0][0] + self._window - now

    async def acquire(self, tokens: int) -> list:
        async with self._lock:
            while True:
                now = self._clock()
                self._prune(now)
                wait = self._wait_needed(now, tokens)
                if wait <= 0:
                    entry = [now, tokens]
                    self._entries.append(entry)
                    return entry
                await self._sleep(wait)

    def release(self, reservation: list, actual_tokens: int) -> None:
        reservation[1] = actual_tokens


def _delay(error, attempt, base_delay, max_delay, jitter) -> float:
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        return retry_after
    return min(max_delay, base_delay * 2**attempt) * (0.5 + 0.5 * jitter())


async def call_with_retries(
    call, *, attempts, base_delay, max_delay, sleep=asyncio.sleep, jitter=random.random
):
    for attempt in range(attempts):
        try:
            return await call()
        except (RateLimited, Transient) as error:
            if attempt == attempts - 1:
                raise
            await sleep(_delay(error, attempt, base_delay, max_delay, jitter))
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_limiter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/analysis/limiter.py tests/test_llm_compare_limiter.py
git commit -m "feat(llm-compare): rate limiter and retry with backoff" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Verdict cache

**Files:**
- Create: `src/llm_compare/output/cache.py`
- Test: `tests/test_llm_compare_cache.py`

**Interfaces:**
- Consumes: `PreparedPair`.
- Produces: `cache_key(pdf_png: bytes, web_png: bytes, prompt_version: str, model: str) -> str`; `pair_cache_key(pair: PreparedPair, prompt_version: str, model: str) -> str`; `VerdictCache(path: Path | None = None)` with `get(key) -> dict | None`, `put(key, entry: dict)`, `save()` (no-op when `path` is None; atomic write; creates parent directories); a missing or corrupt file loads as empty.

- [ ] **Step 1: Write the failing test**

```python
import json

from llm_compare.output.cache import VerdictCache, cache_key, pair_cache_key
from tests.llm_compare_support import prepared_pair


def test_the_key_is_stable_and_changes_with_every_component():
    base = cache_key(b"a", b"b", "v1", "m")
    assert base == cache_key(b"a", b"b", "v1", "m")
    assert len({base, cache_key(b"x", b"b", "v1", "m"), cache_key(b"a", b"x", "v1", "m"),
                cache_key(b"a", b"b", "v2", "m"), cache_key(b"a", b"b", "v1", "n")}) == 5


def test_parts_cannot_be_shifted_between_fields_to_collide():
    assert cache_key(b"ab", b"c", "v", "m") != cache_key(b"a", b"bc", "v", "m")


def test_pair_cache_key_uses_the_prepared_png_bytes():
    pair = prepared_pair()
    assert pair_cache_key(pair, "v1", "m") == cache_key(pair.pdf.png, pair.web.png, "v1", "m")


def test_entries_round_trip_through_a_file(tmp_path):
    path = tmp_path / "nested" / "cache.json"
    cache = VerdictCache(path)
    cache.put("k", {"verdict": "IDENTICAL", "differences": []})
    cache.save()
    assert VerdictCache(path).get("k") == {"verdict": "IDENTICAL", "differences": []}
    assert [p.name for p in path.parent.iterdir()] == ["cache.json"]


def test_a_missing_key_gives_none_and_a_memory_cache_never_writes(tmp_path):
    cache = VerdictCache()
    assert cache.get("nope") is None
    cache.put("k", {"x": 1})
    cache.save()
    assert cache.get("k") == {"x": 1}
    assert list(tmp_path.iterdir()) == []


def test_a_corrupt_file_loads_as_empty_and_is_overwritten_on_save(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    cache = VerdictCache(path)
    assert cache.get("k") is None
    cache.put("k", {"x": 1})
    cache.save()
    assert json.loads(path.read_text()) == {"k": {"x": 1}}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_cache.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `src/llm_compare/output/cache.py`

```python
"""Verdicts remembered by content, so a re-run or an interrupted run re-spends nothing."""

import hashlib
import json
from pathlib import Path

from llm_compare.domain.models import PreparedPair


def cache_key(pdf_png: bytes, web_png: bytes, prompt_version: str, model: str) -> str:
    digest = hashlib.sha256()
    for part in (pdf_png, web_png, prompt_version.encode(), model.encode()):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def pair_cache_key(pair: PreparedPair, prompt_version: str, model: str) -> str:
    return cache_key(pair.pdf.png, pair.web.png, prompt_version, model)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class VerdictCache:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._entries: dict[str, dict] = _read(path) if path is not None else {}

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, entry: dict) -> None:
        self._entries[key] = entry

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._entries))
        temporary.replace(self._path)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_cache.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/output/cache.py tests/test_llm_compare_cache.py
git commit -m "feat(llm-compare): content-keyed verdict cache" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The DSPy judge

**Files:**
- Create: `src/llm_compare/analysis/prompt.py`, `src/llm_compare/analysis/judge.py`
- Test: `tests/test_llm_compare_judge.py`

**Interfaces:**
- Consumes: `PairJudge`/`JudgeResult`, `PreparedPair`, `Usage`, `Prices`, `cost_of`, `LlmCompareConfig`, `litellm_model`, errors.
- Produces: `INSTRUCTIONS: str`, `PROMPT_VERSION: str` (first 12 hex of the SHA-256 of `INSTRUCTIONS`); `build_manifest(count: int) -> str`; `map_litellm_error(error: Exception) -> JudgeError`; `DspyPairJudge(config, prices, *, predictor=None, lm=None, instructions=INSTRUCTIONS)` implementing `PairJudge`. A parse failure of the model output (bad label, bad id, not JSON) returns `JudgeResult([], Usage())` so the runner re-queues the pairs; any other failure raises a `JudgeError`. Output tokens = `max(total - prompt, completion)` so hidden "thinking" tokens are counted.

- [ ] **Step 1: Verify the DSPy API this task relies on**

Run:

```bash
python3 - <<'EOF'
import dspy
print("version", dspy.__version__)
print("acall", hasattr(dspy.Predict, "acall"))
print("with_instructions", hasattr(dspy.Signature, "with_instructions"))
print("get_lm_usage", hasattr(dspy.Prediction, "get_lm_usage"))
image = dspy.Image(url="data:image/png;base64,iVBORw0KGgo=")
print("image ok", type(image).__name__)
try:
    from dspy.utils.exceptions import AdapterParseError
    print("AdapterParseError ok")
except ImportError as error:
    print("AdapterParseError missing:", error)
lm = dspy.LM("gemini/x", api_key="k", temperature=0.0, num_retries=0, cache=False)
print("lm ok")
EOF
```

Expected: every line prints `True` / `ok`. If anything is missing or differs, stop and adapt this task's code (and note it in the spec) before continuing: `dspy.Image` construction, the `lm=` per-call keyword on `Predict.acall`, `dspy.configure(track_usage=True)` + `Prediction.get_lm_usage()` under async, and the parse-error exception class. The mapping/usage/manifest tests below do not depend on these and pin the behaviour regardless.

- [ ] **Step 2: Write the failing test** — `tests/test_llm_compare_judge.py`

```python
import asyncio

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
    return asyncio.run(judge.judge([prepared_pair(f"K{n}", pdf=f"images/{n}.png") for n in range(count)]))


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
        [PairVerdictModel(pair_id=1, verdict="IDENTICAL", differences=[]),
         PairVerdictModel(pair_id=2, verdict="DIFFERENT", differences=["label X missing"])],
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
        {"pair_id": 1, "verdict": "identical", "differences": []},   # wrong case
        {"pair_id": 1, "verdict": "MAYBE", "differences": []},       # unknown label
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
```

- [ ] **Step 3: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_judge.py -q`
Expected: FAIL `ModuleNotFoundError: llm_compare.analysis.judge`

- [ ] **Step 4: Implement**

`src/llm_compare/analysis/prompt.py`:

```python
# ruff: noqa: E501  (the prompt is the user's text, verbatim; its lines are long)
"""The agreed Gemini comparison prompt, verbatim, plus the paragraph that makes it work on
a batch of numbered pairs. Editing the text changes PROMPT_VERSION and so invalidates the
cache."""

import hashlib

INSTRUCTIONS = """\
System / Instruction Prompt:
You are an expert visual analysis AI. Your task is to compare two provided images to determine if their visible content, information, and structural layout are functionally identical.
Guidelines for Comparison:

1. Focus on Content: Compare all text, labels, diagrams, shapes, illustrations, annotations, structural elements, and data points present in both images.
2. Ignore Quality & Formatting Differences: Do NOT flag differences in image resolution, pixelation, compression artifacts, aspect ratio, image file format, scaling, or minor brightness/contrast variations.
3. Determine Match: The images should be considered identical in content if a reader receives the exact same information, wording, diagrams, and layout from both.

Output Structure:

* Verdict: State clearly whether the content is IDENTICAL or DIFFERENT
* Differences (if any):
* If DIFFERENT, list the specific missing, modified, visible information, wording, annotations, and structural diagrams  between the two.

Batch handling: this call holds several numbered pairs. Judge each pair independently of the others, comparing only image A (PDF) with image B (web) of the same pair. Return one verdict per pair, with pair_id equal to the PAIR number, verdict exactly IDENTICAL or DIFFERENT, and differences empty when IDENTICAL.
"""

PROMPT_VERSION = hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()[:12]
```

`src/llm_compare/analysis/judge.py`:

```python
"""The DSPy implementation of PairJudge: one multimodal call judges a numbered batch of
image pairs and returns a structured verdict per pair."""

import base64
from collections.abc import Sequence
from typing import Literal

import dspy
from pydantic import BaseModel, Field

from llm_compare.analysis.prompt import INSTRUCTIONS
from llm_compare.config import LlmCompareConfig, litellm_model
from llm_compare.domain.costing import cost_of
from llm_compare.domain.errors import JudgeError, Permanent, RateLimited, Transient
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import PairVerdict, Prices, PreparedPair, Usage, Verdict

try:
    from dspy.utils.exceptions import AdapterParseError

    _PARSE_ERRORS: tuple[type[Exception], ...] = (AdapterParseError, ValueError)
except ImportError:
    _PARSE_ERRORS = (ValueError,)

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
        lines.append(
            f"PAIR {number}: image {first} is A (PDF), image {first + 1} is B (web)"
        )
    return "\n".join(lines)


def _to_image(png: bytes) -> dspy.Image:
    return dspy.Image(url="data:image/png;base64," + base64.b64encode(png).decode())


def _retry_after(error: Exception) -> float | None:
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def map_litellm_error(error: Exception) -> JudgeError:
    status = getattr(error, "status_code", None)
    if status == 429 or type(error).__name__ == "RateLimitError":
        return RateLimited(str(error), _retry_after(error))
    if (status is not None and status >= 500) or type(error).__name__ in _TRANSIENT_NAMES:
        return Transient(str(error))
    return Permanent(str(error))


def _usage_of(prediction, prices: Prices | None) -> Usage:
    per_model = prediction.get_lm_usage() or {}
    prompt = sum(int(m.get("prompt_tokens") or 0) for m in per_model.values())
    completion = sum(int(m.get("completion_tokens") or 0) for m in per_model.values())
    total = sum(int(m.get("total_tokens") or 0) for m in per_model.values())
    output = max(total - prompt, completion)
    return Usage(prompt, output, cost_of(prompt, output, prices))


def _verdicts_of(prediction) -> list[PairVerdict]:
    parsed = [PairVerdictModel.model_validate(item) for item in prediction.verdicts]
    return [
        PairVerdict(item.pair_id, Verdict(item.verdict), tuple(item.differences)) for item in parsed
    ]


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
        self._lm = lm or dspy.LM(
            litellm_model(config.model),
            api_key=config.api_key,
            temperature=0.0,
            num_retries=0,
            cache=False,
        )
        self._predictor = predictor or dspy.Predict(build_signature(instructions))
        dspy.configure(track_usage=True)

    async def judge(self, pairs: Sequence[PreparedPair]) -> JudgeResult:
        images = [_to_image(side.png) for pair in pairs for side in (pair.pdf, pair.web)]
        try:
            prediction = await self._predictor.acall(
                manifest=build_manifest(len(pairs)), images=images, lm=self._lm
            )
        except _PARSE_ERRORS:
            return JudgeResult([], Usage())
        except Exception as error:
            raise map_litellm_error(error) from error
        return self._result(prediction)

    def _result(self, prediction) -> JudgeResult:
        usage = _usage_of(prediction, self._prices)
        try:
            return JudgeResult(_verdicts_of(prediction), usage)
        except _PARSE_ERRORS:
            return JudgeResult([], usage)
```

Note for the implementer: the malformed-verdict test expects `usage.input_tokens == 0` because the fake prediction there has no usage; a real malformed answer keeps its real usage (counted as wasted by the runner).

- [ ] **Step 5: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_judge.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/llm_compare/analysis/prompt.py src/llm_compare/analysis/judge.py tests/test_llm_compare_judge.py
git commit -m "feat(llm-compare): DSPy judge for batches of image pairs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Runner (classify, prepare, batch, judge, retry, cache)

**Files:**
- Create: `src/llm_compare/analysis/hash_score.py`, `src/llm_compare/analysis/runner.py`
- Test: `tests/test_llm_compare_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces: `score_pair(pair, pdf_bytes, web_bytes) -> float` (`compare_images(comparison_key(pair.key, pair.web_key or pair.key), ...).similarity_percent`); `ScoredPair(pair, pdf_bytes, web_bytes, score)`; `Classification(settled: dict[str, PairRecord], to_llm: list[ScoredPair])`; `classify_pairs(pairs, load, threshold, scorer=score_pair) -> Classification` where `load(path) -> bytes | None`; `prepare_pairs(scored, max_edge, token_scale) -> list[PreparedPair]`; `RunStats(calls=0, wasted=Usage())`; `JudgeDeps(judge, limiter, cache, config, prompt_version, stats, sleep, jitter)`; `async judge_pairs(prepared, deps) -> dict[str, PairRecord]`; `RunOutcome(records: list[PairRecord], calls: int, wasted: Usage)`; `async run_comparison(pairs, load, deps, *, limit=None, scorer=score_pair) -> RunOutcome`.
- Cache entry shape: `{"verdict": str, "differences": list[str], "input_tokens": int, "output_tokens": int, "cost": float | None}`.

- [ ] **Step 1: Write the failing test** — `tests/test_llm_compare_runner.py`

```python
import asyncio

import pytest

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
        self.batches, self.drop_in_batches, self.drop_always = [], set(drop_in_batches), set(drop_always)
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
            if p.key not in self.drop_always and not (len(pairs) > 1 and p.key in self.drop_in_batches)
        ]
        count = len(pairs)
        return JudgeResult(verdicts, Usage(100 * count, 10 * count, 0.01 * count))


def _deps(judge, cache=None, **overrides):
    settings = {"max_pairs_per_call": 3, "workers": 2, "rpm": 10_000, "tpm": 10**9,
                "retry_base_delay": 0.0, **overrides}
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
    web_only = ImagePair(row_id="web:w", key="W", pdf_path=None, web_path="web_images/w.png", web_key="W")
    skipped = ImagePair(row_id="pdf:s", key="S", pdf_path="images/s.png", web_path=None,
                        skip_reason="no web counterpart")
    pairs = [_pair("hi"), _pair("lo"), web_only, skipped, _pair("gone")]
    files = _files("images/hi.png", "web_images/hi.png", "images/lo.png", "web_images/lo.png")
    result = classify_pairs(pairs, _loader(files), 90.0, _scores(hi=95.0, lo=40.0))
    assert result.settled["pdf:images/hi.png"].verdict is Verdict.MATCH_PHASH
    assert result.settled["pdf:images/hi.png"].score == 95.0
    assert result.settled["web:w"].verdict is Verdict.WEB_ONLY
    assert (result.settled["pdf:s"].verdict, result.settled["pdf:s"].message) == (
        Verdict.SKIPPED, "no web counterpart")
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
    assert [r.verdict for r in outcome.records] == [Verdict.MATCH_PHASH, Verdict.IDENTICAL, Verdict.IDENTICAL]
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
        run_comparison([_pair(k) for k in keys], _loader(files), _deps(ScriptedJudge()),
                       limit=1, scorer=_scores(a=1.0, b=1.0, c=1.0))
    )
    assert [r.verdict for r in outcome.records] == [Verdict.IDENTICAL, Verdict.SKIPPED, Verdict.SKIPPED]
    assert "--limit" in outcome.records[1].message


def test_prepare_pairs_estimates_tokens_from_the_prepared_sizes():
    from llm_compare.analysis.runner import ScoredPair

    scored = [ScoredPair(_pair("a"), PNG, PNG, 10.0)]
    (prepared,) = prepare_pairs(scored, max_edge=1024, token_scale=1.0)
    assert prepared.tokens == 516 and (prepared.pdf.width, prepared.pdf.height) == (40, 30)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_runner.py -q`
Expected: FAIL `ModuleNotFoundError: llm_compare.analysis.runner`

- [ ] **Step 3: Implement**

`src/llm_compare/analysis/hash_score.py`:

```python
"""The perceptual-hash score the routing is based on: the same score the comparison engine
uses (better of plain and ink phash for figures, plain for equations)."""

from comparison.image_similarity import compare_images, comparison_key
from llm_compare.domain.models import ImagePair


def score_pair(pair: ImagePair, pdf_bytes: bytes, web_bytes: bytes) -> float:
    key = comparison_key(pair.key, pair.web_key or pair.key)
    return compare_images(key, pdf_bytes, web_bytes).similarity_percent
```

`src/llm_compare/analysis/runner.py`:

```python
"""Runs the comparison: route each pair by its hash score, prepare the images that need the
LLM, pack them into calls, judge the calls concurrently inside the rate limits, re-queue
unusable answers one pair at a time, and remember every verdict."""

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass, field

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
    pdf_bytes, web_bytes = load(pair.pdf_path), load(pair.web_path or "")
    if pdf_bytes is None or web_bytes is None:
        return _skipped(pair, "image file missing")
    try:
        score = scorer(pair, pdf_bytes, web_bytes)
    except (OSError, ValueError) as error:
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


def prepare_pairs(scored: list[ScoredPair], max_edge: int, token_scale: float) -> list[PreparedPair]:
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
        pair.pair, Verdict.ERROR, score=pair.score, message=message, batch_id=batch_id, **_sizes(pair)
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
    estimate = estimate_call_tokens(pairs, config.call_overhead_tokens, config.output_tokens_per_pair)

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


async def _attempt(pairs, batch_id, deps, records) -> list[PreparedPair]:
    """One call for `pairs`; returns the pairs it gave no usable verdict for."""
    try:
        result = await _call_judge(pairs, deps)
    except JudgeError as error:
        for pair in pairs:
            records[pair.row_id] = _error_record(pair, batch_id, str(error))
        return []
    good, missing = validate_verdicts(len(pairs), result.verdicts)
    answered = sorted(good)
    if not answered:
        deps.stats.wasted = add_usage(deps.stats.wasted, result.usage)
    shares = split_usage(result.usage, [pairs[n - 1].tokens for n in answered])
    for number, share in zip(answered, shares, strict=True):
        _store(pairs[number - 1], good[number], share, batch_id, deps, records)
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
    batches = pack(misses, config.max_pairs_per_call, config.max_input_tokens, config.call_overhead_tokens)
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_runner.py -q`
Expected: PASS. If `test_prepare_pairs_estimates_tokens_from_the_prepared_sizes` disagrees on the token count, recompute: the prepared images are 40x30, both sides <= 384 so each is 258 -> 516.

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/analysis/hash_score.py src/llm_compare/analysis/runner.py tests/test_llm_compare_runner.py
git commit -m "feat(llm-compare): async runner with batching, retries, limits and caching" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Report (JSON + HTML showing every image and verdict)

**Files:**
- Create: `src/llm_compare/output/report.py`
- Test: `tests/test_llm_compare_report.py`

**Interfaces:**
- Consumes: `PairRecord`, `Usage`, `Verdict`, `LLM_VERDICTS`.
- Produces: `summarise(records, calls: int, wasted: Usage) -> dict`; `build_report(records, *, calls, wasted, model, prompt_version, generated_at: str) -> dict` (`{"generated_at","model","prompt_version","summary","rows"}`); `render_html(report: dict, asset_prefix: str = "") -> str`; `write_report(report, output_dir: Path, asset_prefix: str = "") -> tuple[Path, Path]` writing `llm_image_compare.json` and `llm_image_report.html`.

`summarise` keys: `total_rows`, `counts` (all six verdicts, zero-filled), `judged_by_llm`, `cached_hits`, `settled_by_hash`, `calls`, `input_tokens`, `output_tokens`, `cost` (None if unknown), `cost_per_judged_pair`, `estimated_saved_cost`. Token/cost totals cover pairs judged **this run** (not cached) plus wasted calls.

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest

from llm_compare.domain.models import PairRecord, Usage, Verdict
from llm_compare.output.report import build_report, render_html, summarise, write_report


def _rec(key, verdict, **extra):
    base = {"row_id": f"pdf:{key}", "key": key, "verdict": verdict,
            "pdf_path": f"images/{key}.png", "web_path": f"web_images/{key}.jpg"}
    return PairRecord(**{**base, **extra})


def _records():
    return [
        _rec("A.Fig1", Verdict.MATCH_PHASH, score=97.0),
        _rec("A.Fig2", Verdict.IDENTICAL, score=60.0, input_tokens=1000, output_tokens=50,
             cost=0.002, batch_id=1, sent_pdf=(40, 30), sent_web=(80, 60)),
        _rec("A.Fig3", Verdict.DIFFERENT, score=30.0, input_tokens=2000, output_tokens=100,
             cost=0.004, batch_id=1, differences=("label 'X' missing",)),
        _rec("A.Fig4", Verdict.IDENTICAL, score=70.0, input_tokens=500, output_tokens=10,
             cost=0.001, cached=True),
        _rec("A.Fig5", Verdict.SKIPPED, web_path=None, message="no web counterpart"),
        PairRecord(row_id="web:w", key="W.Fig1", verdict=Verdict.WEB_ONLY, pdf_path=None,
                   web_path="web_images/w.jpg"),
        _rec("A.Fig6", Verdict.ERROR, message="no usable verdict after retries"),
    ]


def test_summary_counts_every_verdict_and_totals_only_this_runs_spend():
    summary = summarise(_records(), calls=2, wasted=Usage(100, 5, 0.0005))
    assert summary["total_rows"] == 7
    assert summary["counts"] == {"MATCH_PHASH": 1, "IDENTICAL": 2, "DIFFERENT": 1, "SKIPPED": 1,
                                 "WEB_ONLY": 1, "ERROR": 1}
    assert (summary["judged_by_llm"], summary["cached_hits"], summary["settled_by_hash"]) == (3, 1, 1)
    assert summary["calls"] == 2
    assert (summary["input_tokens"], summary["output_tokens"]) == (3100, 155)
    assert summary["cost"] == pytest.approx(0.0065)
    assert summary["cost_per_judged_pair"] == pytest.approx(0.0065 / 2)
    assert summary["estimated_saved_cost"] == pytest.approx(0.0065 / 2)


def test_unknown_cost_stays_unknown_everywhere():
    records = [_rec("A.Fig2", Verdict.IDENTICAL, input_tokens=10, output_tokens=1, cost=None, batch_id=1)]
    summary = summarise(records, calls=1, wasted=Usage())
    assert summary["cost"] is None and summary["cost_per_judged_pair"] is None
    assert "cost unavailable" in render_html(build_report(records, calls=1, wasted=Usage(), model="m",
                                                           prompt_version="v", generated_at="t"))


def test_an_empty_run_is_valid():
    report = build_report([], calls=0, wasted=Usage(), model="m", prompt_version="v", generated_at="t")
    assert report["summary"]["total_rows"] == 0
    assert render_html(report).count("<tr data-verdict") == 0


def _html(records=None, prefix=""):
    report = build_report(records or _records(), calls=2, wasted=Usage(), model="gemini-x",
                          prompt_version="abc123", generated_at="2026-10-12T00:00:00+00:00")
    return render_html(report, prefix), report


def test_every_record_gets_a_row_with_its_verdict():
    html, report = _html()
    assert html.count("<tr data-verdict") == 7 == len(report["rows"])
    for verdict in ("MATCH_PHASH", "IDENTICAL", "DIFFERENT", "SKIPPED", "WEB_ONLY", "ERROR"):
        assert f"v-{verdict}" in html


def test_both_images_are_shown_with_their_sent_size_and_a_web_only_row_shows_one():
    html, _ = _html()
    assert 'src="images/A.Fig2.png"' in html and 'src="web_images/A.Fig2.jpg"' in html
    assert "sent 40×30" in html and "sent 80×60" in html
    assert 'src="web_images/w.jpg"' in html and "images/W.Fig1" not in html


def test_the_asset_prefix_is_applied_to_every_image():
    html, _ = _html(prefix="../src_out/")
    assert 'src="../src_out/images/A.Fig2.png"' in html


def test_differences_message_and_numbers_are_shown():
    html, _ = _html()
    assert "label &#x27;X&#x27; missing" in html
    assert "no web counterpart" in html and "no usable verdict after retries" in html
    assert "1,000" in html and "cached" in html


def test_special_characters_in_keys_and_messages_are_escaped_and_searchable():
    nasty = _rec("B.A-9.8.8.6.(1).Fig4 <&>", Verdict.DIFFERENT, differences=("<script>alert(1)</script>",),
                 input_tokens=1, output_tokens=1, cost=0.0, batch_id=1)
    html, _ = _html([nasty])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "B.A-9.8.8.6.(1).Fig4 &lt;&amp;&gt;" in html
    assert "data-key='b.a-9.8.8.6.(1).fig4 &lt;&amp;&gt;'" in html


def test_the_header_states_tokens_cost_and_the_free_hash_settlements():
    html, _ = _html()
    for text in ("gemini-x", "abc123", "3,000", "$0.00600", "settled by hash"):
        assert text in html


def test_write_report_creates_both_files(tmp_path):
    _, report = _html()
    json_path, html_path = write_report(report, tmp_path, asset_prefix="")
    assert json.loads(json_path.read_text())["summary"]["total_rows"] == 7
    assert html_path.name == "llm_image_report.html" and "<table" in html_path.read_text()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_llm_compare_report.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement** — `src/llm_compare/output/report.py`

```python
# ruff: noqa: E501  (inline CSS/HTML strings)
"""The report: a JSON file for programs and a self-contained HTML page for people that shows
every image (both sides, side by side), its verdict, and what the LLM check cost."""

import json
from collections import Counter
from dataclasses import asdict
from html import escape
from pathlib import Path
from urllib.parse import quote

from llm_compare.domain.models import LLM_VERDICTS, PairRecord, Usage, Verdict

_ROUTE = {
    Verdict.MATCH_PHASH: "hash",
    Verdict.IDENTICAL: "LLM",
    Verdict.DIFFERENT: "LLM",
    Verdict.ERROR: "LLM",
}


def _total_cost(live: list[PairRecord], wasted: Usage) -> float | None:
    costs = [record.cost for record in live]
    if wasted.input_tokens or wasted.output_tokens:
        costs.append(wasted.cost)
    return None if any(cost is None for cost in costs) else sum(costs)


def summarise(records: list[PairRecord], calls: int, wasted: Usage) -> dict:
    counts = Counter(record.verdict for record in records)
    judged = [record for record in records if record.verdict in LLM_VERDICTS]
    live = [record for record in judged if not record.cached]
    cost = _total_cost(live, wasted)
    per_pair = cost / len(live) if cost is not None and live else None
    settled = counts[Verdict.MATCH_PHASH]
    return {
        "total_rows": len(records),
        "counts": {verdict.value: counts[verdict] for verdict in Verdict},
        "judged_by_llm": len(judged),
        "cached_hits": sum(record.cached for record in judged),
        "settled_by_hash": settled,
        "calls": calls,
        "input_tokens": sum(r.input_tokens for r in live) + wasted.input_tokens,
        "output_tokens": sum(r.output_tokens for r in live) + wasted.output_tokens,
        "cost": cost,
        "cost_per_judged_pair": per_pair,
        "estimated_saved_cost": per_pair * settled if per_pair is not None else None,
    }


def _row(record: PairRecord) -> dict:
    row = asdict(record)
    row["verdict"] = record.verdict.value
    row["route"] = _ROUTE.get(record.verdict, "—")
    row["differences"] = list(record.differences)
    return row


def build_report(
    records: list[PairRecord],
    *,
    calls: int,
    wasted: Usage,
    model: str,
    prompt_version: str,
    generated_at: str,
) -> dict:
    return {
        "generated_at": generated_at,
        "model": model,
        "prompt_version": prompt_version,
        "summary": summarise(records, calls, wasted),
        "rows": [_row(record) for record in records],
    }


_STYLE = """
:root{--bg:#fff;--fg:#1d2330;--mute:#667085;--line:#e3e6ec;--card:#f6f7fa;
--ok:#1a7f4b;--bad:#c0392b;--warn:#b7791f;--info:#2b6cb0;--none:#718096}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14171f;--fg:#e6e9f0;
--mute:#9aa3b5;--line:#2a2f3c;--card:#1c202b;--ok:#4cc38a;--bad:#ff7b6b;--warn:#e0b04c;
--info:#6cb0ff;--none:#8a93a6}}
:root[data-theme=dark]{--bg:#14171f;--fg:#e6e9f0;--mute:#9aa3b5;--line:#2a2f3c;--card:#1c202b;
--ok:#4cc38a;--bad:#ff7b6b;--warn:#e0b04c;--info:#6cb0ff;--none:#8a93a6}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,sans-serif}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mute);margin-bottom:14px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;min-width:120px}
.card b{display:block;font-size:18px}.card span{color:var(--mute);font-size:12px}
.tools{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
select,input{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}
th{position:sticky;top:0;background:var(--card);font-size:12px;color:var(--mute)}
td img{max-width:260px;max-height:200px;border:1px solid var(--line);background:#fff;display:block}
.cap,.none{color:var(--mute);font-size:12px}.key{font-family:ui-monospace,monospace;font-size:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;
border:1px solid currentColor}
.v-MATCH_PHASH,.v-IDENTICAL{color:var(--ok)}.v-DIFFERENT,.v-ERROR{color:var(--bad)}
.v-SKIPPED{color:var(--warn)}.v-WEB_ONLY{color:var(--info)}
ul{margin:4px 0 0 18px;padding:0}.num{white-space:nowrap}
"""

_SCRIPT = """
const rows=[...document.querySelectorAll('tbody tr')];
const verdict=document.getElementById('verdict'),query=document.getElementById('q');
function apply(){const v=verdict.value,q=query.value.toLowerCase();
for(const r of rows){r.hidden=!((v==='ALL'||r.dataset.verdict===v)&&(!q||r.dataset.key.includes(q)));}}
verdict.addEventListener('change',apply);query.addEventListener('input',apply);
"""


def _money(value: float | None) -> str:
    return "cost unavailable" if value is None else f"${value:.5f}"


def _src(path: str, prefix: str) -> str:
    return escape(prefix + quote(path), quote=True)


def _image_cell(path: str | None, prefix: str, sent: list | None) -> str:
    if not path:
        return "<span class='none'>—</span>"
    caption = f"<div class='cap'>sent {sent[0]}×{sent[1]}</div>" if sent else ""
    source = _src(path, prefix)
    return (
        f'<a href="{source}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{source}" alt=""></a>{caption}'
    )


def _details(row: dict) -> str:
    parts = []
    if row["score"] is not None:
        parts.append(f"<div class='cap'>hash {row['score']:.1f}%</div>")
    if row["differences"]:
        items = "".join(f"<li>{escape(text)}</li>" for text in row["differences"])
        parts.append(f"<ul>{items}</ul>")
    if row["message"]:
        parts.append(f"<div>{escape(row['message'])}</div>")
    return "".join(parts) or "<span class='none'>—</span>"


def _usage(row: dict) -> str:
    if row["verdict"] not in ("IDENTICAL", "DIFFERENT"):
        return "<span class='none'>—</span>"
    cached = " · cached" if row["cached"] else ""
    batch = f"batch {row['batch_id']}" if row["batch_id"] is not None else "earlier run"
    return (
        f"{row['input_tokens']:,} in / {row['output_tokens']:,} out<br>"
        f"{_money(row['cost'])}<div class='cap'>{batch}{cached}</div>"
    )


def _row_html(row: dict, prefix: str) -> str:
    verdict = row["verdict"]
    key = escape(row["key"].lower(), quote=True)
    badge = f"<span class='badge v-{verdict}'>{verdict}</span><div class='cap'>{row['route']}</div>"
    cells = [
        f"<td class='key'>{escape(row['key'])}</td>",
        f"<td>{_image_cell(row['pdf_path'], prefix, row['sent_pdf'])}</td>",
        f"<td>{_image_cell(row['web_path'], prefix, row['sent_web'])}</td>",
        f"<td>{badge}</td>",
        f"<td>{_details(row)}</td>",
        f"<td class='num'>{_usage(row)}</td>",
    ]
    return f"<tr data-verdict='{verdict}' data-key='{key}'>{''.join(cells)}</tr>"


def _cards(summary: dict) -> str:
    cards = [
        ("images", f"{summary['total_rows']:,}"),
        ("settled by hash (free)", f"{summary['settled_by_hash']:,}"),
        ("judged by LLM", f"{summary['judged_by_llm']:,}"),
        ("from cache", f"{summary['cached_hits']:,}"),
        ("LLM calls", f"{summary['calls']:,}"),
        ("input tokens", f"{summary['input_tokens']:,}"),
        ("output tokens", f"{summary['output_tokens']:,}"),
        ("cost this run", _money(summary["cost"])),
        ("cost per judged pair", _money(summary["cost_per_judged_pair"])),
        ("est. saved by hash", _money(summary["estimated_saved_cost"])),
    ]
    return "".join(f"<div class='card'><b>{value}</b><span>{label}</span></div>" for label, value in cards)


def _verdict_options(counts: dict) -> str:
    options = "".join(f"<option value='{v}'>{v} ({n})</option>" for v, n in counts.items())
    return f"<option value='ALL'>All verdicts</option>{options}"


def render_html(report: dict, asset_prefix: str = "") -> str:
    summary = report["summary"]
    body = "\n".join(_row_html(row, asset_prefix) for row in report["rows"])
    head = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>LLM Image Report</title><style>{_STYLE}</style></head><body>"
    )
    title = (
        f"<h1>LLM image comparison</h1><div class='sub'>model {escape(report['model'])} · "
        f"prompt {escape(report['prompt_version'])} · {escape(report['generated_at'])}</div>"
    )
    tools = (
        f"<div class='tools'><select id='verdict'>{_verdict_options(summary['counts'])}</select>"
        "<input id='q' type='search' placeholder='Search unified number'></div>"
    )
    table = (
        "<div class='wrap'><table><thead><tr><th>Unified number</th><th>PDF image</th>"
        "<th>Web image</th><th>Verdict</th><th>Details</th><th>Tokens / cost</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )
    cards = f"<div class='cards'>{_cards(summary)}</div>"
    return f"{head}{title}{cards}{tools}{table}<script>{_SCRIPT}</script></body></html>"


def write_report(report: dict, output_dir: Path, asset_prefix: str = "") -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "llm_image_compare.json"
    html_path = output_dir / "llm_image_report.html"
    json_path.write_text(json.dumps(report, indent=2))
    html_path.write_text(render_html(report, asset_prefix))
    return json_path, html_path
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pytest tests/test_llm_compare_report.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/output/report.py tests/test_llm_compare_report.py
git commit -m "feat(llm-compare): report showing every image, verdict, tokens and cost" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Dry-run estimate and the CLI

**Files:**
- Create: `src/llm_compare/analysis/estimate.py`, `src/build_llm_comparison.py`
- Test: `tests/test_llm_compare_estimate.py`, `tests/test_build_llm_comparison.py`

**Interfaces:**
- Consumes: runner functions, `VerdictCache`, `resolve_prices`, `build_pairs`, `build_report`, `write_report`, `DspyPairJudge`, `PROMPT_VERSION`.
- Produces: `RunPlan(rows, settled_by_hash, web_only, skipped, to_llm, cached, calls, input_tokens, output_tokens, cost)`; `plan_run(pairs, load, config, cache, prompt_version, prices, scorer=score_pair) -> RunPlan`; `format_plan(plan) -> str`; CLI `main(argv=None, env=os.environ, judge=None, now=None) -> int`.
- CLI flags: `--source-dir` (default `output/`: where `bcbc_pdf.json`, `bcbc_web.json`, `comparison.json`, `images/`, `web_images/` live), `--output-dir` (default: the source dir; receives the report and the `llm_compare/` cache), `--config` (default `llm_compare_config.toml`), `--env-file` (default `.env` in the project root), `--dry-run`, `--limit N`. (`--calibrate N` is added in Task 13.) Exit codes: 0 ok, 2 configuration/inputs problem (e.g. missing key), 130 interrupted (the report is still written from the cache; unfinished pairs are `ERROR`).
- The CLI calls `score_pair` through its own module-level name so tests can monkeypatch `build_llm_comparison.score_pair`.

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_compare_estimate.py`:

```python
from llm_compare.analysis.estimate import format_plan, plan_run
from llm_compare.analysis.runner import classify_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.models import ImagePair, Prices
from llm_compare.output.cache import VerdictCache, pair_cache_key
from tests.llm_compare_support import image_pair, png_bytes

FIRST, SECOND = png_bytes(), png_bytes(box=(5, 5, 40, 30))  # different bytes -> different cache keys


def _setup():
    keys = ("hi", "lo1", "lo2")
    pairs = [image_pair(k, pdf=f"images/{k}.png", web=f"web_images/{k}.png") for k in keys]
    pairs.append(ImagePair(row_id="web:w", key="W", pdf_path=None, web_path="web_images/w.png"))
    files = {}
    for key, png in zip(keys, (FIRST, FIRST, SECOND), strict=True):
        files[f"images/{key}.png"] = files[f"web_images/{key}.png"] = png
    scores = {"hi": 95.0, "lo1": 10.0, "lo2": 20.0}
    return pairs, files.get, (lambda pair, a, b: scores[pair.key])


def test_the_plan_counts_routes_calls_and_estimates_tokens_and_cost():
    pairs, load, scorer = _setup()
    config = LlmCompareConfig(model="m", max_pairs_per_call=6)
    plan = plan_run(pairs, load, config, VerdictCache(), "v1", Prices(1.0, 2.0), scorer)
    assert (plan.rows, plan.settled_by_hash, plan.web_only, plan.to_llm, plan.cached) == (4, 1, 1, 2, 0)
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
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), VerdictCache(), "v1", Prices(1.0, 2.0),
                    lambda p, a, b: 100.0)
    assert (plan.to_llm, plan.calls, plan.input_tokens, plan.output_tokens) == (0, 0, 0, 0)
    assert plan.cost == 0.0


def test_format_plan_names_the_cost_or_says_it_is_unavailable():
    pairs, load, scorer = _setup()
    plan = plan_run(pairs, load, LlmCompareConfig(model="m"), VerdictCache(), "v1", None, scorer)
    text = format_plan(plan)
    assert "cost unavailable" in text and "LLM calls: 1" in text and "settled by hash (free): 1" in text
```

`tests/test_build_llm_comparison.py`:

```python
import json

import build_llm_comparison
from build_llm_comparison import main
from llm_compare.domain.judge import JudgeResult
from llm_compare.domain.models import PairVerdict, Usage, Verdict
from tests.llm_compare_support import png_bytes

PNG = png_bytes()
ENV = {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-x", "PATH": ""}


class AllIdentical:
    def __init__(self):
        self.calls = 0

    async def judge(self, pairs):
        self.calls += 1
        verdicts = [PairVerdict(n, Verdict.IDENTICAL, ()) for n in range(1, len(pairs) + 1)]
        return JudgeResult(verdicts, Usage(10 * len(pairs), len(pairs), 0.001))


def _source(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(exist_ok=True)
    (root / "web_images").mkdir(exist_ok=True)
    (root / "images/a.png").write_bytes(PNG)
    (root / "web_images/a.png").write_bytes(PNG)
    pdf = {"images": [{"image_path": "images/a.png", "unified_number": "A.Fig1"}], "volume": {}}
    web = {"images": [{"id": "a", "unified_number": "A.Fig1", "local_path": "web_images/a.png"}], "tree": {}}
    (root / "bcbc_pdf.json").write_text(json.dumps(pdf))
    (root / "bcbc_web.json").write_text(json.dumps(web))
    (root / "comparison.json").write_text(json.dumps({"counterparts": {}}))
    return root


def _args(source, *extra, out=None):
    return ["--source-dir", str(source), "--output-dir", str(out or source),
            "--config", str(source / "none.toml"), "--env-file", str(source / "none.env"), *extra]


def test_identical_images_are_settled_by_the_hash_and_still_reported(tmp_path):
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source), env=ENV, judge=judge, now="2026-10-12T00:00:00+00:00") == 0
    assert judge.calls == 0
    report = json.loads((source / "llm_image_compare.json").read_text())
    assert [row["verdict"] for row in report["rows"]] == ["MATCH_PHASH"]
    assert (source / "llm_image_report.html").exists()


def test_a_pair_the_hash_cannot_settle_is_judged_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 0
    assert judge.calls == 1
    row = json.loads((source / "llm_image_compare.json").read_text())["rows"][0]
    assert row["verdict"] == "IDENTICAL" and row["input_tokens"] == 10
    assert (source / "llm_compare" / "cache.json").exists()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 0
    assert judge.calls == 1  # the second run is served from the cache


def test_the_report_references_images_relative_to_the_output_directory(tmp_path):
    source = _source(tmp_path / "src")
    out = tmp_path / "out"
    assert main(_args(source, out=out), env=ENV, judge=AllIdentical(), now="t") == 0
    assert 'src="../src/images/a.png"' in (out / "llm_image_report.html").read_text()


def test_dry_run_calls_nothing_writes_no_report_and_needs_no_key(tmp_path, capsys):
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source, "--dry-run"), env={"PATH": ""}, judge=judge) == 0
    assert judge.calls == 0 and not (source / "llm_image_report.html").exists()
    assert "LLM calls" in capsys.readouterr().out


def test_a_missing_key_or_model_exits_before_any_call(tmp_path, capsys):
    source = _source(tmp_path)
    assert main(_args(source), env={"PATH": ""}, judge=None) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    assert main(_args(source), env={"GEMINI_API_KEY": "k"}, judge=None) == 2
    assert "GEMINI_MODEL" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_missing_input_files_exit_with_a_clear_message(tmp_path, capsys):
    assert main(_args(tmp_path), env=ENV, judge=AllIdentical()) == 2
    assert "bcbc_pdf.json" in capsys.readouterr().err


def test_an_invalid_config_file_exits_with_its_message(tmp_path, capsys):
    source = _source(tmp_path)
    (source / "bad.toml").write_text("rpm = 0")
    args = ["--source-dir", str(source), "--config", str(source / "bad.toml"),
            "--env-file", str(source / "none.env")]
    assert main(args, env=ENV, judge=AllIdentical()) == 2
    assert "rpm" in capsys.readouterr().err


def test_an_interrupted_run_still_reports_with_unfinished_pairs_as_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)

    class Interrupting:
        async def judge(self, pairs):
            raise KeyboardInterrupt

    assert main(_args(source), env=ENV, judge=Interrupting(), now="t") == 130
    row = json.loads((source / "llm_image_compare.json").read_text())["rows"][0]
    assert row["verdict"] == "ERROR" and "interrupted" in row["message"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_llm_compare_estimate.py tests/test_build_llm_comparison.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/llm_compare/analysis/estimate.py`:

```python
"""What a run would do and cost, worked out without calling the API (--dry-run)."""

from collections import Counter
from dataclasses import dataclass

from llm_compare.analysis.hash_score import score_pair
from llm_compare.analysis.runner import LoadBytes, Scorer, classify_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.batching import pack
from llm_compare.domain.costing import cost_of
from llm_compare.domain.models import ImagePair, Prices, Verdict
from llm_compare.output.cache import VerdictCache, pair_cache_key


@dataclass(frozen=True)
class RunPlan:
    rows: int
    settled_by_hash: int
    web_only: int
    skipped: int
    to_llm: int
    cached: int
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float | None


def plan_run(
    pairs: list[ImagePair],
    load: LoadBytes,
    config: LlmCompareConfig,
    cache: VerdictCache,
    prompt_version: str,
    prices: Prices | None,
    scorer: Scorer = score_pair,
) -> RunPlan:
    classified = classify_pairs(pairs, load, config.hash_match_percent, scorer)
    prepared = prepare_pairs(classified.to_llm, config.max_edge, config.token_scale)
    misses = [
        pair
        for pair in prepared
        if cache.get(pair_cache_key(pair, prompt_version, config.model)) is None
    ]
    batches = pack(
        misses, config.max_pairs_per_call, config.max_input_tokens, config.call_overhead_tokens
    )
    input_tokens = sum(p.tokens for p in misses) + config.call_overhead_tokens * len(batches)
    output_tokens = config.output_tokens_per_pair * len(misses)
    counts = Counter(record.verdict for record in classified.settled.values())
    return RunPlan(
        rows=len(pairs),
        settled_by_hash=counts[Verdict.MATCH_PHASH],
        web_only=counts[Verdict.WEB_ONLY],
        skipped=counts[Verdict.SKIPPED],
        to_llm=len(prepared),
        cached=len(prepared) - len(misses),
        calls=len(batches),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost_of(input_tokens, output_tokens, prices),
    )


def format_plan(plan: RunPlan) -> str:
    cost = "cost unavailable" if plan.cost is None else f"${plan.cost:.4f}"
    return "\n".join(
        [
            f"rows: {plan.rows}  (web-only {plan.web_only}, skipped {plan.skipped})",
            f"settled by hash (free): {plan.settled_by_hash}",
            f"for the LLM: {plan.to_llm}  (already cached {plan.cached})",
            f"LLM calls: {plan.calls}",
            f"estimated tokens: {plan.input_tokens:,} in / {plan.output_tokens:,} out",
            f"estimated cost: {cost}",
        ]
    )
```

`src/build_llm_comparison.py`:

```python
"""Judge, with a multimodal LLM (DSPy), the PDF/web image pairs the perceptual hash cannot
settle, and write a report of every image with its verdict, tokens and cost.

    python src/build_llm_comparison.py --dry-run       # counts + estimated tokens/cost, no API call
    python src/build_llm_comparison.py --limit 10      # try 10 pairs first
    python src/build_llm_comparison.py --calibrate 24  # choose max_edge / batch size by evidence
    python src/build_llm_comparison.py                 # the full run (resumable, cached)

GEMINI_API_KEY and GEMINI_MODEL come from the environment or .env; other settings from
llm_compare_config.toml (see llm_compare_config.example.toml). Inputs are read from
--source-dir (default output/); the report and cache go to --output-dir (default the same).
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_compare.analysis.estimate import format_plan, plan_run  # noqa: E402
from llm_compare.analysis.hash_score import score_pair  # noqa: E402
from llm_compare.analysis.limiter import RateLimiter  # noqa: E402
from llm_compare.analysis.pricing import resolve_prices  # noqa: E402
from llm_compare.analysis.prompt import PROMPT_VERSION  # noqa: E402
from llm_compare.analysis.runner import JudgeDeps, RunOutcome, run_comparison  # noqa: E402
from llm_compare.config import ConfigError, LlmCompareConfig, load_config, parse_dotenv  # noqa: E402
from llm_compare.domain.errors import Permanent  # noqa: E402
from llm_compare.output.cache import VerdictCache  # noqa: E402
from llm_compare.output.report import build_report, write_report  # noqa: E402
from llm_compare.parsing.pair_source import build_pairs  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILES = ("bcbc_pdf.json", "bcbc_web.json", "comparison.json")


class _RefusingJudge:
    """Used after Ctrl-C: cached verdicts are kept, unfinished pairs become ERROR rows."""

    async def judge(self, pairs):
        raise Permanent("run interrupted before this pair was judged")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-dir", type=Path, default=PROJECT_ROOT / "output")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "llm_compare_config.toml")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N pairs")
    return parser


def _read_text(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


def _load_inputs(source_dir: Path) -> tuple[list[dict], list[dict], dict]:
    missing = [name for name in INPUT_FILES if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing in {source_dir}: {', '.join(missing)}")
    pdf, web, comparison = (json.loads((source_dir / name).read_text()) for name in INPUT_FILES)
    return pdf["images"], web["images"], comparison.get("counterparts", {})


def _loader(source_dir: Path):
    def load(relative: str) -> bytes | None:
        path = source_dir / relative
        return path.read_bytes() if relative and path.is_file() else None

    return load


def _asset_prefix(source_dir: Path, output_dir: Path) -> str:
    relative = Path(os.path.relpath(source_dir, output_dir)).as_posix()
    return "" if relative == "." else relative + "/"


def _real_judge(config: LlmCompareConfig):
    from llm_compare.analysis.judge import DspyPairJudge

    return DspyPairJudge(config, resolve_prices(config))


def _check_credentials(config: LlmCompareConfig, judge) -> str | None:
    if judge is not None:
        return None
    if not config.api_key:
        return "GEMINI_API_KEY is not set (put it in .env or the environment)"
    if not config.model:
        return "GEMINI_MODEL is not set (put it in .env, the environment or the config file)"
    return None


def _finish(outcome: RunOutcome, config, source_dir, output_dir, now) -> None:
    report = build_report(
        outcome.records,
        calls=outcome.calls,
        wasted=outcome.wasted,
        model=config.model,
        prompt_version=PROMPT_VERSION,
        generated_at=now or datetime.now(UTC).isoformat(timespec="seconds"),
    )
    _, html_path = write_report(report, output_dir, _asset_prefix(source_dir, output_dir))
    summary = report["summary"]
    print(f"report: {html_path}")
    print(f"verdicts: {summary['counts']}")
    print(
        f"calls {summary['calls']}, tokens {summary['input_tokens']:,} in / "
        f"{summary['output_tokens']:,} out, cost {summary['cost']}"
    )


def _run(pairs, load, deps, limit) -> tuple[RunOutcome, bool]:
    try:
        return asyncio.run(run_comparison(pairs, load, deps, limit=limit, scorer=score_pair)), False
    except KeyboardInterrupt:
        refusing = JudgeDeps(_RefusingJudge(), deps.limiter, deps.cache, deps.config, PROMPT_VERSION)
        outcome = asyncio.run(run_comparison(pairs, load, refusing, limit=limit, scorer=score_pair))
        return outcome, True


def main(argv=None, env: Mapping[str, str] = os.environ, judge=None, now: str | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = args.output_dir or args.source_dir
    try:
        config = load_config(_read_text(args.config), env, parse_dotenv(_read_text(args.env_file)))
        pdf_images, web_images, counterparts = _load_inputs(args.source_dir)
    except (ConfigError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    pairs = build_pairs(pdf_images, web_images, counterparts)
    load = _loader(args.source_dir)
    cache = VerdictCache(output_dir / "llm_compare" / "cache.json")
    if args.dry_run:
        prices = resolve_prices(config)
        print(format_plan(plan_run(pairs, load, config, cache, PROMPT_VERSION, prices, score_pair)))
        return 0
    problem = _check_credentials(config, judge)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    limiter = RateLimiter(config.rpm, config.tpm)
    deps = JudgeDeps(judge or _real_judge(config), limiter, cache, config, PROMPT_VERSION)
    outcome, interrupted = _run(pairs, load, deps, args.limit)
    _finish(outcome, config, args.source_dir, output_dir, now)
    return 130 if interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
```

(`asyncio.run` turns a `KeyboardInterrupt` raised inside a task into a `KeyboardInterrupt` out of `asyncio.run`; the interrupted-run test relies on that. If it surfaces differently on this Python, keep the test and catch `(KeyboardInterrupt, asyncio.CancelledError)` in `_run`.)

- [ ] **Step 4: Run them to verify they pass**

Run: `pytest tests/test_llm_compare_estimate.py tests/test_build_llm_comparison.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/analysis/estimate.py src/build_llm_comparison.py tests/test_llm_compare_estimate.py tests/test_build_llm_comparison.py
git commit -m "feat(llm-compare): dry-run estimate and the build_llm_comparison CLI" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Calibration (`--calibrate N`)

**Files:**
- Create: `src/llm_compare/analysis/calibration.py`
- Modify: `src/build_llm_comparison.py` (add the `--calibrate` flag and `_calibrate`)
- Test: `tests/test_llm_compare_calibration.py`, `tests/test_build_llm_comparison.py` (one more test)

**Interfaces:**
- Produces: `ORIGINAL_EDGE = 10**6`; `Variant(name, max_edge, max_pairs_per_call)`; `default_variants(default_edge: int, default_batch: int) -> list[Variant]` -> `[original@1, 768@1, 1024@1, <default_edge>@<default_batch>]` (the first is the baseline); `sample_evenly(items: Sequence, count: int) -> list`; `agreement(baseline: dict[str, Verdict], other: dict[str, Verdict]) -> float` (share of the pairs both judged that got the same verdict; 0.0 if none shared); `VariantResult(variant, input_tokens, output_tokens, cost, verdicts)`; `async run_variants(scored, variants, config, make_deps) -> list[VariantResult]` (`make_deps(config) -> JudgeDeps`, built with a memory-only cache so every variant really calls the model); `recommend(results) -> int | None` (among results after the baseline with `max_pairs_per_call == 1` and agreement 1.0, the `max_edge` with the fewest input tokens, else None); `format_calibration(results) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_compare_calibration.py`:

```python
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
    other = {"a": Verdict.IDENTICAL, "b": Verdict.IDENTICAL, "d": Verdict.IDENTICAL, "c": Verdict.ERROR}
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
```

Add to `tests/test_build_llm_comparison.py`:

```python
def test_calibrate_prints_a_recommendation_and_saves_the_variants(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source, "--calibrate", "1"), env=ENV, judge=AllIdentical()) == 0
    assert "recommended max_edge" in capsys.readouterr().out
    saved = json.loads((source / "llm_compare" / "calibration.json").read_text())
    assert saved[0]["variant"].startswith("original size")
    assert not (source / "llm_image_report.html").exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_llm_compare_calibration.py tests/test_build_llm_comparison.py -q`
Expected: FAIL (`ModuleNotFoundError` for calibration; `unrecognized arguments: --calibrate` for the CLI test)

- [ ] **Step 3: Implement**

`src/llm_compare/analysis/calibration.py`:

```python
"""--calibrate: pick the preprocessing cap and check batching by evidence. A sample of the
pairs bound for the LLM is judged under several settings; the smallest image cap whose
verdicts match the original-size baseline is recommended, and batched verdicts are compared
with one-pair-per-call ones."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from llm_compare.analysis.runner import JudgeDeps, ScoredPair, judge_pairs, prepare_pairs
from llm_compare.config import LlmCompareConfig
from llm_compare.domain.models import LLM_VERDICTS, Verdict

ORIGINAL_EDGE = 10**6


@dataclass(frozen=True)
class Variant:
    name: str
    max_edge: int
    max_pairs_per_call: int


@dataclass(frozen=True)
class VariantResult:
    variant: Variant
    input_tokens: int
    output_tokens: int
    cost: float | None
    verdicts: dict[str, Verdict]


def default_variants(default_edge: int, default_batch: int) -> list[Variant]:
    return [
        Variant("original size, 1 per call", ORIGINAL_EDGE, 1),
        Variant("768px, 1 per call", 768, 1),
        Variant("1024px, 1 per call", 1024, 1),
        Variant(f"{default_edge}px, {default_batch} per call", default_edge, default_batch),
    ]


def sample_evenly(items: Sequence, count: int) -> list:
    if count >= len(items):
        return list(items)
    step = len(items) / count
    return [items[int(index * step)] for index in range(count)]


def agreement(baseline: dict[str, Verdict], other: dict[str, Verdict]) -> float:
    shared = [
        key for key in baseline if baseline[key] in LLM_VERDICTS and other.get(key) in LLM_VERDICTS
    ]
    if not shared:
        return 0.0
    return sum(baseline[key] == other[key] for key in shared) / len(shared)


async def _run_one(scored, variant, config, make_deps) -> VariantResult:
    settings = replace(
        config, max_edge=variant.max_edge, max_pairs_per_call=variant.max_pairs_per_call
    )
    deps = make_deps(settings)
    prepared = prepare_pairs(scored, settings.max_edge, settings.token_scale)
    records = list((await judge_pairs(prepared, deps)).values())
    costs = [record.cost for record in records]
    return VariantResult(
        variant,
        sum(record.input_tokens for record in records) + deps.stats.wasted.input_tokens,
        sum(record.output_tokens for record in records) + deps.stats.wasted.output_tokens,
        None if any(cost is None for cost in costs) else sum(costs),
        {record.row_id: record.verdict for record in records},
    )


async def run_variants(
    scored: list[ScoredPair],
    variants: list[Variant],
    config: LlmCompareConfig,
    make_deps: Callable[[LlmCompareConfig], JudgeDeps],
) -> list[VariantResult]:
    return [await _run_one(scored, variant, config, make_deps) for variant in variants]


def recommend(results: list[VariantResult]) -> int | None:
    baseline = results[0].verdicts
    keeps = [
        result
        for result in results[1:]
        if result.variant.max_pairs_per_call == 1 and agreement(baseline, result.verdicts) == 1.0
    ]
    if not keeps:
        return None
    return min(keeps, key=lambda result: result.input_tokens).variant.max_edge


def format_calibration(results: list[VariantResult]) -> str:
    baseline = results[0].verdicts
    lines = ["variant                      input tok  output tok  agreement with original"]
    for result in results:
        share = agreement(baseline, result.verdicts)
        lines.append(
            f"{result.variant.name:<28} {result.input_tokens:>9,} {result.output_tokens:>11,}"
            f"  {share:>9.0%}"
        )
    best = recommend(results)
    lines.append(f"recommended max_edge: {best if best is not None else 'none (keep original size)'}")
    return "\n".join(lines)
```

In `src/build_llm_comparison.py` add the flag to `_parser()`:

```python
    parser.add_argument(
        "--calibrate",
        type=int,
        default=None,
        metavar="N",
        help="judge N sample pairs under several settings and recommend max_edge",
    )
```

add these imports with the other `# noqa: E402` imports:

```python
from llm_compare.analysis.calibration import (  # noqa: E402
    default_variants,
    format_calibration,
    run_variants,
    sample_evenly,
)
from llm_compare.analysis.runner import classify_pairs  # noqa: E402
```

add the function:

```python
def _calibrate(count: int, pairs, load, config, judge, output_dir: Path) -> int:
    routed = classify_pairs(pairs, load, config.hash_match_percent, score_pair).to_llm
    chosen = sample_evenly(routed, count)
    shared_judge, limiter = judge or _real_judge(config), RateLimiter(config.rpm, config.tpm)

    def make_deps(settings):
        return JudgeDeps(shared_judge, limiter, VerdictCache(), settings, PROMPT_VERSION)

    variants = default_variants(config.max_edge, config.max_pairs_per_call)
    results = asyncio.run(run_variants(chosen, variants, config, make_deps))
    print(format_calibration(results))
    saved = [
        {
            "variant": r.variant.name,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "verdicts": {key: verdict.value for key, verdict in r.verdicts.items()},
        }
        for r in results
    ]
    (output_dir / "llm_compare").mkdir(parents=True, exist_ok=True)
    (output_dir / "llm_compare" / "calibration.json").write_text(json.dumps(saved, indent=2))
    return 0
```

and in `main`, right after the credentials check and before the `limiter = RateLimiter(...)` line:

```python
    if args.calibrate:
        return _calibrate(args.calibrate, pairs, load, config, judge, output_dir)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `pytest tests/test_llm_compare_calibration.py tests/test_build_llm_comparison.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_compare/analysis/calibration.py src/build_llm_comparison.py tests/test_llm_compare_calibration.py tests/test_build_llm_comparison.py
git commit -m "feat(llm-compare): --calibrate picks the image cap and checks batching" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Docs, live test, Definition of done, real run, PR

**Files:**
- Modify: `CLAUDE.md`, `Readme.md`
- Create: `tests/test_llm_compare_live.py`

- [ ] **Step 1: Opt-in live test** — `tests/test_llm_compare_live.py`

```python
"""Hits the real model on three pairs; skipped unless a key and the built output exist.
Run with: pytest -m slow tests/test_llm_compare_live.py"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from llm_compare.analysis.judge import DspyPairJudge
from llm_compare.analysis.pricing import resolve_prices
from llm_compare.analysis.runner import classify_pairs, prepare_pairs
from llm_compare.config import load_config, parse_dotenv
from llm_compare.domain.models import LLM_VERDICTS
from llm_compare.parsing.pair_source import build_pairs

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("LLM_COMPARE_SOURCE_DIR", ROOT / "output"))
ENV_FILE = Path(os.environ.get("LLM_COMPARE_ENV_FILE", ROOT / ".env"))


@pytest.mark.slow
def test_three_real_pairs_get_real_verdicts_and_usage():
    dotenv = parse_dotenv(ENV_FILE.read_text()) if ENV_FILE.is_file() else {}
    config = load_config("", os.environ, dotenv)
    if not (config.api_key and config.model and (SOURCE / "bcbc_pdf.json").is_file()):
        pytest.skip("needs GEMINI_API_KEY, GEMINI_MODEL and a built output/")
    pdf = json.loads((SOURCE / "bcbc_pdf.json").read_text())["images"]
    web = json.loads((SOURCE / "bcbc_web.json").read_text())["images"]
    counterparts = json.loads((SOURCE / "comparison.json").read_text())["counterparts"]
    load = lambda rel: (SOURCE / rel).read_bytes() if rel and (SOURCE / rel).is_file() else None  # noqa: E731
    scored = classify_pairs(build_pairs(pdf, web, counterparts), load, 90.0).to_llm[:3]
    prepared = prepare_pairs(scored, config.max_edge, config.token_scale)
    judge = DspyPairJudge(config, resolve_prices(config))
    result = asyncio.run(judge.judge(prepared))
    assert len(result.verdicts) == 3
    assert all(v.verdict in LLM_VERDICTS for v in result.verdicts)
    assert result.usage.input_tokens > 0
```

- [ ] **Step 2: Docs**

In `CLAUDE.md` add item **4. LLM visual image comparison** under "Project" (what it does in one paragraph: second-opinion verdicts for pairs the phash scores below 90%, DSPy + Gemini, batched/async/rate-limited/cached, report at `output/llm_image_report.html`, spec and plan paths), add `src/llm_compare/`, `src/build_llm_comparison.py` to the "Definition of done" scope list, and add `llm_compare_config.toml` + `.env` to the git-ignored secrets note. In `Readme.md` add a section "6. LLM image comparison" with the four commands from the CLI docstring, the `.env` keys, where results land, and a note that `--source-dir` reads another checkout's `output/` (useful from a worktree) together with `--env-file`.

- [ ] **Step 3: Definition of done** (fix everything reported)

```bash
ruff check --fix . && ruff format .
radon cc -s -n B src/llm_compare src/build_llm_comparison.py   # refactor anything graded C or worse
vulture src/llm_compare src/build_llm_comparison.py tests
pytest -q
pytest --cov=src/llm_compare --cov-report=term-missing -q
```

Expected: ruff clean; no function graded C or worse (split any that is); vulture clean (add `ignore_names` in `pyproject.toml` only for names that are read by libraries, e.g. pydantic fields); whole suite green; the new package's branches covered. Commit fixes as `chore(llm-compare): satisfy ruff/radon/vulture`.

- [ ] **Step 4: Measure on the real data (cheap first)**

Run from this worktree, reading the shared build and writing to a scratch directory (per `CLAUDE.md`, never into the shared `output/` before the PR merges):

```bash
SRC=/Users/rajeev/Projects/PlayGround/output
ENVF=/Users/rajeev/Projects/PlayGround/.env
OUT=/private/tmp/claude-501/-Users-rajeev-Projects-PlayGround/f2c2babe-8fb9-4144-a462-f5e191caf113/scratchpad/llm_out
python src/build_llm_comparison.py --source-dir "$SRC" --output-dir "$OUT" --env-file "$ENVF" --dry-run
```

Expected: ~521 comparable pairs, ~276 settled by hash, ~245 for the LLM, an estimated call count, tokens and cost. Then, with the user's go-ahead for spending API money:

```bash
python src/build_llm_comparison.py --source-dir "$SRC" --output-dir "$OUT" --env-file "$ENVF" --calibrate 24
```

Set `max_edge` (and, if batching agreement is below 100%, `max_pairs_per_call`) in `llm_compare_config.toml` from the recommendation, then:

```bash
python src/build_llm_comparison.py --source-dir "$SRC" --output-dir "$OUT" --env-file "$ENVF" --limit 10
python src/build_llm_comparison.py --source-dir "$SRC" --output-dir "$OUT" --env-file "$ENVF"
pytest -m slow tests/test_llm_compare_live.py
```

Open `$OUT/llm_image_report.html` in the browser pane and check: every PDF and web image has a row; counts per verdict add up to the total; a DIFFERENT row lists plausible differences; header tokens/cost match the sum of the rows; a second full run makes zero calls and costs nothing.

- [ ] **Step 5: Open the PR, then clean up after merge**

```bash
git push -u origin worktree-llm-image-compare
gh pr create --title "feat: DSPy visual comparison of the images the phash cannot settle" --body "<summary, spec/plan links, dry-run + calibration + full-run numbers>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

After the PR merges: delete the worktree, local branch and remote branch (`git branch -d worktree-llm-image-compare`, `git push origin --delete worktree-llm-image-compare`), and copy the generated report from the scratch directory into `output/` if wanted.

---

## Self-review

**Spec coverage** — Selection >= 90% inclusive incl. equations, skipped/unreadable/web-only: Tasks 2, 4, 10. Preprocessing (flatten, trim, scale-down-only, PNG): Task 3. Calibration for `max_edge` and batch size: Task 13. Prompt verbatim + batch paragraph, `prompt_version`, temperature 0, structured verdicts: Task 9. Batching by pair and token budget, single-pair re-queue, `ERROR` after retries: Tasks 5, 10. Async, rate limiter (RPM/TPM, correction by actual usage), 429/5xx backoff with Retry-After, no retry on other 4xx: Tasks 7, 9, 10. Tokens/cost from usage, price fallback, "cost unavailable", per-pair split, cache, dry-run: Tasks 6, 8, 12. Report with every image + verdict + header summary + filter/search + relative image paths: Tasks 4, 11. Config/.env, key never from file: Task 1. Error table (missing image, missing key, 429/5xx, partial response, Ctrl-C): Tasks 10, 12. Testing list: each task. DoD + worktree/PR: Task 14.

**Spec deviations to confirm:** per-pair *cost* shares sum to float precision rather than "exactly" (tokens are exact); `--limit` and `--source-dir/--env-file` are added options (a safe first trial, and running from a worktree); Ctrl-C builds the report from the cache and marks unfinished pairs `ERROR` (exit 130).

**Placeholder scan** — none: every step carries its code or command; the `--calibrate` flag and `_calibrate` are specified fully in Task 13.

**Trial run of this plan's code** — before handing it over, every file in Tasks 1-8 and 10-13 was extracted into a scratch copy of the repo and its tests run: 138 pass (config, domain, preprocess, pair source, batching, costing/pricing, limiter, cache, runner, report, estimate, calibration, CLI). Not yet exercised: `tests/test_llm_compare_judge.py` and the live test, which need `dspy` installed (Task 1 step 5) and the Task 9 step 1 API check. `ruff format` / import sorting are applied at Task 14's Definition of done.

**Type consistency** — `ImagePair.row_id` keys every dict (`settled`, `records`); `PreparedPair.row_id/key` delegate to it; `PairVerdict.verdict` is a `Verdict`; `Usage.cost` defaults `0.0`, `None` means unknown; `JudgeDeps` fields match the names used in Tasks 10, 12 and 13; `validate_verdicts` ids are 1-based batch positions, matching `build_manifest`.
