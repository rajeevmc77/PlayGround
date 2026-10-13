"""Judge, with a multimodal LLM (DSPy), the PDF/web image pairs the perceptual hash cannot
settle, and write a report of every image with its verdict, tokens and cost.

    python src/build_llm_comparison.py --dry-run       # counts + estimated tokens/cost/time
    python src/build_llm_comparison.py --calibrate 24  # optional: max_edge / batch size, no report
    python src/build_llm_comparison.py --limit 10      # try 10 pairs first (writes the report)
    python src/build_llm_comparison.py                 # the full run (resumable; writes the report)
    open output/llm_image_report.html                  # only a normal run writes the report

GEMINI_API_KEY and GEMINI_MODEL come from the environment or .env; other settings from
llm_compare_config.toml (see llm_compare_config.example.toml). Inputs are read from
--source-dir (default output/); the report and cache go to --output-dir (default the same).
The report links each image to its page in --pdf and to its element in the saved web pages.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

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
from llm_compare.output.cache import VerdictCache  # noqa: E402
from llm_compare.output.links import resolve_links  # noqa: E402
from llm_compare.output.report import (  # noqa: E402  # noqa: E402
    build_report,
    format_time_line,
    write_report,
)
from llm_compare.parsing.pair_source import build_pairs  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = PROJECT_ROOT / "data" / "MO Package BCBC MRK signed.pdf"
INPUT_FILES = ("bcbc_pdf.json", "bcbc_web.json", "comparison.json")
CALIBRATE_NOTE = (
    "note: --calibrate does not build the HTML report; run without --calibrate "
    "(add --limit N to try N pairs) to write llm_image_report.html"
)


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
    parser.add_argument(
        "--pdf",
        type=Path,
        default=PDF_PATH,
        help="the PDF the report's PDF links open (at the image's page)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit", type=_non_negative_int, default=None, help="judge only the first N pairs"
    )
    parser.add_argument(
        "--calibrate",
        type=_positive_int,
        default=None,
        metavar="N",
        help="judge N sample pairs under several settings and recommend max_edge "
        "(prints a table and writes llm_compare/calibration.json; no HTML report)",
    )
    return parser


def _read_text(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


class InputError(Exception):
    """An input file is not JSON shaped the way the PDF/web/comparison builds write it."""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"{path.name} is not valid JSON: {error}") from error


def _images(name: str, data) -> list:
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, list):
        raise InputError(f'{name} has no "images" list - rebuild it')
    return images


def _counterparts(data) -> dict:
    counterparts = data.get("counterparts", {}) if isinstance(data, dict) else None
    if not isinstance(counterparts, dict):
        raise InputError('comparison.json has no "counterparts" object - rebuild it')
    return counterparts


def _load_inputs(source_dir: Path) -> tuple[list[dict], list[dict], dict]:
    missing = [name for name in INPUT_FILES if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing in {source_dir}: {', '.join(missing)}")
    pdf, web, comparison = (_read_json(source_dir / name) for name in INPUT_FILES)
    return _images("bcbc_pdf.json", pdf), _images("bcbc_web.json", web), _counterparts(comparison)


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


def _page_reader(source_dir: Path):
    def read(page_file: str) -> str | None:
        path = source_dir / page_file
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None

    return read


def _pdf_href(pdf_path: Path, output_dir: Path) -> str | None:
    """The PDF's url-quoted path relative to the report, None (with a note) when it is not there."""
    if not pdf_path.is_file():
        print(f"PDF not found at {pdf_path}: PDF links are omitted")
        return None
    return quote(Path(os.path.relpath(pdf_path, output_dir)).as_posix())


def _links_for(outcome: RunOutcome, source_dir: Path, output_dir: Path, pdf_path: Path):
    return resolve_links(
        outcome.records,
        read_page=_page_reader(source_dir),
        pdf_href=_pdf_href(pdf_path, output_dir),
        asset_prefix=_asset_prefix(source_dir, output_dir),
    )


def _report_for(outcome: RunOutcome, config, now, links) -> dict:
    return build_report(
        outcome.records,
        calls=outcome.calls,
        wasted=outcome.wasted,
        model=config.model,
        prompt_version=PROMPT_VERSION,
        generated_at=now or datetime.now(UTC).isoformat(timespec="seconds"),
        scoring_seconds=outcome.scoring_seconds,
        judging_seconds=outcome.judging_seconds,
        call_seconds=outcome.call_seconds,
        links=links,
    )


def _finish(outcome: RunOutcome, config, source_dir, output_dir, now, pdf_path) -> None:
    report = _report_for(
        outcome, config, now, _links_for(outcome, source_dir, output_dir, pdf_path)
    )
    _, html_path = write_report(report, output_dir, _asset_prefix(source_dir, output_dir))
    _print_summary(html_path, report["summary"])


def _print_summary(html_path: Path, summary: dict) -> None:
    print(f"report: {html_path}")
    print(f"verdicts: {summary['counts']}")
    print(
        f"calls {summary['calls']}, tokens {summary['input_tokens']:,} in / "
        f"{summary['output_tokens']:,} out, cost {summary['cost']}"
    )
    print(
        f"all judged verdicts: tokens {summary['cumulative_total_tokens']:,}, "
        f"cost {summary['cumulative_cost']}"
    )
    print(format_time_line(summary))


@contextmanager
def _sigint_ignored():
    """Hold off Ctrl-C for the moment (well under a second) the report takes to write, so a
    second press after an interrupt cannot lose it."""
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def _setup(args, env: Mapping[str, str]) -> tuple[LlmCompareConfig, list]:
    config = load_config(_read_text(args.config), env, parse_dotenv(_read_text(args.env_file)))
    pdf_images, web_images, counterparts = _load_inputs(args.source_dir)
    return config, build_pairs(pdf_images, web_images, counterparts)


def _judged_run(args, config, pairs, cache, judge, now) -> int:
    limiter = RateLimiter(config.rpm, config.tpm)
    deps = JudgeDeps(judge or _real_judge(config), limiter, cache, config, PROMPT_VERSION)
    try:
        outcome = run_comparison(
            pairs, _loader(args.source_dir), deps, limit=args.limit, scorer=score_pair
        )
    except KeyboardInterrupt:
        # Only scoring/preparing (before any call) lets Ctrl-C through: nothing to report.
        print("error: interrupted before any pair was judged; no report written", file=sys.stderr)
        return 130
    with _sigint_ignored():
        output_dir = args.output_dir or args.source_dir
        _finish(outcome, config, args.source_dir, output_dir, now, args.pdf)
    return 130 if outcome.interrupted else 0


def _save_calibration(results: list[VariantResult], output_dir: Path) -> Path:
    saved = [
        {
            "variant": result.variant.name,
            "input_tokens": result.input_tokens,
            "estimated_input_tokens": result.estimated_input_tokens,
            "output_tokens": result.output_tokens,
            "cost": result.cost,
            "first_error": result.first_error,
            "elapsed_seconds": result.elapsed_seconds,
            "verdicts": {key: verdict.value for key, verdict in result.verdicts.items()},
        }
        for result in results
    ]
    path = output_dir / "llm_compare" / "calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, indent=2))
    return path


def _calibrate(count: int, args, config, pairs, judge) -> int:
    routed = classify_pairs(
        pairs,
        _loader(args.source_dir),
        config.hash_match_percent,
        score_pair,
        config.scoring_workers,
    ).to_llm
    shared_judge = judge or _real_judge(config)
    limiter = RateLimiter(config.rpm, config.tpm)

    def make_deps(settings):
        # A memory-only cache per variant, so each really calls the model and the real
        # cache.json is never written.
        return JudgeDeps(shared_judge, limiter, VerdictCache(), settings, PROMPT_VERSION)

    variants = default_variants(config.max_edge, config.max_pairs_per_call)
    results = asyncio.run(run_variants(sample_evenly(routed, count), variants, config, make_deps))
    print(format_calibration(results, config.token_scale))
    saved = _save_calibration(results, args.output_dir or args.source_dir)
    print(f"saved: {saved.resolve()}")
    print(CALIBRATE_NOTE)
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
    except (ConfigError, FileNotFoundError, InputError) as error:
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
