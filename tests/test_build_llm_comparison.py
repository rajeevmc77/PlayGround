import asyncio
import json
import os
import signal
import time

import pytest

import build_llm_comparison
from build_llm_comparison import main
from llm_compare.analysis.judge import DspyPairJudge
from llm_compare.analysis.limiter import RateLimiter
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
    web = {
        "images": [{"id": "a", "unified_number": "A.Fig1", "local_path": "web_images/a.png"}],
        "tree": {},
    }
    (root / "bcbc_pdf.json").write_text(json.dumps(pdf))
    (root / "bcbc_web.json").write_text(json.dumps(web))
    (root / "comparison.json").write_text(json.dumps({"counterparts": {}}))
    return root


def _args(source, *extra, out=None):
    return [
        "--source-dir",
        str(source),
        "--output-dir",
        str(out or source),
        "--config",
        str(source / "none.toml"),
        "--env-file",
        str(source / "none.env"),
        *extra,
    ]


def _report_rows(source):
    return json.loads((source / "llm_image_compare.json").read_text())["rows"]


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
    row = _report_rows(source)[0]
    assert row["verdict"] == "IDENTICAL" and row["input_tokens"] == 10
    assert (source / "llm_compare" / "cache.json").exists()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 0
    assert judge.calls == 1  # the second run is served from the cache


def test_a_cached_rerun_still_prints_what_all_the_verdicts_cost(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=AllIdentical(), now="t") == 0
    capsys.readouterr()
    assert main(_args(source), env=ENV, judge=AllIdentical(), now="t") == 0
    out = capsys.readouterr().out
    assert "calls 0, tokens 0 in / 0 out, cost 0" in out
    assert "all judged verdicts: tokens 11, cost 0.001" in out


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


def test_dry_run_keeps_litellm_off_the_network_by_using_its_local_price_map(tmp_path, monkeypatch):
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    assert main(_args(_source(tmp_path), "--dry-run"), env={"PATH": ""}) == 0
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_dry_run_respects_an_explicit_price_map_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    assert main(_args(_source(tmp_path), "--dry-run"), env={"PATH": ""}) == 0
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "False"


def test_a_missing_key_or_model_exits_before_any_call(tmp_path, capsys):
    source = _source(tmp_path)
    assert main(_args(source), env={"PATH": ""}, judge=None) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    assert main(_args(source), env={"GEMINI_API_KEY": "k"}, judge=None) == 2
    assert "GEMINI_MODEL" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_the_api_key_value_is_never_printed(tmp_path, capsys):
    source = _source(tmp_path)
    secret = {"GEMINI_API_KEY": "s3cr3t-key-value", "PATH": ""}
    assert main(_args(source), env=secret, judge=None) == 2
    captured = capsys.readouterr()
    assert "s3cr3t-key-value" not in captured.out + captured.err


def test_missing_input_files_exit_with_a_clear_message(tmp_path, capsys):
    assert main(_args(tmp_path), env=ENV, judge=AllIdentical()) == 2
    assert "bcbc_pdf.json" in capsys.readouterr().err


def test_an_invalid_config_file_exits_with_its_message(tmp_path, capsys):
    source = _source(tmp_path)
    (source / "bad.toml").write_text("rpm = 0")
    args = [
        "--source-dir",
        str(source),
        "--config",
        str(source / "bad.toml"),
        "--env-file",
        str(source / "none.env"),
    ]
    assert main(args, env=ENV, judge=AllIdentical()) == 2
    assert "rpm" in capsys.readouterr().err


class Interrupting:
    async def judge(self, pairs):
        raise KeyboardInterrupt


def test_an_interrupted_run_still_reports_with_unfinished_pairs_as_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=Interrupting(), now="t") == 130
    row = _report_rows(source)[0]
    assert row["verdict"] == "ERROR" and "interrupted" in row["message"]


def test_an_interrupted_run_makes_no_second_pass_with_a_second_limiter(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    made = []

    class Spy(RateLimiter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(build_llm_comparison, "RateLimiter", Spy)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=Interrupting(), now="t") == 130
    assert len(made) == 1


KEYS = "ABCDE"


def _many_sources(root):
    """Five pairs with distinct images (so distinct cache keys), all routed to the LLM."""
    _source(root)
    pdf_images, web_images = [], []
    for n, key in enumerate(KEYS):
        png = png_bytes(box=(5 + n, 5, 40, 30))
        (root / f"images/{key}.png").write_bytes(png)
        (root / f"web_images/{key}.png").write_bytes(png)
        pdf_images.append({"image_path": f"images/{key}.png", "unified_number": key})
        web_images.append({"id": key, "unified_number": key, "local_path": f"web_images/{key}.png"})
    (root / "bcbc_pdf.json").write_text(json.dumps({"images": pdf_images}))
    (root / "bcbc_web.json").write_text(json.dumps({"images": web_images}))
    (root / "settings.toml").write_text("max_pairs_per_call = 2\nworkers = 1\nsingle_retries = 1\n")
    return root


class CtrlCOnThirdCall:
    """Call 1 ([A, B]) answers A only; call 2 (B alone) answers nothing (wasted); call 3
    ([C, D]) is where the user presses Ctrl-C - a real SIGINT, `presses` times."""

    def __init__(self, presses=1):
        self.calls, self.presses, self.interrupted_at = 0, presses, None

    async def judge(self, pairs):
        self.calls += 1
        if self.calls == 1:
            return JudgeResult([PairVerdict(1, Verdict.IDENTICAL, ())], Usage(200, 20, 0.002))
        if self.calls == 2:
            return JudgeResult([], Usage(50, 5, 0.0005))
        self.interrupted_at = time.monotonic()
        for _ in range(self.presses):
            signal.raise_signal(signal.SIGINT)
        await asyncio.sleep(2)  # never finishes: the interrupt cancels it
        return JudgeResult([PairVerdict(n, Verdict.IDENTICAL, ()) for n in (1, 2)], Usage())


def _watch_limiter(monkeypatch, judge):
    late = []

    class Watched(RateLimiter):
        async def acquire(self, tokens):
            if judge.interrupted_at is not None:
                late.append(tokens)
            return await super().acquire(tokens)

    monkeypatch.setattr(build_llm_comparison, "RateLimiter", Watched)
    return late


def _interrupted_main(tmp_path, monkeypatch, judge):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    late = _watch_limiter(monkeypatch, judge)
    source = _many_sources(tmp_path)
    args = _args(source)
    args[args.index("--config") + 1] = str(source / "settings.toml")
    code = main(args, env=ENV, judge=judge, now="t")
    return code, source, late, time.monotonic() - judge.interrupted_at


def test_ctrl_c_keeps_finished_verdicts_live_and_marks_only_unfinished_pairs(tmp_path, monkeypatch):
    judge = CtrlCOnThirdCall()
    code, source, late, seconds = _interrupted_main(tmp_path, monkeypatch, judge)
    assert code == 130 and seconds < 1.0
    assert late == []  # nothing waits on the rate limiter once interrupted
    report = json.loads((source / "llm_image_compare.json").read_text())
    rows = {row["key"]: row for row in report["rows"]}
    a = rows["A"]
    assert (a["verdict"], a["cached"], a["input_tokens"], a["output_tokens"]) == (
        "IDENTICAL",
        False,
        200,
        20,
    )
    assert a["cost"] == pytest.approx(0.002) and a["batch_id"] == 1
    assert rows["B"]["verdict"] == "ERROR" and "no usable verdict" in rows["B"]["message"]
    for key in "CDE":
        assert rows[key]["verdict"] == "ERROR"
        assert rows[key]["message"] == "run interrupted before this pair was judged"
    summary = report["summary"]
    assert summary["calls"] == 3 == judge.calls
    assert (summary["input_tokens"], summary["output_tokens"]) == (250, 25)  # A + wasted B
    cache = json.loads((source / "llm_compare" / "cache.json").read_text())
    assert [entry["verdict"] for entry in cache.values()] == ["IDENTICAL"]


def test_a_second_ctrl_c_still_gets_the_report(tmp_path, monkeypatch):
    judge = CtrlCOnThirdCall(presses=2)
    code, source, late, seconds = _interrupted_main(tmp_path, monkeypatch, judge)
    assert code == 130 and seconds < 1.0 and late == []
    rows = {row["key"]: row for row in _report_rows(source)}
    assert rows["A"]["verdict"] == "IDENTICAL" and rows["E"]["verdict"] == "ERROR"
    assert (source / "llm_compare" / "cache.json").exists()


class AnswersThenCtrlCWhileWaiting:
    """Answers at once; on the second call it arranges for the user to press Ctrl-C `presses`
    times 0.1 s later, while the workers wait ~60 s on the rate limiter (rpm = 2)."""

    def __init__(self, presses):
        self.calls, self.presses, self.interrupted_at = 0, presses, None

    def _press(self):
        self.interrupted_at = time.monotonic()
        for _ in range(self.presses):
            signal.raise_signal(signal.SIGINT)

    async def judge(self, pairs):
        self.calls += 1
        if self.calls == 2:
            asyncio.get_running_loop().call_later(0.1, self._press)
        verdicts = [PairVerdict(n, Verdict.IDENTICAL, ()) for n in range(1, len(pairs) + 1)]
        return JudgeResult(verdicts, Usage(10, 1, 0.001))


@pytest.mark.parametrize("presses", [1, 5])
def test_ctrl_c_while_workers_wait_on_the_rate_limiter_reports_at_once(
    tmp_path, monkeypatch, presses
):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _many_sources(tmp_path)
    (source / "settings.toml").write_text("max_pairs_per_call = 1\nworkers = 2\nrpm = 2\n")
    args = _args(source)
    args[args.index("--config") + 1] = str(source / "settings.toml")
    judge = AnswersThenCtrlCWhileWaiting(presses)
    assert main(args, env=ENV, judge=judge, now="t") == 130
    assert time.monotonic() - judge.interrupted_at < 1.0
    verdicts = [row["verdict"] for row in _report_rows(source)]
    assert verdicts == ["IDENTICAL", "IDENTICAL", "ERROR", "ERROR", "ERROR"]
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


class PressesThroughTheHandler:
    """Calls the SIGINT handler in force three times, as repeated presses would: a handler
    that raises KeyboardInterrupt (asyncio.run's does from the second press) can land inside
    asyncio's own code and hang or break the loop's teardown - seen with real signals."""

    def __init__(self):
        self.raised, self.interrupted_at = 0, None

    async def judge(self, pairs):
        handler = signal.getsignal(signal.SIGINT)
        self.interrupted_at = time.monotonic()
        for _ in range(3):
            try:
                handler(signal.SIGINT, None)
            except KeyboardInterrupt:
                self.raised += 1
        await asyncio.sleep(2)  # cancelled by the first press
        return JudgeResult([], Usage())


def test_repeated_ctrl_c_presses_never_raise_inside_the_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    judge = PressesThroughTheHandler()
    assert main(_args(source), env=ENV, judge=judge, now="t") == 130
    assert judge.raised == 0 and time.monotonic() - judge.interrupted_at < 1.0
    assert _report_rows(source)[0]["message"] == "run interrupted before this pair was judged"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_ctrl_c_while_the_report_is_written_does_not_lose_it(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    real_write = build_llm_comparison.write_report

    def write_while_interrupted(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)
        return real_write(*args, **kwargs)

    monkeypatch.setattr(build_llm_comparison, "write_report", write_while_interrupted)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=AllIdentical(), now="t") == 0
    assert _report_rows(source)[0]["verdict"] == "IDENTICAL"
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_ctrl_c_before_any_pair_is_judged_exits_130_without_a_report(tmp_path, monkeypatch, capsys):
    def interrupted_scorer(pair, pdf, web):
        raise KeyboardInterrupt

    monkeypatch.setattr(build_llm_comparison, "score_pair", interrupted_scorer)
    source = _source(tmp_path)
    assert main(_args(source), env=ENV, judge=AllIdentical(), now="t") == 130
    assert "interrupted" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_a_negative_limit_is_rejected_by_the_argument_parser_before_any_work(tmp_path, capsys):
    source = _source(tmp_path)
    judge = AllIdentical()
    with pytest.raises(SystemExit) as raised:
        main(_args(source, "--limit", "-1"), env=ENV, judge=judge)
    assert raised.value.code == 2 and judge.calls == 0
    assert "limit" in capsys.readouterr().err
    assert not (source / "llm_image_report.html").exists()


def test_a_non_numeric_limit_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(_args(_source(tmp_path), "--limit", "many"), env=ENV, judge=AllIdentical())
    assert raised.value.code == 2


def test_a_limit_of_zero_judges_nothing_and_skips_the_pairs_for_the_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    judge = AllIdentical()
    assert main(_args(source, "--limit", "0"), env=ENV, judge=judge, now="t") == 0
    row = _report_rows(source)[0]
    assert judge.calls == 0 and row["verdict"] == "SKIPPED"
    assert "not judged: --limit reached" in row["message"]


def test_calibrate_prints_a_recommendation_and_saves_the_variants(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    assert main(_args(source, "--calibrate", "1"), env=ENV, judge=AllIdentical()) == 0
    assert "recommended max_edge" in capsys.readouterr().out
    saved = json.loads((source / "llm_compare" / "calibration.json").read_text())
    assert saved[0]["variant"].startswith("original size")
    assert saved[0]["verdicts"] == {"pdf:images/a.png": "IDENTICAL"}
    assert not (source / "llm_image_report.html").exists()
    assert not (source / "llm_compare" / "cache.json").exists()


class ThreeTimesTheEstimate:
    """Reports 3x the input tokens we estimate for the call (overhead 1 in this config)."""

    async def judge(self, pairs):
        verdicts = [PairVerdict(n, Verdict.IDENTICAL, ()) for n in range(1, len(pairs) + 1)]
        return JudgeResult(verdicts, Usage(3 * (sum(p.tokens for p in pairs) + 1), 1, 0.0))


def test_calibrate_checks_the_token_estimate_against_usage_with_the_configured_scale(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(build_llm_comparison, "score_pair", lambda pair, pdf, web: 10.0)
    source = _source(tmp_path)
    (source / "scale.toml").write_text("token_scale = 2.0\ncall_overhead_tokens = 1\n")
    args = _args(source, "--calibrate", "1")
    args[args.index("--config") + 1] = str(source / "scale.toml")
    assert main(args, env=ENV, judge=ThreeTimesTheEstimate()) == 0
    out = capsys.readouterr().out
    assert "estimated vs actual input tokens" in out
    # usage is 3x the estimate made with the configured token_scale 2.0: suggest 6.0
    assert out.splitlines()[-1] == (
        "actual input tokens were 3.00x the estimate: suggest token_scale = 6.00 "
        "in llm_compare_config.toml"
    )
    saved = json.loads((source / "llm_compare" / "calibration.json").read_text())
    assert all(v["input_tokens"] == 3 * v["estimated_input_tokens"] > 0 for v in saved)


@pytest.mark.parametrize("value", ["0", "-3", "many"])
def test_an_invalid_calibrate_count_is_rejected_before_any_work(tmp_path, value):
    source = _source(tmp_path)
    judge = AllIdentical()
    with pytest.raises(SystemExit) as raised:
        main(_args(source, "--calibrate", value), env=ENV, judge=judge)
    assert raised.value.code == 2 and judge.calls == 0
    assert not (source / "llm_compare").exists()


def test_with_a_key_and_a_model_the_credential_check_passes():
    config = build_llm_comparison.LlmCompareConfig(api_key="k", model="gemini-x")
    assert build_llm_comparison._check_credentials(config, None) is None


def test_the_real_judge_is_a_dspy_judge_for_the_configured_model():
    config = build_llm_comparison.LlmCompareConfig(api_key="k", model="gemini-x")
    assert isinstance(build_llm_comparison._real_judge(config), DspyPairJudge)
