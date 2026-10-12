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

from llm_compare.analysis.calibration import (  # noqa: E402
    VariantResult,
    default_variants,
    format_calibration,
    run_variants,
    sample_evenly,
)
from llm_compare.analysis.estimate import format_plan, plan_run  # noqa: E402
from llm_compare.analysis.hash_score import score_pair  # noqa: E402
from llm_compare.analysis.limiter import RateLimiter  # noqa: E402
from llm_compare.analysis.pricing import resolve_prices  # noqa: E402
from llm_compare.analysis.prompt import PROMPT_VERSION  # noqa: E402
from llm_compare.analysis.runner import (  # noqa: E402
    JudgeDeps,
    RunOutcome,
    classify_pairs,
    run_comparison,
)
from llm_compare.config import (  # noqa: E402
    ConfigError,
    LlmCompareConfig,
    load_config,
    parse_dotenv,
)
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


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{value} is negative; use 0 or more")
    return value


def _positive_int(text: str) -> int:
    value = _non_negative_int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-dir", type=Path, default=PROJECT_ROOT / "output")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "llm_compare_config.toml")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit", type=_non_negative_int, default=None, help="judge only the first N pairs"
    )
    parser.add_argument(
        "--calibrate",
        type=_positive_int,
        default=None,
        metavar="N",
        help="judge N sample pairs under several settings and recommend max_edge",
    )
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
    # numpy/imagehash must already be loaded before dspy is imported (dspy's lazy-import hook
    # breaks numpy's first import); this module's top-level imports guarantee it.
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
        # An asyncio.Lock binds to the first event loop it contends in, so the second
        # asyncio.run needs a limiter of its own.
        limiter = RateLimiter(deps.config.rpm, deps.config.tpm)
        refusing = JudgeDeps(_RefusingJudge(), limiter, deps.cache, deps.config, PROMPT_VERSION)
        outcome = asyncio.run(run_comparison(pairs, load, refusing, limit=limit, scorer=score_pair))
        return outcome, True


def _setup(args, env: Mapping[str, str]) -> tuple[LlmCompareConfig, list]:
    config = load_config(_read_text(args.config), env, parse_dotenv(_read_text(args.env_file)))
    pdf_images, web_images, counterparts = _load_inputs(args.source_dir)
    return config, build_pairs(pdf_images, web_images, counterparts)


def _judged_run(args, config, pairs, cache, judge, now) -> int:
    limiter = RateLimiter(config.rpm, config.tpm)
    deps = JudgeDeps(judge or _real_judge(config), limiter, cache, config, PROMPT_VERSION)
    outcome, interrupted = _run(pairs, _loader(args.source_dir), deps, args.limit)
    _finish(outcome, config, args.source_dir, args.output_dir or args.source_dir, now)
    return 130 if interrupted else 0


def _save_calibration(results: list[VariantResult], output_dir: Path) -> None:
    saved = [
        {
            "variant": result.variant.name,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost": result.cost,
            "verdicts": {key: verdict.value for key, verdict in result.verdicts.items()},
        }
        for result in results
    ]
    (output_dir / "llm_compare").mkdir(parents=True, exist_ok=True)
    (output_dir / "llm_compare" / "calibration.json").write_text(json.dumps(saved, indent=2))


def _calibrate(count: int, args, config, pairs, judge) -> int:
    routed = classify_pairs(
        pairs, _loader(args.source_dir), config.hash_match_percent, score_pair
    ).to_llm
    shared_judge = judge or _real_judge(config)
    limiter = RateLimiter(config.rpm, config.tpm)

    def make_deps(settings):
        # A memory-only cache per variant, so each really calls the model and the real
        # cache.json is never written.
        return JudgeDeps(shared_judge, limiter, VerdictCache(), settings, PROMPT_VERSION)

    variants = default_variants(config.max_edge, config.max_pairs_per_call)
    results = asyncio.run(run_variants(sample_evenly(routed, count), variants, config, make_deps))
    print(format_calibration(results))
    _save_calibration(results, args.output_dir or args.source_dir)
    return 0


def _dry_run(args, config, pairs, cache) -> int:
    # The dry run calls nothing: stop litellm fetching its price map from GitHub on import.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    prices = resolve_prices(config)
    print(
        format_plan(
            plan_run(
                pairs, _loader(args.source_dir), config, cache, PROMPT_VERSION, prices, score_pair
            )
        )
    )
    return 0


def main(argv=None, env: Mapping[str, str] = os.environ, judge=None, now: str | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config, pairs = _setup(args, env)
    except (ConfigError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    cache = VerdictCache((args.output_dir or args.source_dir) / "llm_compare" / "cache.json")
    if args.dry_run:
        return _dry_run(args, config, pairs, cache)
    problem = _check_credentials(config, judge)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    if args.calibrate is not None:
        return _calibrate(args.calibrate, args, config, pairs, judge)
    return _judged_run(args, config, pairs, cache, judge, now)


if __name__ == "__main__":
    sys.exit(main())
